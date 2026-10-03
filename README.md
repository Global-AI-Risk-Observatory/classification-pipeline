# airo: classification pipeline for AI-related content in corporate filings

`airo` classifies how companies write about AI in their filings: whether a passage is about AI at all,
what role AI plays for the company (market driver, own adoption, offering, risk, governance, incident),
which risk is meant, and how specific the statement is. It is built to start with a handful of example reports and
designed so that the same stages can be applied to millions; what is and is not in place for that is
listed under "Design" and "Known limits".

## Install

Python 3.10 or later; depends on `lxml` and `pydantic`, and on `pytest` for the tests.
Without installing, prefix the commands below with `PYTHONPATH=src`.

    pip install -e ".[dev]"

## Stages and files

Interim layout: all files live in one local working directory, set with `--data` (default
`data`). The target deployment is Google Cloud (filings and per-document outputs in Cloud
Storage, labels and summaries in BigQuery, runs as Cloud Batch jobs); the local layout exists
for development until the cloud project is set up.

| Stage | Command | Reads | Writes |
|---|---|---|---|
| 1+2 ingest, retrieve | `run <dir-or-files...>` | HTML / inline XBRL filings, `index/files.jsonl` | `docs/<doc_id>/document.json`, `docs/<doc_id>/blocks.jsonl`, `docs/<doc_id>/passages.jsonl`, `index/files.jsonl` |
| 3 classify | `tasks` | `docs/*/document.json`, `docs/*/passages.jsonl` | `tasks.jsonl`, `hints.jsonl`, `codebook.md` |
| | `accept <file> --coder X` | a coder's JSONL file, `docs/*/passages.jsonl` | `labels/X.jsonl` |
| | `adjudicate` | `labels/*.jsonl` | `labels_final.jsonl`, `agreement.json` |
| 4 aggregate | `aggregate` | `docs/*/document.json`, `docs/*/passages.jsonl`, `labels_final.jsonl` | `report_summary.jsonl`, `reports/<doc_id>.md` |

Run them in this order. `--data` is a global option and goes before the sub-command.

    python -m airo --data data run filings/ --manifest manifest.jsonl
    python -m airo --data data tasks
    # a coder labels data/tasks.jsonl following data/codebook.md and returns one JSON object per line
    python -m airo --data data accept alice.jsonl --coder alice
    python -m airo --data data adjudicate
    python -m airo --data data aggregate

- `run` takes files or directories (`*.htm*` in a directory) and processes every file on its own: it
  parses the filing into one document record (metadata from the inline XBRL `dei:` facts, the file's row
  of `--manifest`, word count, text coverage, sections) and ordered text blocks (paragraphs, headings,
  list items and table rows with cells joined by ` | `), finds the candidate passages and writes the three
  files of `docs/<doc_id>/`. `--workers N` processes run at a time (default: all CPUs). `--context N`
  sets how many neighbouring blocks are taken on each side of a hit (default 1).
- `--manifest` is a JSONL file with one row per input file, `{"file": "<name>", "isic_class": "0721", ...}`;
  every other key is copied into the document record. `isic_class` selects the industry glossary; without
  it only the core glossary is used. When filings come from the data provider's API, the manifest is
  written from its company metadata (`sub_industry_code` is the ISIC class).
- `run` can be re-issued at any time. `index/files.jsonl` lists every file seen, and a file whose bytes
  are already indexed is skipped, so an interrupted run resumes where it stopped and new files can be
  dropped into the directory. A file that failed is skipped as well, unless `--retry-failed` is given.
  The run prints a line per processed file and ends with the done / duplicate / skipped / failed counts
  and the files per second.
- `accept` is run once per coder. If any line is rejected it writes nothing, unless `--partial` is given.
- `adjudicate` is needed with a single coder too: `aggregate` reads `labels_final.jsonl`.

## Automated coder (Gemini on Vertex AI)

`airo.coders.gemini` labels `tasks.jsonl` with a Gemini model on Google Cloud Vertex AI, one request per
passage, in JSON mode with the `Label` schema from `taxonomy.py`, at temperature 0. It writes the labels
that pass the pipeline's own validation as JSONL for `accept`, and a `<out>.run.json` beside it with the
run's totals (tasks, succeeded, failed, tokens by kind, wall time, model, estimated cost).

    python -m airo.coders.gemini --tasks data/tasks.jsonl --codebook data/codebook.md \
        --out data/labels_in/gemini.jsonl --model gemini-2.5-flash \
        --project <gcp-project-id> --location us-central1 \
        [--workers 4] [--thinking-budget N] [--price-input X --price-output Y] [--limit N]
    python -m airo --data data accept data/labels_in/gemini.jsonl --coder gemini

It needs: the `google-genai` package (`pip install google-genai`); a Google Cloud project with the
Vertex AI API enabled; credentials from `gcloud auth application-default login` (or a service account
set in `GOOGLE_APPLICATION_CREDENTIALS`); and a model name available in the chosen region. Prices are not
built in: give `--price-input` and `--price-output` in USD per million tokens to get a cost estimate
(thinking tokens are billed as output tokens). On thinking models the thinking tokens count against the
output limit, so `--max-output-tokens` defaults to 4096 and `--thinking-budget` caps the thinking.
Failed passages (transient errors after retries, invalid or schema-breaking output, paraphrased
evidence) are listed in the run file and left out of the labels file; re-run with `--limit` or a
filtered task file to retry them. The live call has not yet been exercised: the module was written
against the SDK's documented interface and tested only with a fake client.

## Design

- **Documents are identified by their text, not their bytes.** `doc_id` is the first 16 hex characters of
  the SHA-256 of the extracted, whitespace-normalised block text. The same filing downloaded twice (for
  example with a different Cloudflare e-mail token in the markup) becomes one document with two
  `source_files`. Because the hash is taken over the extracted blocks, a change to the block extraction
  changes the ids.
- **Stages communicate only through files.** Every stage reads the files of earlier stages and writes its
  own; data passes as JSONL, one record per line (`document.json`, `codebook.md`, `agreement.json` and
  `reports/*.md` are the non-JSONL outputs). A stage can be re-run without re-running the ones before it.
- **Each filing is an independent unit of work.** `runner.process` takes one file through parsing,
  manifest metadata and passage retrieval and writes the result to its own directory `docs/<doc_id>/`
  (`document.json`, `blocks.jsonl`, `passages.jsonl`). Nothing is shared between files, so `run` hands
  them to a pool of worker processes (`--workers`, default all CPUs); each worker builds the glossary
  matcher itself and caches it per industry. A directory is written under a temporary name and renamed
  when complete, so a reader never sees a half-written document. A file whose text is already in
  `docs/` (a second download of the same filing) is not processed again: its name is added to
  `source_files`. One bad file is recorded as failed and the run goes on.
- **Runs are resumable and incremental.** `index/files.jsonl` gets one row per input file (SHA-256 of
  the bytes, path, `doc_id` or `error`, timestamps) and is only ever appended to. `run` skips every file
  whose hash is in the index, so an interrupted run resumes by re-issuing the same command, and new
  files can be added at any time. The later stages iterate over `docs/*/` one document at a time and
  never load all blocks at once.
- **A cheap lexical step selects what gets classified.** Every block is searched with the glossaries
  under `glossaries/`: `core.json` (500 sector-independent AI terms) plus the glossary of the company's
  industry, `isic/<division>.json`, chosen from the 4-digit ISIC Rev. 5 class in the manifest (the
  classification the data provider attaches to every company; `isic_rev5.json` holds the official
  structure), including that file's `class_terms` for the exact class. Terms have a tier: `ai` (the term
  itself denotes AI) or `context` (industry lingo around which AI is discussed, such as "data center" for
  a uranium miner). This gives two kinds of mention: a passage with at least one `ai` hit is a **direct
  mention** and goes to the classifier as a task; a passage with `context` hits only is an **implicit
  mention** and is not classified but handed on as a hint, with its text and the wordings found, in
  `hints.jsonl` and at the end of the report view. Phrases match
  as whole words with plural and hyphen/space variation; short acronyms are case-sensitive. A trie-merged
  pre-filter keeps the search at about one second per 10-K. A hit block and its neighbours form a passage
  (page furniture is skipped, a following heading ends the window); overlapping or touching windows merge,
  and a window never crosses a section boundary. Only these passages become tasks, so a report without a
  hit costs no classification. The classifier can still label a candidate `none`.
- **The classifier stage is defined by two files, not by who codes.** `tasks.jsonl` (passage plus company,
  form, fiscal year, section, heading, matched terms) and `codebook.md` go in; one label per passage comes
  back as JSONL. A coder can be a person, an agent or a batch job against a model API.
- **Every accepted label is validated.** `accept` checks each line against the schema in `taxonomy.py`,
  rejects unknown and duplicate passage ids and evidence that is not a verbatim quote from the passage
  (whitespace differences are tolerated), and reports passages without a label. Accepted labels and
  adjudicated labels carry `taxonomy_version`.
- **Several coders are reconciled by majority vote.** `adjudicate` takes, per passage and field, the value
  that more than half of the coders chose (per value for `roles` and `risk_types`). A passage with a field
  without majority, or with a coder missing, is flagged `needs_review`. `agreement.json` reports, per
  field, the share of passages on which all coders agree, the share of coder pairs with identical labels,
  and the passages to review.

## Taxonomy v0.4

One label per passage. `taxonomy.py` is the single definition; `python -m airo tasks` renders it as the
full codebook, with a definition and a checklist of criteria for every value (a value applies only if all
its criteria hold) and the decision rules, to `data/codebook.md`. Since v0.4 the coder fixes the `frame`
of the AI statement before judging any role or trait; criteria marked "frame-dependent" in the codebook
(`market_driver`, `adoption`, `governance`, `externalisation`) are read in that frame.

| Field | Allowed values | Rule |
|---|---|---|
| `ai_reference` | `explicit`, `implicit`, `none` | exactly one, judged from the passage alone; with `none` the next six fields and `evidence` stay empty |
| `frame` | `risk_factor`, `governance`, `business`, `market` | exactly one when the passage is about AI, decided from section, heading and sentence function before any role or trait; `null` if and only if `ai_reference` is `none` |
| `roles` | `market_driver`, `adoption`, `offering`, `risk`, `governance`, `incident`, `general` | one or more; `general` only alone |
| `risk_types` | `market_demand`, `strategic_competitive`, `operational_reliability`, `cybersecurity`, `third_party`, `regulatory_legal`, `workforce`, `reputational_ethical`, `information_integrity`, `environmental`, `other` | one or more if and only if `risk` is a role |
| `adoption_stage` | `planned`, `piloting`, `deployed`, `unclear` | exactly one if and only if `adoption` is a role |
| `ai_kind` | `generative`, `non_generative`, `unspecified` | exactly one |
| `disclosure_traits` | `boilerplate`, `hedging`, `externalisation`, `vagueness`, `safe_harbour` | zero or more; `[]` when no trait applies (the statement is specific) and always when `ai_reference` is `none`; `externalisation` never in frame `market` |
| `entities` | list of names | organisations or AI products named in connection with AI |
| `evidence` | list of 1 to 3 quotes | verbatim quotes from the passage, one per role where the roles rest on different sentences; `[]` if and only if `ai_reference` is `none` |
| `confidence` | `low`, `medium`, `high` | always required |
| `note` | text | optional |

## Known limits

- Section detection knows only Form 10-K "Item" headings ("Item 1A. Risk Factors"). A block belongs to the
  most recent Item heading, so content after the last one, such as the financial statements, is attributed
  to that last item. Other forms and other report formats get no sections.
- The glossaries are English only, and were written from domain knowledge, not mined from filings; they
  have been exercised on one 10-K so far and need review against real reports per industry.
- The Gemini coder has not yet been run against Vertex AI (no credentials in the development
  environment); the three-coder runs so far were done by agents handing in label files.
- Input is HTML / inline XBRL only. There is no PDF reader. Metadata comes only from inline XBRL `dei:`
  facts and is empty for plain HTML.
- `run` parallelises over the cores of one machine; there is no distribution over several machines yet.
  Two `run` commands on the same `--data` directory at the same time are not supported: each reads the
  index once at start and removes the other's temporary directories. The skip is by file hash, so a file
  is re-processed only if its bytes change or `--retry-failed` is given; a changed glossary or parser
  needs a fresh `--data` directory. `document.json` of a document is rewritten in place when a duplicate
  adds a `source_files` entry.
- `tasks` has no filter: it rewrites `tasks.jsonl` for every document under `docs/`. `accept` and
  `aggregate` hold all passages, or all final labels, in memory at once.
- `adjudicate` does not re-validate the files in `labels/` and does not check their `taxonomy_version`;
  it votes over every `*.jsonl` file it finds there and stamps the current version on the result.

## Tests

    python3 -m pytest -q

The tests use synthetic HTML written to a temporary directory; they need no network and no `data/`.
pytest is configured with `pythonpath = src`, so the package itself does not have to be installed.
