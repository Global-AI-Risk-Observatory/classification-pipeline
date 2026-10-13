# airo: classification pipeline for AI-related content in corporate filings

`airo` classifies how companies write about AI in their filings: whether a passage is about AI at all,
what role AI plays for the company (market driver, own adoption, offering, risk, governance, incident),
which risk is meant, and how specific the statement is.

The filings are those of US companies. They come from one source, the FinancialReports API
(financialfilings.com), as Markdown, and are kept in Google Cloud Storage, not on anyone's machine and not
in this repository. Every team member fetches with their own API key; a filing that is already in the
bucket is not fetched again.

The pipeline is built to start with a handful of example reports and designed so that the same stages can
be applied to millions; what is and is not in place for that is listed under "Design" and "Known limits".

## Install

Python 3.10 or later; depends on `lxml` and `pydantic`, and on `pytest` for the tests.
Without installing, prefix the commands below with `PYTHONPATH=src`.

    pip install -e ".[dev,gcs]"

`gcs` adds `google-cloud-storage`, which `fetch` needs to write to the bucket. Two things are set up once
per person:

1. Google Cloud credentials, with the Google account that has access to project `gario-1`:

       gcloud auth application-default login

2. The personal API key of the data provider, in a file `.env.local` in the repository root:

       FR_API_KEY=<your key>

   Git ignores `.env*`; the key must never be committed or put into the cloud configuration.

## Stages and files

The filings live in the raw bucket `gs://airo-filings-raw`, written by `fetch`. Everything the later
stages produce lives in one working directory, set with `--data` (default `data`): locally a directory, in
the cloud the mounted bucket `airo-pipeline-data` (see "Google Cloud" below). Labels and summaries move to
BigQuery once the first cloud runs are done.

| Stage | Command | Reads | Writes |
|---|---|---|---|
| 0 download | `fetch <out> --types T` | the data provider's API (US companies, Markdown only), the names already in `<out>` | `<out>/markdown/<filing id>.md`, `<out>/manifest/<filing id>.json`, once `<out>/companies/us.jsonl` |
| 1+2 ingest, retrieve | `run <dir-or-files...>` | Markdown filings (also HTML / inline XBRL), `index/files.jsonl` | `docs/<doc_id>/document.json`, `docs/<doc_id>/blocks.jsonl`, `docs/<doc_id>/passages.jsonl`, `index/files.jsonl` |
| 3 classify | `tasks` | `docs/*/document.json`, `docs/*/passages.jsonl` | `tasks.jsonl`, `hints.jsonl`, `codebook.md` |
| | `accept <file> --coder X` | a coder's JSONL file, `docs/*/passages.jsonl` | `labels/X.jsonl` |
| | `adjudicate` | `labels/*.jsonl` | `labels_final.jsonl`, `agreement.json` |
| 4 aggregate | `aggregate` | `docs/*/document.json`, `docs/*/passages.jsonl`, `labels_final.jsonl` | `report_summary.jsonl`, `reports/<doc_id>.md`, `recall_check.json` |

Run them in this order. `--data` is a global option and goes before the sub-command. `<raw>` is the path
under which the raw bucket is mounted (in a Batch job; `run` reads files, not `gs://` locations).

    python -m airo fetch gs://airo-filings-raw --types 10-K --since 2025-01-01 --until 2025-03-31 --limit 100
    python -m airo --data data run <raw>/markdown --manifest <raw>/manifest
    python -m airo --data data tasks
    # a coder labels data/tasks.jsonl following data/codebook.md and returns one JSON object per line
    python -m airo --data data accept alice.jsonl --coder alice
    python -m airo --data data adjudicate
    python -m airo --data data aggregate

- `fetch` copies filings of US companies from the FinancialReports API (financialfilings.com) into the raw
  bucket. It stores the provider's Markdown rendering of each filing and nothing else: `markdown/<filing id>.md`
  and, next to it, its metadata as `manifest/<filing id>.json` (ISIC class, country, company, LEI, CIK, ticker,
  exchange, form, fiscal year and period, period end, filing date, source filing id, release time). `<out>` is `gs://bucket[/prefix]` or a directory (the mounted bucket in a Batch job);
  nothing is kept on the machine that runs the command.
  - **A filing is stored once.** Its name is the provider's filing id, so it is the same whoever fetches it.
    `fetch` first reads the names already in `<out>` and skips those filings without an API request; objects
    are created with a "only if absent" condition and never overwritten, so two people fetching at the same
    time leave one copy. The call ends with the stored / already present / failed counts.
  - **What is fetched is chosen on the command line.** `--types` (required) takes the provider's filing type
    codes. The provider's type `10-K` ("annual report") covers several SEC forms for US companies: 10-K
    (159,376 filings in October 2026), 10-K/A (34,958), ARS (34,003), N-CSR (6,740), 20-F (5,688), 40-F (440),
    10-KT (111). `--form 10-K` narrows to one of them; an ARS often repeats the 10-K of the same company under
    another filing id. `--since` / `--until` bound the release date, `--limit` the filings stored per call
    (default 10).
  - **Metadata costs no request per filing.** The filing's own (fiscal year, period, period end, filing date,
    source filing id) comes with the listing that is read anyway (`view=full`). The company's (CIK, ticker,
    exchange) comes from the provider's list of US companies, which the first `fetch` reads once (about 220
    requests for 22,027 companies, three minutes) and keeps as `companies/us.jsonl` in `<out>`; every later
    `fetch`, by anyone, reads it from there. A company that is not in that list is asked for once and kept as
    `companies/<id>.json`. Where the provider has no value, the filing's cover page is used (form, fiscal year,
    period end, ticker, exchange). Where that has none either, the field holds the notice
    `not provided by the data provider` instead of being left out, and the line that `fetch` prints for the
    filing names the fields. In October 2026 the provider's list had a CIK for 21,973 of the 22,027 companies,
    a ticker for 10,964 and an exchange for 5,570.
  - **The API key is personal**, because the provider counts requests per key (one request per filing plus one
    per 100 listed). Put `FR_API_KEY=<your key>` in `.env.local` in the repository root (ignored by git) or
    export it; it is sent to the API only.
- `run` takes files or directories (`*.md` and `*.htm*` in a directory) and processes every file on its own: it
  parses the filing into one document record (form and fiscal period from the cover page of a Markdown filing or
  from the inline XBRL `dei:` facts of an HTML one, the file's row
  of `--manifest`, word count, text coverage, sections) and ordered text blocks (paragraphs, headings,
  list items and table rows with cells joined by ` | `), finds the candidate passages and writes the three
  files of `docs/<doc_id>/`. `--workers N` processes run at a time (default: all CPUs). `--context N`
  sets how many neighbouring blocks are taken on each side of a hit (default 1).
- `--manifest` is the `manifest/` directory that `fetch` writes (one JSON file per filing) or a JSONL file with
  one row per input file, `{"file": "<name>", "isic_class": "0721", ...}`;
  every other key is copied into the document record. `isic_class` selects the industry glossary; without
  it only the core glossary is used. `fetch` takes it from the provider's company metadata
  (`sub_industry_code`).
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
        --out data/labels_in/gemini.jsonl --model gemini-3.8-flash \
        --project gario-1 --location us-central1 \
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

## Google Cloud

The pipeline is deployed on Google Cloud; the settings are in `cloud/config.env` (no secrets).

| Item | Value |
|---|---|
| Project | `gario-1`, region `us-central1` |
| Raw filings | bucket `airo-filings-raw` (regional, Standard, uniform access, no public access, no versioning, deleted objects recoverable for 7 days): `markdown/<filing id>.md` and `manifest/<filing id>.json`, written by `fetch`, each filing once, and the company list `companies/us.jsonl` |
| Pipeline outputs | bucket `airo-pipeline-data` (same settings) |
| Pipeline identity | service account `airo-pipeline@gario-1.iam.gserviceaccount.com`: Storage Object User, Agent Platform (Vertex AI) User, Batch Job Editor, BigQuery Data Editor, BigQuery Job User, Secret Manager Secret Accessor, Artifact Registry Reader, Batch Agent Reporter, Logs Writer |
| Model | Gemini `gemini-3.8-flash` through Vertex AI, tested in Vertex AI Studio |
| Image | `us-central1-docker.pkg.dev/gario-1/airo/pipeline` (Artifact Registry repository `airo`), built from `Dockerfile` |
| Build | Cloud Build trigger `airo-main` on every push to `main` of this repository (GitHub connection `GithubAIRO`, 2nd gen): runs the tests, builds and pushes the image (`cloudbuild.yaml`), as service account `cloudbuild-airo@gario-1.iam.gserviceaccount.com` |
| Enabled APIs | Cloud Storage, Vertex AI, Batch, BigQuery, Secret Manager, Artifact Registry, Cloud Build, Compute Engine |
| Budget | budget alert on the billing account (warns, does not cap) |

Set up and pending:

- Done: project, billing, IAM for the team, buckets, service accounts, APIs, Gemini access, GitHub
  connection, build trigger; the first build succeeded (tests passed in the cloud, image pushed).
- Pending: the first `fetch` into the raw bucket; the first Cloud Batch run of the pipeline over the raw
  bucket; the BigQuery tables for labels and summaries.

The data provider's API key is not stored in the cloud (Secret Manager holds no secret): the provider
counts requests per key, so every team member runs `fetch` from their own machine with their own key, and
the filings go straight into the raw bucket. All five team members can write to both buckets through
their project roles.

The container runs `python -m airo <command>` with `AIRO_GLOSSARIES=/app/glossaries` and includes
`google-cloud-storage`. A Batch job mounts the two buckets and calls `run` (on the raw bucket's
`markdown/` and `manifest/`), `tasks`, the Gemini coder, `accept`, `adjudicate`, `aggregate` in that order.

## Design

- **A filing is in the raw bucket once.** `fetch` names a filing by the provider's filing id, reads the
  names already in the bucket before it requests anything, and creates objects only if they are absent. A
  second fetch of the same range, by the same person or another, stores nothing twice and spends API
  requests only on the listing.
- **Documents are identified by their text, not their bytes.** `doc_id` is the first 16 hex characters of
  the SHA-256 of the extracted, whitespace-normalised block text. The same text in two files (for example
  one filing stored under two names) becomes one document with two `source_files`. Because the hash is taken over the extracted blocks, a change to the block extraction
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
  under `glossaries/`: `core.json` (502 sector-independent AI terms) plus the glossary of the company's
  industry, `isic/<division>.json`, chosen from the 4-digit ISIC Rev. 5 class in the manifest (the
  classification the data provider attaches to every company; `isic_rev5.json` holds the official
  structure), including that file's `class_terms` for the exact class. Terms have a tier: `ai` (the term
  itself denotes AI) or `context` (industry lingo around which AI is discussed, such as "data center" for
  a uranium miner). This gives two kinds of mention: a passage with at least one `ai` hit is a **direct
  mention**: a candidate AI statement that goes to the classifier as a task, which confirms it (`explicit`)
  or rejects it (`none`). A passage with `context` hits only is an **implicit mention**: context around AI
  (data-centre demand, industry lingo, euphemisms), not an AI statement. It is never classified; it is
  handed on with its text in `hints.jsonl`, counted per term and glossary group in the report summary
  (`context_terms`, `context_groups`), and shown at the end of the report view. Phrases match
  as whole words with plural and hyphen/space variation; short acronyms are case-sensitive. A trie-merged
  pre-filter keeps the search at about one second per 10-K. A hit block and its neighbours form a passage
  (page furniture is skipped, a following heading ends the window); overlapping or touching windows merge,
  and a window never crosses a section boundary. Only these passages become tasks, so a report without a
  hit costs no classification. The classifier can still label a candidate `none`.
- **A second keyword list measures what the glossaries miss.** `recall.py` holds a reference list that
  was written independently of the glossaries (the 66 keyword patterns of the predecessor UK pipeline).
  `run` counts, per document, the blocks that match it but lie in no passage (`recall_check` in
  `document.json`), and `aggregate` adds the counts up in `recall_check.json`. The hits do not become
  passages; a term that turns up there is added to a glossary.
- **The classifier stage is defined by two files, not by who codes.** `tasks.jsonl` (passage plus company,
  form, fiscal year, section, heading, matched terms) and `codebook.md` go in; one label per passage comes
  back as JSONL. A coder can be a person, an agent or a batch job against a model API.
- **Every accepted label is validated.** `accept` checks each line against the schema in `taxonomy.py`,
  rejects unknown and duplicate passage ids and evidence that is not a verbatim quote from the passage
  (whitespace differences are tolerated), and reports passages without a label. Accepted labels and
  adjudicated labels carry `taxonomy_version`.
- **Several coders are reconciled by majority vote.** `adjudicate` takes, per passage and field, the value
  that more than half of the coders chose (per value for the list fields, such as `roles` and `risk_types`). A passage with a field
  without majority, or with a coder missing, is flagged `needs_review`. `agreement.json` reports, per
  field, the share of passages on which all coders agree, the share of coder pairs with identical labels,
  and the passages to review.

## Taxonomy v0.7

One label per passage. `taxonomy.py` is the single definition; `python -m airo tasks` renders it as the
full codebook, with a definition and a checklist of criteria for every value (a value applies only if all
its criteria hold) and the decision rules, to `data/codebook.md`. Since v0.4 the coder fixes the `frame`
of the AI statement before judging any role or trait; criteria marked "frame-dependent" in the codebook
(`market_driver`, `adoption`, `governance`, `externalisation`) are read in that frame. v0.5 added
`substantiveness`; v0.6 added `business_functions`, `governance_responses` and the risk type
`national_security`; v0.7 removed `implicit` from `ai_reference`: a passage either treats AI or it does
not, and context passages are not labelled at all; v0.8 made `ai_kinds` a list of eight kinds, coded only
when named.

| Field | Allowed values | Rule |
|---|---|---|
| `ai_reference` | `explicit`, `none` | exactly one, judged from the passage alone: `explicit` needs a matched AI term in its technology sense and a statement about AI; analytics, automation or algorithm wording without an AI term is `none`; with `none` the next nine fields and `evidence` stay empty |
| `frame` | `risk_factor`, `governance`, `business`, `market` | exactly one when the passage is about AI, decided from section, heading and sentence function before any role or trait; `null` if and only if `ai_reference` is `none` |
| `roles` | `market_driver`, `adoption`, `offering`, `risk`, `governance`, `incident`, `general` | one or more; `general` only alone |
| `risk_types` | `market_demand`, `strategic_competitive`, `operational_reliability`, `cybersecurity`, `third_party`, `regulatory_legal`, `workforce`, `reputational_ethical`, `information_integrity`, `environmental`, `national_security`, `other` | one or more if and only if `risk` is a role |
| `adoption_stage` | `planned`, `piloting`, `deployed`, `unclear` | exactly one if and only if `adoption` is a role |
| `business_functions` | `customer_service`, `marketing_sales`, `operations`, `finance`, `hr_workforce`, `legal_compliance`, `rd_product`, `it_cybersecurity`, `supply_chain`, `manufacturing`, `decision_analytics`, `other`, `not_stated` | one or more if and only if `adoption` is a role; the company's own use; `not_stated` only alone |
| `governance_responses` | `oversight_structure`, `policies_processes`, `technical_controls`, `third_party_controls`, `workforce_measures`, `transparency_accountability`, `other` | one or more if and only if `governance` is a role |
| `ai_kinds` | `traditional_ml`, `generative_llm`, `computer_vision`, `nlp`, `recommendation`, `agentic`, `other`, `unspecified` | one or more when the passage is about AI; a kind only when a term for it is in the passage, nothing estimated from context; `unspecified` only alone |
| `disclosure_traits` | `boilerplate`, `hedging`, `externalisation`, `vagueness`, `safe_harbour` | zero or more; `[]` when no trait applies (the statement is specific) and always when `ai_reference` is `none`; `externalisation` never in frame `market` |
| `substantiveness` | `boilerplate`, `generic`, `specific`, `detailed`, `quantified` | exactly one when the passage is about AI; five ordered levels, the highest whose criteria the AI statements meet |
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
- Input is the provider's Markdown (or HTML / inline XBRL). There is no PDF reader. A Markdown filing has no
  XBRL facts: its metadata comes from the manifest. The filer category (large accelerated filer, ...) is in
  neither the provider's data nor read from the cover page, so it is empty. A manifest field without a value
  holds a notice text, also `fiscal_year`, which is otherwise a number.
- `companies/us.jsonl` is written once and not refreshed: a ticker or exchange the provider adds later to a
  company in the list is not picked up until the file is deleted from the bucket.
- `fetch` recognises a filing by the provider's filing id. The same report under two ids (a 10-K and the ARS
  that reprints it) is stored twice; `run` merges only files whose extracted text is identical.
- `run` parallelises over the cores of one machine; distribution over several machines comes with
  the Cloud Batch job definition, which is not written yet.
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

The tests use synthetic Markdown and HTML written to a temporary directory, a fake of the provider's API
and a fake bucket; they need no network, no API key, no Google Cloud credentials and no `data/`.
pytest is configured with `pythonpath = src`, so the package itself does not have to be installed.
