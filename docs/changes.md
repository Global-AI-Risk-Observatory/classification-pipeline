# Changes against the original pipeline

Every design change is recorded here in the same form: how the original did it (with the file),
how this pipeline does it (with the file), why, what is demonstrably better, and what is not better
or still open. New changes get a new entry; nothing is deleted.

"Original" is the UK pipeline this repository started from: `AI-Risk-Observatory/pipeline/`
(fork of `84rt/AI-Risk-Observatory`, state of 2026-09-16). "New" is `src/airo/` here.

Evidence so far comes from one filing (Uranium Energy Corp, 10-K FY2026) and from coders that
are language models, not people. Every "better" below is therefore an indication, not a result.

---

## 1. Document identity and storage

**Status: the local file layout is interim.** The target is Google Cloud: filings and
per-document outputs in Cloud Storage buckets, labels and report summaries in BigQuery, runs as
Cloud Batch jobs. Nothing in this entry about directories and local files is a final design;
it exists so the pipeline can be developed and tested before the cloud project exists.

**Original.** Filings arrived as Markdown from the data provider's API or were extracted from
iXBRL (`src/ixbrl_extractor.py`, 1,064 lines) and stored in a SQLite database through SQLAlchemy
(`src/database.py`, 1,694 lines, 55 functions): tables for companies, documents, chunks, runs,
classifications. A document was identified by company and fiscal year.

**New, interim.** `src/airo/ingest.py` parses the HTML / inline XBRL file directly with lxml. A
document is identified by the SHA-256 of its normalised block text (`doc_id`).
`src/airo/runner.py` writes one directory per document under a local `--data` directory and an
append-only file index. No database.

**What carries over to the cloud design.** The text-hash identity (it is what makes duplicate
downloads collapse), the per-document unit of work, and the file formats (JSON / JSONL). What
changes: the location (bucket paths instead of directories), the index (a BigQuery table
instead of `index/files.jsonl`), and the queries (BigQuery instead of reading files).

**Why the text hash.** Five downloads of the same 10-K differed in raw bytes (a Cloudflare
e-mail token) but not in text; a text hash collapses them, a company-year key or a byte hash
would not.

**Better.** The five duplicate downloads became one document automatically.

**Not better / open.** The whole storage layer is to be rebuilt on Google Cloud once the project
exists (see `docs/research-plan.md` and the team's cloud setup). No Markdown route from the
provider's API yet. Metadata comes only from inline-XBRL `dei:` facts.

## 2. Sections

**Original.** Regular expressions for UK annual-report headings ("Principal risks", "Strategic
report", "Directors' report", ...) in `src/ixbrl_extractor.py` (`SECTION_PATTERNS`, line 448).

**New.** Form 10-K "Item N." headings (`_ITEM` in `src/airo/ingest.py`), plus bold/italic-only
short paragraphs as sub-headings. Table-of-contents rows and running sentences that start with
"Item" are excluded (fixed after the test suite found both).

**Why.** The first case study is a US 10-K; its section structure is formal and reliable.

**Better.** All 23 Items of the 10-K were found; every candidate passage carries its Item and
the nearest sub-heading, which the coders used.

**Not better / open.** UK and ESEF headings are not ported yet, so European reports currently get
no sections. Everything after the last Item (signatures, financial statements) is attributed to
that last Item.

## 3. Finding candidate passages

**Original.** One keyword list of about 70 regular expressions for all companies
(`src/utils/keywords.py`), windows of 2 paragraphs before and after each hit
(`chunk_markdown` in `src/markdown_chunker.py`, line 636), overlapping windows merged.

**New.** Glossaries (`glossaries/`): `core.json` with 500 sector-independent terms and one file
per ISIC Rev. 5 division (87 files) with industry lingo, chosen by the company's ISIC class from
the manifest; `src/airo/glossary.py` compiles them, `src/airo/retrieve.py` builds windows of 1
block on each side, skips page furniture and stops before the next heading. Each term has a
tier: `ai` (the term is AI) or `context` (lingo around which AI is discussed). A passage with
an `ai` hit is a direct mention and becomes a classification task; a passage with `context`
hits only is an implicit mention and is handed on as a hint with its text (`hints.jsonl`), not
classified.

**Why.** A uranium miner's AI story is "data center power demand" and "hyperscaler" nuclear
deals; no generic list contains that. Industry-specific lingo needs an industry key, and the
data provider supplies ISIC codes for every company. The two tiers keep the classifier's cost
bound to passages that name AI while not losing the implicit ones for a human reader.

**Better.** On the case study, 4 direct passages and 3 hints instead of 6 passages from the old
list, with the two data-centre demand passages now visible as hints and no false candidate among
the classified ones. Search time about 1 s per 10-K (a trie-merged pre-filter; the first version
took 18 s).

**Not better / open.** The glossaries were written from domain knowledge by language models and
exercised on one filing; term lists per industry are unvalidated and the agents flagged terms
for human review in each file. Context window 1 instead of 2 was chosen for cost, not measured.
English only. Seventeen phrases appear under two canonical terms (reported under the first).
Hints have no quality measure yet; how many are AI-driven is itself a research question
(`docs/research-plan.md`).

## 4. Classification architecture

**Original.** A cascade of seven classifiers (`src/classifiers/*.py`, shared
`base_classifier.py` of 870 lines): `mention_type` as a gate (adoption / risk / harm / vendor /
general / none), then `adoption_type`, `risk`, `vendor`, `harms`, an open-taxonomy risk
discovery, and three separate substantiveness classifiers. Each returned per-label confidence
scores in [0, 1] and a free-text reasoning; risk and adoption carried a signal strength 1–3 for
how directly AI was attributed. Prompts lived in `prompts/classifiers.yaml` (three versions of
that file existed side by side); calls went through the Gemini Batch API
(`src/utils/batch_api.py`).

**New.** One label per passage in one call. The label schema is the pydantic model `Label` in
`src/airo/taxonomy.py`; every coder's output is validated against it by `classify.validate`,
including the rule that each `evidence` quote is a verbatim substring of the passage.
Confidence has three levels; there is no reasoning field; there is no signal strength.

**Why.** Three to seven calls per passage do not scale to millions of reports. A single label
cannot contradict itself across classifiers. Verbatim evidence is checkable by machine; free-text
reasoning is not.

**Better.** Cost per passage is one call. Cross-field consistency is enforced by the schema
(`risk_types` if and only if `risk`, etc.), where the original only checked each classifier's
own output. Three model coders agree on every field but the disclosure traits on the case study.

**Not better / open.** The signal strength 1–3 is gone; it encoded how directly AI was blamed,
which the three-level confidence does not. The reasoning text is gone, which made audits of the
original's decisions readable. A gate classifier may reject non-AI passages with higher
precision than one combined call; not measured. The one-call design has not been run against a
model API yet (see 9).

## 5. Value definitions: criteria instead of prose and examples

**Original.** Each value was described in prose in the prompt, followed by example sentences
with target labels and confidence values, e.g. `prompts/classifiers.yaml` lines 1–49
(`mention_type`): "We are exploring AI opportunities. -> general_other_or_ambiguous ~0.7". The
schema (`src/classifiers/schemas.py`) knew the value names only.

**New.** Every value is a definition plus two or three criteria that must all hold, in one dict
per field in `src/airo/taxonomy.py` (`ROLES`, `RISK_TYPES`, ...). `_table()` renders them into
the codebook as "Criteria (all required): (1) ... (2) ... (3) ..."; the same module defines the
schema, so definition, codebook and validation have one source.

**Why.** Examples do not define a boundary; criteria do. Where the v0.2 codebook had prose only
(adoption stage, specificity), the coders disagreed. With criteria, a disagreement can be
located ("criterion (2) of vagueness is unclear per sentence vs per passage") and fixed; an
example list can only grow. People can apply a checklist; "~0.7" they cannot.

**Better.** From v0.2 to v0.3 the three coders went from disagreeing on two fields to agreeing
on all fields except the new disclosure traits (four passages; an indication only). The coders'
feedback now names criteria instead of feelings.

**Not better / open.** Criteria are stricter than examples: a borderline case that an example
would have caught drops out when one criterion is narrowly missed; recall may fall, unmeasured
without human labels. The criteria were written by me from four passages, not derived from data.
The original's signal strength expressed degree; a yes/no criterion cannot.

## 6. Taxonomy content

**Original** (`prompts/classifiers.yaml`, `src/classifiers/schemas.py`): mention types
adoption / risk / harm / vendor / general_other_or_ambiguous / none; ten risk types
(strategic_competitive, operational_technical, cybersecurity, workforce_impacts,
regulatory_compliance, information_integrity, reputational_ethical, third_party_supply_chain,
environmental_impact, national_security); adoption types non_llm / llm / agentic with signal
0–3; vendor names; substantiveness boilerplate / moderate / substantive, separately for
adoption, risk and vendor.

**New** (`src/airo/taxonomy.py`):
- `roles`: market_driver (new), adoption, offering (new), risk, governance (new), incident
  (was harm), general. `vendor` became the free-text field `entities`.
- `risk_types`: market_demand (new), strategic_competitive, operational_reliability,
  cybersecurity, third_party, regulatory_legal, workforce, reputational_ethical,
  information_integrity, environmental, other. `national_security` dropped.
- `adoption_stage` planned / piloting / deployed / unclear and `ai_kind` generative /
  non_generative / unspecified replace the adoption-type signals.
- `disclosure_traits` boilerplate / hedging / externalisation / vagueness / safe_harbour
  (multi-label, grounded in impression-management research on corporate disclosure) replace
  the three substantiveness classifiers (v0.2 had a single `specificity` in between).
- `ai_reference` explicit / implicit / none makes the "is this AI at all" decision a field.

**Why.** The case study showed the gap: for a uranium miner AI is a demand driver and the risk
is that the demand fails; the original taxonomy had no place for either and would have filed
both under "general" or "strategic". One substantiveness judgement instead of three removes
redundant calls; traits instead of a scale make the judgement a research construct (how
companies obscure) rather than a quality grade.

**Better.** Both market-side passages of the case study are coded with their actual role and
risk. The traits give a per-report activation rate (0.75 on the case study; hedging in 3 of 4
AI passages).

**Not better / open.** Continuity with the original's 474 human annotations is partly broken;
`risk_types` can still be mapped, mention types only roughly. `national_security` was dropped
on a judgement that it rarely appears as a company risk; for a policy audience (the project's
sponsor) that may be the wrong call and is easy to reverse. The traits conflict in mixed
passages (a vague sentence next to a specific one): the rule "a trait applies if any AI
statement meets its criteria" makes `vagueness` accumulate; all three coders reported it.
Decision pending.

## 7. Quality control

**Original.** A human golden set of 474 annotations for 15 UK companies
(`data/golden_set/human/annotations.jsonl`), compared against model runs by scripts
(`scripts/compare_llm_runs.py`, `run_audit_comparison.py`), with a stated target of about 90 %
agreement. Low-confidence cases flagged for review.

**New.** Several coders label the same tasks; `classify.adjudicate` takes the majority per
field, writes `agreement.json` (unanimity share per field, share of identical label pairs) and
flags passages without a majority (`needs_review`). Any coder, human or model, hands in the
same file format and goes through the same validation.

**Why.** Agreement between independent coders is measurable before any gold standard exists,
and the mechanism is the same one a human annotation campaign needs.

**Better.** The case study has an agreement figure per field after every taxonomy change, which
is how the v0.2 and v0.3 revisions were justified.

**Not better / open.** No human label exists yet in this pipeline; four model coders agreeing
shows the codebook is unambiguous for models, not that the labels are right. No Cohen's kappa
yet. The original's human golden set is not reused yet (see `docs/research-plan.md`, section 3).

## 8. Execution

**Original.** `run_pipeline.py` plus about 90 scripts in `scripts/` and `pipeline/scripts/` for
batches, repairs, migrations and exports, all against the SQLite database, run on one machine.

**New.** Four commands (`run`, `tasks`, `accept`/`adjudicate`, `aggregate`) that communicate
only through files; `run` processes files in a process pool with resume and an append-only
index (`src/airo/runner.py`, `src/airo/cli.py`).

**Why.** Scale to hundreds of thousands of reports requires independent units of work, restart
after failure and no shared mutable store.

**Better.** 1.0 s per 10-K end to end on one core; a second run skips indexed files in 0.1 s;
`--workers 2` gives byte-identical output to `--workers 1` (tested).

**Not better / open.** Interim: one machine, local directories. The target is Cloud Batch jobs
over a Cloud Storage bucket with a BigQuery index; the per-file function in `runner.py` is what
a cloud worker will call, the directory and index handling will be replaced. Two runs on the
same `--data` directory at once are not safe. A parser or glossary change does not re-process
indexed files.

## 9. Model access

**Original.** Gemini through the Batch API (`src/utils/batch_api.py`), with a note in
`pipeline/CLAUDE.md` that thinking tokens count against `max_output_tokens`.

**New.** `src/airo/coders/gemini.py`: online calls through the `google-genai` SDK on Vertex AI,
thread pool, retries, JSON mode with the pydantic schema, token and cost accounting, written for
the team's Google Cloud setup. Tested against a fake client only.

**Why.** The team decided on Google Cloud and Gemini; the coder must produce exactly the file
that `accept` validates.

**Better.** Nothing yet: the live call has not been made.

**Not better / open.** Batch mode (half price, the original's route) is not implemented. The
schema's acceptance by Vertex AI and the thinking configuration for Gemini 3 models are
unverified until the first run with credentials.

## 10. Frame before criteria (v0.4)

Here "Original" is v0.3 of this pipeline, not the UK pipeline.

**Original** (`src/airo/taxonomy.py` v0.3). The value criteria were applied independently of
where the AI statement sits and what the sentence does. The `adoption` decision rule treated a
presupposed use as adoption ("our evaluation reviews AI usage" -> `adoption`, stage `unclear`),
and the `governance` rule counted the same phrase as governance. On the case study (Uranium
Energy Corp, 10-K FY2026) all four coders therefore gave the board-oversight passage both
`adoption` and `governance`: the codebook made the double coding mandatory, so the agreement
figure confirmed a rule, not a reading.

**New** (`src/airo/taxonomy.py` v0.4, `FRAMES`, `Label.frame`). A required field `frame` with
four values, `risk_factor`, `governance`, `business`, `market`, fixed from section, heading and
sentence function before any role or trait is judged; `null` only when `ai_reference` is
`none`. The codebook gets a section "Step 1: determine the frame" before the roles, and four
criteria are marked frame-dependent: `adoption` in frame `governance` needs a clause outside
the remit that asserts the company's own use (the presupposed-use rule is gone; "AI usage"
inside a review or control remit is `governance` only); `governance` applies in any frame but
is the primary role in frame `governance`; `market_driver` is the primary role in frame
`market` and needs an explicit demand, price or supply statement elsewhere; `externalisation`
is evaluated only with the roles `adoption`, `offering`, `governance` or `risk` and never in
frame `market` (the schema rejects it there). `classify.adjudicate` votes on `frame` like the
other single-valued fields; `aggregate.summarise` counts `frames` per report.

**Why.** The double coding was a property of the rules, not of the text: a committee remit that
lists "AI usage" says that AI is overseen, not that it is used. Reading the criteria in a frame
lets the same phrase mean different things in a risk factor, a governance paragraph and a
business description, which is how a human reader takes it, and it gives disagreements a
location one step earlier ("we disagree on the frame" before "we disagree on the role").

**Better.** Nothing measured yet: the v0.3 labels under `data/labels/` have not been recoded,
so there is no agreement figure for v0.4. What can be said: the case-study passage that forced
`adoption` on every coder now has a rule that yields `governance` alone, and every
frame-dependent criterion names the frame it depends on, so a reviewer can check the step.

**Not better / open.** One more field the coders can disagree on, and a disagreement on the
frame propagates into the roles and traits; the unanimity share may fall before it rises. The
frame leans on section and heading, and section detection knows only Form 10-K "Item" headings
(entry 2), so for any other form the coder has only the sentence function to go on. The order
of tests in the frame decision rules (harm, then remit, then market, then business) is a
judgement from four passages. Whether `market_driver` in frame `risk_factor` now drops cases
that v0.3 caught (a risk factor that implies demand without stating it) is unmeasured.

---

## 11. Source: US filings as Markdown from one provider, stored once in Cloud Storage

**Original.** The UK pipeline collected annual reports of companies listed in London from
several places: PDFs and metadata from the Companies House API (`src/companies_house.py`, key
`COMPANIES_HOUSE_API_KEY`), iXBRL from filings.xbrl.org, and Markdown from the data provider's
API (`scripts/fetch_fr_dataset.py`, London Stock Exchange only, with three local cache
directories). Up to entry 10 this repository had no download at all: `run` was given HTML
files that someone had saved by hand.

**New** (`src/airo/fetch.py`, `python -m airo fetch`; `ingest.parse_markdown`). One source and
one country: filings of US companies from the FinancialReports API (financialfilings.com). No
Companies House, no UK data, no other key than the provider's.

- Only the provider's Markdown rendering of a filing is fetched, not the filing package (HTML,
  XBRL, exhibits). `ingest` reads that Markdown: paragraphs, bold lines as headings, pipe-table
  rows; the Item sections are found as before.
- The filings go to the raw bucket (`gs://airo-filings-raw/markdown/<filing id>.md`), not to a
  local directory and not into the repository. `run` reads the mounted bucket.
- A filing is stored once: the object name is the provider's filing id, the names in the
  bucket are read before anything is requested, and objects are created only if absent.
- The API key is personal and stays in each person's `.env.local`, because the provider counts
  requests per key. It is not in Secret Manager.
- Metadata costs no request per filing. Fiscal year, period and source filing id come with the
  listing (`view=full`); CIK, ticker and exchange from the provider's list of US companies,
  read once and kept in the bucket (`companies/us.jsonl`); the filing's cover page fills what
  the provider leaves empty; a field that is still empty holds a notice text.
- Which filing types are fetched is not fixed in the code: `--types` is required, `--form`
  narrows to one SEC form.

**Why.** The research plan is about US filings, and the provider has them for 22,027 US
companies in one format. Markdown is a tenth of the size of the package and needs no HTML
parser per filer. Storage in one bucket that all five team members write to makes "already
fetched" a property of the bucket, not of anyone's disk, and saves the API requests for
filings that are there. A per-filing detail request would have doubled the requests (about
160,000 more for the Form 10-K filings); the listing and the company list give the same fields
for about 220 requests in total.

**Better.** Measured on the live API on 2026-10-05, with four and five filings: a second fetch
of the same range requested no Markdown for filings already stored; the Boeing 10-K for 2024
gave the same form, period end, fiscal year and 23 Item sections from Markdown as from the
HTML package; the manifests carried CIK, ticker, exchange, fiscal year and source filing id
without a request per filing.

**Not better / open.** Nothing has been written to the real bucket yet; the Cloud Storage code
was tested against a fake bucket and, read-only, against the real one. The provider's type
"10-K" mixes SEC forms (10-K, 10-K/A, ARS, N-CSR, 20-F, 40-F, 10-KT), and the same report can
appear under two filing ids (a 10-K and the ARS that reprints it): such a pair is stored twice
unless `--form` excludes one. Markdown has no XBRL facts, so the filer category is lost. The
company list has a ticker for half of the companies and an exchange for a quarter. The notice
text sits in fields that are otherwise numbers or dates (`fiscal_year`, `period_end`), which
every consumer of the manifest has to expect. The Markdown reader has been run on six filings.

---

## 12. Every passage is classified; a recall check; fields for function and governance response (v0.6)

**Original.** The UK pipeline gated on 66 keyword patterns (`src/utils/keywords.py`) and
classified every chunk that passed the gate. It had no field for the business function of an AI
use and none for the kind of governance response, and no measure of what the gate missed.

**Before (entries 3 and 6, up to v0.5).** A passage with an `ai`-tier term was a direct mention
and was classified. A passage with `context`-tier terms only was an implicit mention: it was
written to `hints.jsonl` for a reader and not classified. Which text became a passage at all was
decided by the glossaries alone.

**New.**

- Every candidate passage is a task (`cli.cmd_tasks`, `cmd_accept`; `aggregate.summarise`,
  `render`). `hints.jsonl` is gone. The kind of mention (`direct`, `implicit`) stays on the
  passage, is written to the task, and the report summary counts both kinds and the AI passages
  that were found through context terms only (`n_ai_passages_from_implicit_mentions`).
- `src/airo/recall.py`: the 66 patterns of the UK pipeline, kept as a reference list that is
  independent of the glossaries. `run` stores per document how many blocks match it outside
  every passage (`recall_check` in `document.json`); `aggregate` writes the totals of the run to
  `recall_check.json`. The reference hits do not become passages.
- `glossaries/core.json`: `autonomous` and `multimodal` as context terms (502 terms). Both were
  in the UK list and absent here, so text that used only them was not stored as a passage.
- Taxonomy v0.6 (`src/airo/taxonomy.py`): `business_functions` (13 values, one or more if and
  only if `adoption` is a role, `not_stated` when the passage names no function),
  `governance_responses` (six groups and `other`, one or more if and only if `governance` is a
  role) and the risk type `national_security`. The two fields follow the operationalisation the
  policy team asked for; its six governance groups are taken as they are, its single controls
  (about 25) are named in the definitions and not coded one by one.

**Why.** The run `us-2025h1_V2` (7,794 filings, v0.5) left 63,801 implicit mentions without a
label. On 2026-10-13 a sample of 3,321 of them was classified with the v0.5 codebook and
`gemini-2.5-flash` (`gs://airo-pipeline-data/us-2025h1_V2/implicit_sample/`; 3,309 labelled, 12
rejected by the acceptance check):

- 2,000 passages drawn at random, proportional to ISIC division, from the 62,480 passages without
  a UK-pattern hit: 248 of 1,997 labelled passages are about AI, 12.4 % (95 % interval 11.0 to
  13.9 %); 124 `explicit`, 124 `implicit`. "data center" alone carries 100 of the 248.
- All 1,321 passages in which a UK pattern matches: 897 of 1,312 labelled passages are about AI,
  68.4 % (65.8 to 70.8 %). By pattern: `predictive_analytics` 208 of 209, `autonomous` 502 of
  615, `algorithmic` 62 of 66, `rpa` (spelled out) 56 of 58, `intelligent_automation` 36 of 41,
  `multimodal` 19 of 43, `rpa_acronym` 22 of 282.

Extrapolated, about 8,650 of the 63,801 unlabelled passages are about AI, against 25,362 among
the labelled chunks of that run: the tier decided for about a quarter of the AI passages that
they were never judged. A tier is a property of a word list; whether a passage is about AI is
the classifier's question, and it has the value `none` for the answer no.

**Decisions behind this version (2026-10-13).**

| Decision | Alternatives considered | Reason |
|---|---|---|
| Classify every passage, whatever the tier of its terms | Keep the tier as the gate and move single terms to tier `ai`; classify a sample of the implicit mentions only | The sample showed AI passages behind many different context terms ("data center", "data science", "nvidia", "compute capacity", "predictive analytics"). Moving terms one by one repeats the same gap with the next term; the classifier already has `none` for a passage that is not about AI. |
| Keep the UK keyword patterns as a reference list that measures, not as retrieval terms | Add all 66 patterns to the glossaries; ignore them | The first view, taken from the UK pipeline's own labels (96 to 100 % `none` for chunks found only through `autonomous`, `rpa_acronym`, `predictive_analytics`, `multimodal`, `algorithmic`), was to leave them out. The sample, labelled with this pipeline's codebook, gave the opposite picture for most of them. Two classifiers disagreeing is a reason to measure in every run, not to copy the list. |
| `autonomous` and `multimodal` enter the core glossary as tier `context` | Tier `ai`; not at all | They were the patterns of the UK list for which this pipeline stored no passage at all. Both have common meanings that have nothing to do with AI, so they do not prove AI on their own; as context terms they are found, and the classifier decides. The phrases of the UK pattern `algorithmic` (trading, decision, bias) were already in the core glossary; nothing was added for it. |
| `governance_responses` with the policy team's six groups | Its roughly 25 single controls as values | One label per passage cannot carry 25 values reliably, and no agreement figures exist yet even for the six groups. The single controls are named in the definitions, so a later split has the wording to start from. |
| `business_functions` with a value `not_stated` | The policy team's twelve functions only | Many adoption statements name no function ("we use AI across our operations"). Without `not_stated` a coder has to guess one, and a required field with a guessed value cannot be told from a stated one. |
| `national_security` as a risk type | Leave it under `regulatory_legal` or `other` | It is in the policy team's list and in the UK taxonomy, which labelled it on 161 chunks of the same filings, so it is rare but present. Export controls on AI chips are a different mechanism from compliance with AI rules. |
| No separate 0 to 3 scale for governance responses | Add the policy team's scale as a field | `substantiveness` already orders every AI statement in five levels, including those with the `governance` role. Two overlapping scales would have to be kept apart by annotators and would be compared with each other, not with the text. |
| `ai_kind` stays at three values | The policy team's eight kinds, several per passage | 18,083 of the 25,362 AI chunks of `us-2025h1_V2` are `unspecified`: most passages do not say which kind. The finer kinds can be derived from the matched glossary terms without a model. |
| No adoption stage `scaling` | Add it after `deployed` | A single passage rarely shows whether a use that is in operation is also being scaled; this is a judgement about the text, it has not been measured. |
| The comparison with a reference risk taxonomy is not part of the classifier | A field per reference category | It needs a crosswalk from `risk_types` to the reference categories and a comparison of shares. It can be built on any labelled run and changes no label. |
| All of this goes into one new run in a new folder beside `us-2025h1_V2` | Label the implicit mentions of `us-2025h1_V2` now and add the new fields in later passes; overwrite `us-2025h1_V2` | Every additional pass over the corpus is paid again. A run under one taxonomy version in one folder can be compared with the earlier runs; a folder that mixes versions cannot. The run starts with a test set before the whole corpus. |
| Human annotation starts after v0.6 | Annotate the v0.5 labels first | Annotators would otherwise go through the same passages a second time for the new fields. |

**Better.** A passage can no longer be about AI and stay without a label because of the tier
of its terms. A term the glossaries lack now shows up as a number in every run. The two policy
fields are labelled in the same pass as the rest, so no second pass over the corpus is needed
for them.

**Not better / open.**

- About three times as many passages go to the model (on that run 92,196 instead of 28,395),
  most of them to receive `none`. The sample cost USD 0.0006 per passage.
- The sample's labels are a model's, not people's. 124 passages of the random stratum are
  labelled `explicit` although no `ai`-tier term is in them: the classifier reads terms such as
  "predictive analytics" and "data science" as naming AI. Whether the codebook should, and
  whether such terms move to tier `ai`, is undecided.
- The UK pipeline's own labels for its chunks with these patterns say the opposite (`none` for
  96 to 100 % of the chunks whose only pattern is `autonomous`, `rpa_acronym`,
  `predictive_analytics`, `multimodal` or `algorithmic`). The two classifiers have not been
  compared on the same passages.
- The recall check counts blocks, not AI statements; most `autonomous` hits will be noise. It
  says where to look, not how much is missed.
- Found while testing v0.6 on 60 passages of the sample (20 that v0.5 had labelled with
  `adoption`, 20 with `governance`, 10 with `risk` only, 10 `none`; `gemini-2.5-flash`,
  temperature 0, 40 passages per request). The same request sent twice gave identical labels on
  all 59 passages answered both times. The v0.5 codebook on the same passages in a different
  grouping of 40 than in the stored run agreed with the stored labels on `ai_reference` for 44
  of 59 and on `roles` for 35 of 59: a label depends on which other passages are in the request.
  The v0.6 codebook against the v0.5 codebook in the same grouping agreed on `ai_reference` for
  51 of 59 and on `roles` for 47 of 59: adding fields also moved the existing ones. The 60
  passages are implicit mentions chosen for being borderline, so these shares are not those of a
  run. A comparison of one passage per request against 40 per request on about 30 % of the
  corpus on 2026-10-12 (not recorded in this repository) found almost no difference, so the
  run keeps 40 passages per request. One passage per request costs about four times as much
  (measured here: about 8,400 against about 780 input tokens per passage).
- With the v0.6 codebook 58 of these 60 labels passed the acceptance check on the first answer
  (two evidence quotes were not verbatim). In the 60 answers the classifier gave 25 business functions
  on 17 adoption passages and 11 governance responses on 7 governance passages; nobody has
  checked them against the text.
- v0.6 has not been run on a corpus. `business_functions` and `governance_responses` have no
  agreement figures; `scaling` as an adoption stage, a 0 to 3 scale for governance responses and
  eight kinds of AI from the policy team's sheet were left out (the last can be derived from the
  matched terms).

---

## 13. Explicit means treats AI; implicit means context and is not labelled (v0.7)

**Before (entry 12, v0.6, same day).** Every candidate passage went to the classifier, and
`ai_reference` had three values: `explicit` (names AI), `implicit` (AI not named, but AI-linked
infrastructure or demand is a factor) and `none`. The retrieval kind of a passage (`direct`:
an `ai`-tier term; `implicit`: `context`-tier terms only) and the label value `implicit` shared
a word and were read as the same thing.

**New.**

- `ai_reference` has two values. `explicit`: the passage treats AI, that is, a matched AI term
  is used in its technology sense and a statement is made about it for the company. `none`:
  it does not. The `explicit` criteria name what is not enough: analytics, data science,
  automation, algorithm, digital, predictive or autonomous wording without an AI term.
- Passages found through context terms only are context, not AI statements. They are not
  sent to the classifier (entry 12's change is reversed; `hints.jsonl` is back). They are
  counted per filing by term and by glossary group (`context_terms`, `context_groups`,
  `context_sections` in the report summary; the group comes from the core glossary, industry
  glossaries count as `industry`) and shown in the report view with their text.
- Everything else of v0.6 stays: `business_functions`, `governance_responses`,
  `national_security`, the recall check, `autonomous` and `multimodal` as context terms.

**Why.** The sample of 3,321 context passages (entry 12) was read again, this time passage by
passage. Of the 124 `explicit` labels in the random stratum, which has no AI term by
construction, the classifier's evidence quotes rest on "analytics" (16), "data science" (15),
"algorithm" (14), "automation" (12), "predictive" (11); several quote sentences with no
technology word at all ("If we are unable to identify, hire and retain technical resources",
"Mr. Pharis has been working in quantitative finance for over 20 years", "Quantum Computing
Inc."). The 208 of 209 `explicit` on `predictive analytics` are the same reading; the UK
pipeline's classifier labelled the same chunks `none`. The `implicit` labels sat almost
entirely on data-centre and compute terms (98 of 124 on "data center") and 180 of them on
`autonomous`, outside the value's own definition. So the model was deciding, differently from
run to run, what counts as AI, and 439 of the 563 context terms in the random stratum (1,203
of 1,997 passages: loyalty programme, truckload, EU MDR, fair lending, ...) yielded no AI
passage at all and would have been paid for in every run.

The definition now follows the rule both the research plan's codebook and the policy team's
sheet state ("code what the company discloses, not what you infer"), and the coding principle
of the MIT AI Risk Repository, which sorts risks "based on how they are presented in the
source material, without imposing additional interpretation" and files what a source does not
specify under "Other" rather than inferring it
([December 2024 update](https://airisk.mit.edu/blog/framework-updates-december-2024);
[Slattery et al. 2024](https://www.arxiv.org/pdf/2408.12622)). The repository has no
explicit/implicit axis; what it has is the decision to code the stated and not the implied,
which is what `explicit` now means here.

**Decisions.**

| Decision | Alternative considered | Reason |
|---|---|---|
| Context passages are never labelled | Label them and keep `implicit` for infrastructure demand (entry 12); label only context terms with measured yield | Whatever is labelled with the AI taxonomy becomes part of the AI dataset. A context passage is not an AI statement, so its labels would be either `none` (paid for nothing) or an inference. Counting context by term costs nothing and serves the one question that needs it (research plan 6, AI as demand driver), next to the explicit passages with role `market_driver`. |
| `explicit` is decided from the `ai`-tier term list, the classifier only rejects false positives | Let the classifier judge analytics wording case by case | Two classifiers on the same sentences gave opposite answers (predictive analytics: 100 % `none` in the UK pipeline, 99.5 % `explicit` here). A measure that depends on the model's reading drifts with the model and with the grouping of a request; a term list is the same in 2020 and 2025 and can be published. |
| `predictive analytics` stays a context term | Move it to tier `ai` because the policy team's sheet lists it as a type of AI | Whether a filing that says "predictive analytics" and not "AI" discloses AI is a definition the team has to own; the sheet is one input, not the decision. Until it is decided, the term is counted as context (euphemisms group), so the figure exists either way. |
| No `infrastructure` value | A third value for AI-driven demand without an AI term | It would re-create a labelled class of passages that do not treat AI. The demand phenomenon is visible in the context counts (compute_infrastructure group) and, where AI is named as the cause, in explicit passages with `market_driver`. |

**Better.** The AI dataset contains only passages that treat AI, and whether a passage is in
it is decided by a word list plus a false-positive check, not by what a model takes a word to
stand for. Run size and cost return to those of `us-2025h1_V2` (about 28,400 tasks on that
corpus) plus the v0.6 fields.

**Not better / open.**

- A passage that treats AI with a term the `ai` tier lacks is context and gets no label. The
  recall check (entry 12) shows such terms per run; adding one is a glossary decision, not a
  model decision.
- The 63,801 context passages of `us-2025h1_V2` are, under this definition, the context
  dataset of that run; their 3,321 sampled labels are a study of the classifier's reading, not
  data.
- Whether "predictive analytics", "recommendation systems" or "autonomous" count as AI is
  undecided; each is a one-line glossary change once decided.
- v0.7 has not been run on a corpus.

---

## 14. Kinds of AI as a list, coded only when named (v0.8)

**Original.** The UK pipeline estimated the kind of AI from the context: `adoption_signals`
with `non_llm`, `llm`, `agentic` and `ambiguous`, each scored 0 to 3 by the model.

**Before (v0.4 to v0.7).** `ai_kind`, exactly one value: `generative`, `non_generative`,
`unspecified`; `generative` won when both appeared. On `us-2025h1_V2`, 18,083 of 25,362 AI
chunks were `unspecified` (71 %), 4,425 `generative`, 2,854 `non_generative`. No value for
agents.

**New** (`src/airo/taxonomy.py`, `classify.py`, `aggregate.py`). `ai_kinds`, one or more of
`traditional_ml`, `generative_llm`, `computer_vision`, `nlp`, `recommendation`, `agentic`,
`other`, `unspecified`; `unspecified` only alone; `[]` when `ai_reference` is `none`. The rule
in the codebook: a kind is coded only when a term for it is in the passage; nothing is
estimated from the context, the industry, the product or the year. Adjudication votes per
kind, as for the other list fields.

**Why.** The team's question, put by the author of the UK pipeline on 2026-10-13: "We want to
use more AI in our customer service" does not say whether that is classical algorithms,
machine learning, LLM-based systems or agents, and these distinctions matter; so either an
ambiguous category or an estimate from context. The pipeline keeps the ambiguous category,
for the reason given in entries 12 and 13: an estimate cannot be checked against the text,
two coders estimating give two answers, and the estimate drifts with the year ("AI" read as
generative in 2025, not in 2020) while the filings do not. The 71 % `unspecified` is itself a
finding about disclosure. What was missing was the granularity: one value per passage, and no
`agentic`. The list is the one the policy team's operationalisation sheet uses for "What type
of AI?", which also allows several labels per disclosure; the sheet's "Predictive analytics"
is not a kind here because its term is not an AI term (entry 13), so a passage that names only
it is not in the dataset.

**Better.** A passage that names an LLM-based agent for customer service is `generative_llm`
and `agentic`, not `generative`. The share of `unspecified` can be reported per year and sector
as the measure of how much companies say about the AI they mean.

**Not better / open.**

- v0.8 has not been run on a corpus; the 60-passage and 40-filing tests of the same day were
  made with v0.6 and v0.7.
- `traditional_ml` and `nlp` overlap in wording (a "language model" that is not large; "text
  analytics"); the criteria give `nlp` only to a named language-understanding technique and send
  everything else that learns to `traditional_ml`. Whether coders hold that line is untested.
- An `autonomous vehicle` is not `agentic` by the criteria; if the team wants autonomy as a
  kind, it is a one-line change and a glossary decision in one.
- Amended the same day after the 40-filing test of v0.9: `unspecified` given next to a named
  kind was refused by the schema, asked again up to twice, and lost 2 of 127 labels. Once a
  kind is named the AI is specified, so acceptance now drops `unspecified` (and `not_stated` in
  `business_functions`) instead of refusing the label. The codebook still says "only alone".

---

## 15. `mit_subdomains`: the shared key to the MIT AI Risk Repository (v0.9)

**Original.** The UK pipeline's risk types were its own ten categories; no link to an external
taxonomy.

**Before (v0.4 to v0.8).** `risk_types`, twelve firm-centric values (what the harm is for the
company). Nothing to join to the MIT Risk Repository, the Incident Tracker, the Delphi study
or the Governance Map, which share one domain taxonomy.

**New** (`src/airo/taxonomy.py`, `classify.py`, `aggregate.py`). `mit_subdomains`: one or more
of the 24 subdomains of the Repository's Domain Taxonomy, by name (`unfair_discrimination_misrepresentation`
to `multi_agent_risks`; `MIT_SUBDOMAIN_NUMBERS` maps each to the Repository's number for joins), plus the
residual `other`; given if and only if `risk` or `incident` is among the roles, coded from the
harm the passage states, next to `risk_types` and independently of it. Names and descriptions
are those of Table 2 in Slattery et al. (arXiv 2408.12622, v3 of 2026-05-05) and of
airisk.mit.edu/risks, read on 2026-10-13; both give the same 7 domains and 24 subdomains,
including `7.5 AI welfare and rights` and `7.6 Multi-agent risks`. The criteria are this
pipeline's (what the passage must state), with the second criterion the same for every
value: the harm is stated as a risk to the company or as an event that occurred, with AI as
its cause or object. `RISK_TYPE_SUBDOMAINS` records where each firm-centric risk type usually
lands; the codebook shows it as "typical, not binding", and it is the basis of a post-hoc
approximation on labels that lack the field. It is this pipeline's reading, not a mapping
published by MIT. Adjudication votes per subdomain; aggregation counts them per report.

**Why.** Every linkage in the research plan runs through this key: themes via subdomains (A1),
the residual (A3), the gap between implied and disclosed risks (D1), severity weights (D2),
and the policy team's "alignment with a reference taxonomy". The team briefing of 2026-10-08
listed the field as the first taxonomy step; v0.5 added `substantiveness` instead. Coding it in
the same pass as `roles` and `risk_types` keeps the three in one reading of the passage (entry
12 measured how adding fields moves existing ones) and avoids a second pass over the roughly
45 % of AI passages that carry the `risk` role.

**Better.** A disclosed risk can be joined to the Repository's 1,700 risks, to incidents per
subdomain and to the Delphi severity per subdomain without a crosswalk from firm-centric types.
What the taxonomy lacks is visible as `other` and can be read.

**Not better / open.**

- The Repository assigns a risk to its single most appropriate subdomain; this field allows
  several per passage. Counts per subdomain are therefore not directly comparable with the
  Repository's; shares of passages per subdomain are.
- MIT's subdomains describe societal hazards; a 10-K states risks to the company. The second
  criterion bridges the two, and `other` catches what does not bridge (lost sales, lost
  competitiveness, compliance cost as such). How large `other` is, and what it holds, is
  unknown until a run.
- v0.9 has not been run on a corpus. The codebook grew by 25 values; its length is now about
  48,000 characters (v0.5: 24,000).

---

## 16. Export: the run's dataset layout as a stage of the pipeline

**Original.** The UK pipeline exported from its SQLite database with scripts outside the
pipeline's stages.

**Before.** The runs `us-2025h1` and `us-2025h1_V2` in the bucket share one layout
(`chunks.jsonl`, `documents_manifest.json`, `results/classified_chunks.jsonl`,
`results/filing_metrics.jsonl`, `results/us-filing-metrics.json`, a README). The job
definition of `us-2025h1_V2` calls `airo export` for it; no such command existed on `main`, so
the layout was produced outside the repository and could not be reproduced from it.

**New** (`src/airo/export.py`, `python -m airo --data <dir> export <out> --run-id X`).
A fifth stage that writes the layout from the working directory: one row per classified
passage with its text (`chunks.jsonl`), the context passages in the same shape
(`context_passages.jsonl`, named for what they are since v0.7; `us-2025h1_V2` had them as
`implicit_mention_ai.jsonl`), one manifest row and one metrics row per filing (a text carried
by two filings, a 10-K and its ARS reprint, gives two rows with the same `text_id` and the same
values), every label field per labelled passage, shares per filing month in the shape the
dashboard reads, the codebook, the adjudication and summary files, the coder's files, the
per-document files and report views as tarballs, and a README generated from the counts. The
filing metrics carry the v0.6 to v0.9 fields (`mit_subdomains`, `business_functions`,
`governance_responses`, `ai_kinds`, the trait activation rate) next to the booleans of the
earlier runs, so that the three runs can be compared column by column.

**Why.** Three runs on the same 7,794 filings are to be compared; that needs the same files
with the same meaning, produced by code that is in the repository.

**Better.** The layout is reproducible from a working directory with one command, and tested.

**Not better / open.**

- `export` writes to a directory; in a Batch job that is the mounted bucket folder. It does
  not write to `gs://` itself.
- The README it writes is generated; the hand-written descriptions of the earlier runs
  (`docs/us-2025h1-dataset.md`, `docs/us-2025h1_V2-dataset.md`) say more. A run's description
  still needs a person.
- Not yet run on a corpus.

