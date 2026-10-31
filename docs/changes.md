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
- Amended the same day after the 40-filing test: the model labelled every `strategic_competitive`
  passage 6.4 and every `regulatory_legal` passage 6.5, reading the value names
  `competitive_dynamics` and `governance_failure` as the firm's competition and its regulatory
  exposure. MIT's 6.4 is an AI race that releases unsafe systems, 6.5 is regulation lagging
  behind AI. The values are now named `ai_race_unsafe_deployment` and
  `regulation_lagging_behind_ai`. A second test run with the new names changed nothing: every
  `strategic_competitive` passage still got 6.4 and every `regulatory_legal` passage 6.5, because
  the "typical" line of the codebook pointed there. Both entries are now out of
  `RISK_TYPE_SUBDOMAINS` (`strategic_competitive` -> `other`; `regulatory_legal` ->
  `compromise_of_privacy`, `devaluation_of_human_effort`, `other`), and each of the two values has
  a criterion that names the firm-centric reading as not this harm. Numbers and definitions are
  unchanged. A third test run then gave 6.4 to one passage instead of 17, and
  6.5 to 14 instead of 17; the 14 state an uncertain or evolving legal and regulatory
  environment for AI. Decision (2026-10-13): that is 6.5, regulation not keeping pace, not
  `other`; the criterion stays as it is. Compliance obligations and compliance cost as such
  remain excluded.

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

---

## 17. Re-asks deferred: decide on them by their number, not one by one

**Before.** A label the acceptance check rejects (most often an evidence quote that is not
verbatim) was asked again at once, on its own, with the rejected answer and the reason, up to
twice; a task missing from a batch answer was asked on its own from the start. Each such
request carries the whole codebook (about 13,000 tokens at v0.9). On the 400-filing subset of
`us-2025h1_V3`, 181 of 1,504 tasks (12 %) were asked again, and those requests made up an
estimated 2.4 of the run's 6.5 million input tokens: the re-asks of one task in eight cost a
third of the run.

**New** (`src/airo/coders/gemini.py`). `--defer-repairs`: the coder makes no single request
at all. A rejected or missing label gets a result marked `deferred`, with the rejected answer
and the reason, and `write_labels` puts them in `<out>.deferred.jsonl`; `run.json` counts
them as `deferred`, apart from `failed`. `--repairs-from <that file>` then runs exactly those
re-asks (one request per task, with the previous answer and the reason when there was one)
and writes their labels to its own `--out`, to be concatenated with the first file for
`accept`. Without the flag the coder behaves as before.

**Why.** The decision whether 12 % of the passages are worth a third of the cost is one to take
with the number in hand, not one the coder takes for every passage as it goes. Decided on
2026-10-14 after the cost of the subset was compared with that of `us-2025h1_V2`
(USD 0.0021 against 0.0012 per task).

**Amended 2026-10-14, after pass 1 of `us-2025h1_V3`.** 26,884 tasks, 23,791 labelled, 3,093
deferred (11.5 %), USD 28.21. The deferred by reason: 1,807 labels with more than three evidence
quotes (4 to 35, none empty, all `explicit`); 598 quotes not verbatim; 482 a field given without
its role or missing; 206 missing from the batch answer. Two decisions:
- A label with more than three quotes is complete; only its list is too long. Acceptance now
  keeps the first three instead of refusing (`taxonomy.py`), like `unspecified` next to a named
  kind (entry 14). The 1,807 are accepted from their stored answers without a model call.
- `--repairs-from` no longer sends one request per passage with the whole codebook. It asks the
  deferred passages again as a batch pass, 40 per request in a new grouping, without the previous
  answer; what is rejected again is deferred again. A single request costs about forty times a
  batch share, and most rejections (a field without its role, a label missing from the answer)
  do not repeat in a new grouping. The single re-ask with the rejected answer remains available
  without `--defer-repairs`, as before.

**Not better / open.** The deferred passages have no label until the repairs run; a dataset
exported in between is complete in chunks and incomplete in labels, which `chunks_without_label`
in the filing metrics shows. Quotes that the model cannot reproduce verbatim fail in every
grouping; those passages stay without a label.

---

## 18. `frame` removed; its conditions sit on the roles (v0.10)

**Status: adopted as taxonomy v0.10 on 2026-10-31, tested on the 290-passage human-validation
subset of `us-2025h1_V3`, not yet run on a corpus.** The test rounds that led to it are documented
at the end of this entry; two other candidate changes tested in the same rounds and not adopted are
in entry 19.

**Before (v0.4 to v0.9, entry 10).** A required field `frame` (`risk_factor`, `governance`,
`business`, `market`), fixed from section, heading and sentence function before any role or trait
was judged, and four criteria read in that frame: `adoption` in frame `governance` needed a clause
outside the remit; `governance` was the primary role in its frame; `market_driver` was the primary
role in frame `market` and needed an explicit demand statement elsewhere; `externalisation` was
never set in frame `market`. On `us-2025h1_V3` the raters agreed with each other on `frame` at
kappa 0.72 and with the model at 0.68 (`analysis/human_validation/results/us-2025h1_V3/agreement.md`).

**New** (`src/airo/taxonomy.py`, `classify.py`, `aggregate.py`, `export.py`; team decision of
2026-10-31, J. Pilcher and D. Kozachek). The field is gone from the schema, the codebook, the
adjudication, the report summary and the export. The order of coding is `ai_reference`, `roles`,
then the role-dependent fields (`risk_types`, `mit_subdomains`, `adoption_stage`,
`business_functions`, `governance_responses`). What the frame did for the roles is now in the role
criteria and decision rules:

- `market_driver` needs an explicit demand, price, supply or investment statement in the passage;
  a risk-factor sentence that only implies demand does not qualify.
- `adoption` needs the company's use or intention asserted in a clause outside any oversight,
  review or control remit; "our evaluation reviews AI usage" is `governance` only.
- `governance` is unchanged in its criteria; in a passage that describes an oversight remit, other
  roles are added only for clauses outside the remit that meet their own criteria.
- `externalisation` applies only with a role that puts the AI in the company's own hands or risks
  (`adoption`, `offering`, `governance`, `risk`, `incident`); the schema enforces this in place of
  the old frame rule.

The codebook asks the coder to judge each role from the function of the sentence the AI statement
stands in (does it state a harm, describe an oversight remit, describe the company's own business,
or describe a market?), with section and heading as context: the frame decision without a field
for it. Everything else (`substantiveness` with five levels, one call per 40 passages, the Gemini
coder) is as in v0.9.

**Why.** The frame was an intermediate step whose only consumers were the role criteria. A field
that is not reported, with its own disagreement (kappa 0.72 among raters), costs rating time and
gives a disagreement a place to start before the roles. The subset test below shows the roles
agree better with the raters without it.

**Better.** On the 290 passages of the V3 validation sample, labelled with the v0.10 codebook as
it is in the repository (round 3 below), agreement with the seven raters, Cohen's kappa:

| Field | V3 model, v0.9 | v0.10 (round 3) |
|---|---|---|
| ai_reference | 0.75 | 0.79 |
| roles (exact set) | 0.50 | 0.55 |
| roles:risk | 0.75 | 0.76 |
| roles:adoption | 0.55 | 0.67 |
| roles:offering | 0.44 | 0.50 |
| roles:governance | 0.55 | 0.57 |
| roles:market_driver | 0.49 | 0.48 |
| risk_types (exact set) | 0.52 | 0.55 |
| mit_subdomains (exact set) | 0.34 | 0.31 |
| adoption_stage | 0.43 | 0.45 |
| business_functions (exact set) | 0.30 | 0.35 |
| governance_responses (exact set) | 0.34 | 0.42 |
| substantiveness (five levels) | 0.30 | 0.31 |
| disclosure_traits (exact set) | 0.21 | 0.20 |

The roles as a set move from 0.50 to 0.55, carried by `adoption` (0.55 to 0.67) and `offering`;
the dependent fields `business_functions` and `governance_responses` follow. `substantiveness`,
the traits, `risk` and `market_driver` are where they were. One field fewer for raters and coders.

**Not better / open.** `mit_subdomains` is 0.03 lower, within what 290 passages can resolve, as
are all differences below about 0.05 here. The v0.4 argument for the frame was that it gives a
disagreement a location one step earlier ("we disagree on the frame" before "we disagree on the
role"); that location is gone, and a disagreement on `adoption` against `governance` has to be
read from the role criteria alone. The V3 human-validation sheets carry `frame`; the collection
code keeps reading it (`FRAMES_V09` in `analysis/human_validation/human_validation.py`). Labels of
v0.9 and earlier have the field, v0.10 labels do not; a comparison across versions drops it. Not
run on a corpus; the cloud configuration still names v0.9's model settings.

### The subset test (2026-10-31)

**Setup.** The 290 passages of the V3 human validation
(`gs://airo-pipeline-data/us-2025h1_V3/human_validation/sample.jsonl`; 7 raters, 348 ratings,
each passage rated by one or two raters, under taxonomy v0.9) were rebuilt as tasks by
`analysis/v010_subset/subset_test.py tasks` from the run's `chunks.jsonl` and
`documents_manifest.json` (one difference from the live run's tasks: the matched terms are shown
as one list under `ai`, since the exported chunk rows do not keep the `ai` / `context` split).
Each variant labelled the same tasks; `subset_test.py compare` scores every label file against
the raters with Cohen's kappa per field (list fields as exact set and per value), next to the V3
model's own labels of the same passages (`results/labels_final.jsonl`), whose figures reproduce
the published validation. 40 passages per request throughout. Tasks, codebooks, labels, run files,
logs and agreement tables of every round are in `gs://version10test/` (`round1_with_frame/`,
`round2_no_frame/`, `round3_v010_final/`); the code of the two designs that were not adopted is
kept in the repository under `analysis/v010_subset/not_adopted/`.

**Three candidate changes, three rounds.** Three changes to v0.9 were on the table: removing
`frame`, splitting the label into a roles call and a details call, and counting substantiveness
instead of rating it (entry 19 for the last two). Round 1 kept `frame` and tested the other two,
so that round 2, which removed `frame` with everything else held constant, would show the effect
of the field on its own: an ablation of the frame rather than one run with all three changes,
whose result could not have been attributed to any of them. Round 3 ran the codebook as adopted.

| Round | `frame` | substantiveness | calls | models |
|---|---|---|---|---|
| 1 | kept | ten particulars, three derived levels | two calls and, for comparison, one call | roles: `gemini-3.5-flash`, thinking at the model's default, endpoint `global` (the model is listed for `us-central1` but answers 404 there); details and one call: `gemini-2.5-flash`, thinking off, `us-central1` |
| 2 | removed | as round 1 | as round 1 | as round 1; the details call deferred its re-asks and ran them as one batch pass |
| 3 | removed | five levels as in v0.9 | one call | `gemini-2.5-flash`, thinking off, `us-central1` (as in V3) |

**Results, Cohen's kappa against the raters.** Rounds 1 and 2 had three-level substantiveness, so
the raters' five levels and the V3 model's were mapped to three for those rounds (`boilerplate`,
`generic` to `generic`; `specific` to `company_specific`; `detailed`, `quantified` to `detailed`);
the V3 figure for `substantiveness` is therefore 0.35 in those columns and 0.30 on five levels
in round 3 and in the published validation.

| Field | V3, v0.9 | R1 two calls | R1 one call | R2 two calls | R2 one call | R3 (v0.10) |
|---|---|---|---|---|---|---|
| ai_reference | 0.75 | 0.86 | 0.76 | 0.89 | 0.84 | 0.79 |
| frame | 0.68 | 0.72 | 0.69 | – | – | – |
| roles (exact set) | 0.50 | 0.52 | 0.52 | 0.56 | 0.56 | 0.55 |
| roles:risk | 0.75 | 0.77 | 0.77 | 0.76 | 0.75 | 0.76 |
| roles:adoption | 0.55 | 0.54 | 0.57 | 0.59 | 0.64 | 0.67 |
| roles:offering | 0.44 | 0.45 | – | 0.48 | 0.52 | 0.50 |
| roles:governance | 0.55 | 0.52 | 0.53 | 0.55 | 0.60 | 0.57 |
| roles:market_driver | 0.49 | 0.55 | 0.48 | 0.65 | 0.49 | 0.48 |
| risk_types (exact set) | 0.52 | 0.56 | 0.54 | 0.53 | 0.54 | 0.55 |
| mit_subdomains (exact set) | 0.34 | 0.38 | 0.34 | 0.35 | 0.36 | 0.31 |
| adoption_stage | 0.43 | 0.42 | 0.38 | 0.47 | 0.47 | 0.45 |
| business_functions (exact set) | 0.30 | 0.32 | 0.31 | 0.36 | 0.36 | 0.35 |
| governance_responses (exact set) | 0.34 | 0.36 | 0.38 | 0.44 | 0.43 | 0.42 |
| substantiveness | 0.35 / 0.30 | 0.22 | 0.22 | 0.21 | 0.23 | 0.31 |
| disclosure_traits (exact set) | 0.21 | 0.15 | 0.24 | 0.13 | 0.21 | 0.20 |

Labelled: 290 (V3); 288 in each round-1 variant (two evidence quotes not verbatim); 290 in each
round-2 variant; 289 in round 3 (one quote not verbatim after two re-asks). `roles:offering` was not
recorded for the round-1 one-call variant.

Tokens: round 1, roles call 143,121 input / 28,024 output / 83,874 thinking (290 passages), details
call 546,521 / 54,526 (239 passages, of which 31 single re-asks with the whole codebook made up most
of the input), one call 308,421 / 69,371; round 2, roles call 137,634 / 33,882 / 75,177 thinking,
details call 171,906 + 12,726 / 51,309 + 1,109 (242 passages asked, 48 labelled from their `none`
roles label without a request, 4 re-asked in one batch pass), one call 235,040 / 64,129; round 3,
one call 250,062 / 61,903, 60 seconds wall time.

**Reading.** Removing `frame` is what moves the roles: from 0.50 (V3) and 0.52 (round 1, both
variants) to 0.55 or 0.56 in every frame-free variant, with `adoption`, `offering` and
`governance` up and `risk` unchanged, and the dependent fields `business_functions` and
`governance_responses` up with them. The effect is the same whether the roles are decided by a
stronger model in a call of their own or by `gemini-2.5-flash` in one call, which is what round 2
was set up to tell apart. The gains in `market_driver` (0.65) and `ai_reference` (0.89) belong to
the stronger roles model, not to the field; with one call they stay at V3's level.

---

## 19. Tested and not adopted: two calls, and substantiveness as a count (v0.10 candidates)

**Status: implemented, run in rounds 1 and 2 of the subset test of entry 18 on 2026-10-31, and
taken out of the code again on the same day.** This entry records both designs and their results so
the decision can be checked and either design picked up again. The implementation is kept in
`analysis/v010_subset/not_adopted/two_calls_and_count_substantiveness.patch` (against the v0.9 code)
with the test script of those rounds, `subset_test_rounds_1_2.py`, beside it.

### Two calls, roles first

**Design.** `RolesLabel` (`ai_reference`, `roles`, evidence, confidence, note) was the answer of a
first call with a codebook of about 7,700 characters (11,000 with `frame`); `DetailsLabel` (every
role-dependent field, `ai_kinds`, the traits, the substantiveness particulars, `entities`) the
answer of a second call with the rest of the codebook (about 45,000 characters, the MIT table being
most of it), for the passages the first call found to be about AI, with `ai_reference` and `roles`
shown in each task as given ("do not judge again, do not return"). A `none` passage got its label
without a request. `merge` joined the two answers (the details could not override the roles; quotes
of both calls, the lower confidence, both notes) and the result was validated as one `Label`, so
the cross-field rules and `airo accept` were unchanged. `--stage roles|details|single` and
`--roles-from` in the Gemini coder; `airo tasks` wrote one codebook per call.

**Why it was considered.** Roles gate every dependent field and are where the raters disagree
(human-human kappa 0.48 on `us-2025h1_V3`). In one call a disagreement on roles cannot be separated
from its consequences, every change to the roles criteria costs a run over the whole label, and the
first call could go to a stronger model with reasoning while the second goes to a cheaper one
(discussion of 2026-10-31, J. Pilcher and D. Kozachek).

**Result.** Entry 18, table of rounds 1 and 2. Two calls against one call on the same codebook and
passages, both without `frame` (round 2): roles as a set 0.56 in both; two calls ahead on
`ai_reference` (0.89 against 0.84) and `market_driver` (0.65 against 0.49), one call ahead on
`adoption` (0.64 against 0.59), `offering` (0.52 against 0.48), `governance` (0.60 against 0.55)
and the disclosure traits (0.21 against 0.13); the other eight fields within 0.02 of each other.
The two-call run cost the roles call on top (137,634 input and 75,177 thinking tokens on the
stronger model) for the same roles agreement. With 290 passages, differences of 0.05 are not
resolvable; `market_driver` and the traits are the only ones that stand out, one each way.

**Why not adopted.** The split was meant to buy roles agreement; it did not, and the one-call design
with `gemini-2.5-flash` is as good on the roles at lower cost. Its remaining advantages (iterating
the roles codebook alone, a stronger model for the roles) have no measured value yet. The roles
error now propagating into a separate call that cannot correct it, and the details codebook still
carrying the whole MIT table for the cheaper model, were the open points in any case.

**To pick it up again.** The patch above applies the whole design; the `single` stage was kept in
it so both can be compared on the same codebook. What would justify it is a measured gain on the
roles from a model that one call cannot use, or a roles codebook that changes often enough that
re-running the whole label is the cost that matters.

### Substantiveness as a count of particulars

**Design.** Instead of rating one of five levels, the coder ticked which of ten particulars the AI
statement gives, each backed by the passage: group S, what singles the statement out as this
company's (`named_system`, `named_function`, `named_counterparty`, `mechanism`, `figure`), and group
D, what the company does or has seen (`own_measure`, `responsibility`, `time_reference`,
`realised_outcome`, `scope`). On acceptance the pipeline derived `substantiveness_score` (the number
of ticks, 0 to 10) and `substantiveness` with three levels: `generic` (no tick), `company_specific`
(ticks in one group only), `detailed` (ticks in both). A level or score given by the coder was
checked against the ticks and rejected if it contradicted them; adjudication voted per particular;
export and aggregation carried the score (mean and maximum per filing) next to the level. The three
levels were the field for the policy team's three categories; the score was to keep the differences
the three categories hide.

**Why it was considered.** A rating on an ordinal scale has no criterion a second coder can check,
and the human-human kappa of 0.36 on five levels says people do not apply them the same way either.
Hope, Hu and Lu (2016, Review of Accounting Studies 21: 1005-1045) measure the specificity of
risk-factor disclosure as a count of named entities (Stanford NER: persons, locations,
organisations, percentages, money, times, dates) per word and validate the count against student
ratings on a five-point scale (correlation 0.51); the measure itself is a count, not a rating, and
the paper has no three categories. Counting defined particulars makes every disagreement a
disagreement about one particular, gives an ordinal score, and lets the three categories be defined
by the kind of particulars present rather than by cut points chosen after seeing the distribution.
A free 1-to-10 rating by the model was considered and set aside for the same reason as the five
levels: nothing in it can be checked against the text. The "Kraft" source named in the discussion
was not identified.

**Result.** Against the raters' levels mapped to three, kappa 0.22 (round 1) and 0.21 to 0.23
(round 2) against 0.35 for the V3 model's five levels mapped the same way; the same in the two-call
and the one-call variant, so it is the criteria and not the call design. The cross-tabulation of
round 1 (two calls; passages about AI on both sides; rows the rater's v0.9 level, columns the derived
level): `boilerplate` 50 ratings, of which `company_specific` 38, `generic` 7, `detailed` 5;
`generic` 126: `company_specific` 103, `detailed` 13, `generic` 10; `specific` 58:
`company_specific` 40, `detailed` 16, `generic` 2; `detailed` 29: `company_specific` 19, `detailed`
10; `quantified` 6: `detailed` 4, `company_specific` 2. Where a rater said `boilerplate` or `generic`
(176 ratings), the ticks were `mechanism` 101, `named_function` 45, `named_counterparty` 14,
`own_measure` 12, `time_reference` 10, `responsibility` 8, the four others 11 together. Read against
the passages, `mechanism` was ticked for generic causal chains ("as we increase the use of AI tools,
the risk of unauthorized access may increase") although its criterion asks for a step particular to
this company, and `named_function` for "our operations", "our platforms", "our business". The mean
score did rise with the rater's level (1.06, 1.17, 1.71, 1.97, 2.67 from `boilerplate` to
`quantified`), so the count orders the passages the way the raters do, with the scale compressed:
the model's distribution was 176 `company_specific`, 45 `detailed`, 16 `generic`, scores 0 to 4,
and in round 2 170 / 60 / 12 (two calls) and 161 / 43 / 39 (one call). Part of the gap is
definitional: v0.9's `generic` was "names an area, nothing specific to the company", so a rater's
`generic` for "AI in customer service" maps to `generic`, while the count ticks `named_function` for
the same words.

**Why not adopted.** As written, the count agrees with the raters worse than the rated levels, and
its three derived levels put 59 to 61 % of the passages in the middle category, the outcome it was
meant to avoid. Two criteria account for most of it and could be tightened (`mechanism` with its
exclusions written out; `named_function` narrowed or moved out of group S), but that is a new
design to be tested, not a correction of this one, and the five levels of v0.9 were at hand with
the better figure. The raters' five levels also remain comparable with v0.9 and earlier runs
without a mapping.

**To pick it up again.** The patch above carries the particulars, the derivation, the validator,
the adjudication, the export columns and the tests; `SUBSTANTIVENESS_V09_TO_V010` in the round-2
test script maps the raters' levels for the comparison. Before any re-run: tighten `mechanism` and
`named_function`, decide whether a named function alone should make a passage `company_specific`,
and build rater sheets with columns for the particulars, since a count can only be validated
against raters who tick the same particulars.

---

## 20. Substantiveness: three levels against five, with and without anchor examples (tested; five kept)

**Status: tested on the 290-passage subset on 2026-10-31 (round 4 of the v0.10 subset test, entry 18);
v0.10 keeps the five levels. Nothing in the code changed.**

**Question.** The policy team asked for three substantiveness categories (generic, company-specific,
detailed). Entry 19 records that deriving them from a count of particulars agreed worse with the
raters than the five rated levels. Two questions remained: whether coding three levels directly does
better than coding five, and whether anchor examples in the codebook improve either. Hope, Hu and Lu
(2016) was to supply the examples; the paper has no example passages that could be found (the copies
at core.ac.uk and SSRN are blocked to automated download; the published text is paywalled), so the
anchors come from the test set itself.

**Setup** (`analysis/v010_subset/substantiveness_3_vs_5.py`). Three variants of the v0.10 codebook
that differ only in the substantiveness section: `five_examples` (the five levels, plus one anchor
passage per level), `three_examples` (three levels written in the taxonomy's definition-and-criteria
form with the content of the five levels joined two by two: `generic` = boilerplate and generic,
`company_specific` = specific, `detailed` = detailed and quantified; plus the same anchors with their
three-level value), `three_plain` (three levels, no examples). Round 3 is the reference for five
levels without examples. The anchors are five passages of the test set on which the raters agreed
(both raters where there were two): an audit-committee remit that lists AI (`boilerplate`), a
sentence on regulators considering AI rules (`generic`), a named investee whose product checks
documents with AI (`specific`), a bank's named AI fraud-detection tool next to its cyber controls
(`detailed`), a named joint venture with dates and ownership shares (`quantified`). They are left out
of the scoring of every variant, including the references, so no variant is scored on its own
examples. The three-level variants are validated and requested with a three-level schema that the
script substitutes in-process; `gemini-2.5-flash`, thinking off, 40 passages per request, as in
round 3. Files in `gs://version10test/round4_substantiveness_3_vs_5/`.

**Result.** 339 human ratings on 285 passages. Cohen's kappa, human against model, share of identical
ratings in brackets:

| Variant | on five levels | mapped to three |
|---|---|---|
| V3 model, v0.9 (five, no examples) | 0.29 (0.45) | 0.35 (0.53) |
| five, no examples (round 3) | 0.31 (0.47) | 0.37 (0.54) |
| five, with examples | 0.34 (0.50) | 0.38 (0.57) |
| three, no examples | – | 0.24 (0.40) |
| three, with examples | – | 0.32 (0.49) |

"Mapped to three" maps the raters' and the model's five levels with the same rule the three-level
codebook was written from. The other fields did not move (roles as a set 0.54 to 0.57, `ai_reference`
0.79 to 0.84 across the four v0.10 variants). Distributions on the passages about AI: five with
examples 113 `generic`, 46 `specific`, 78 `detailed`, 2 `boilerplate`; three without examples 42 /
123 / 69 (`generic` / `company_specific` / `detailed`); three with examples 68 / 101 / 68; the raters
50 `boilerplate`, 125 `generic`, 59 `specific`, 28 `detailed`, 5 `quantified`. Labelled: 287, 288 and
287 of 290 (evidence quotes not verbatim). Tokens: 315,352 / 63,516, 266,227 / 63,246 and 297,236 /
61,802 input / output.

**Reading.**

- Five levels agree better with the raters than three, with or without examples, and even when the
  five are mapped to three afterwards: coding three directly gives 0.24 (0.32 with examples), coding
  five and mapping gives 0.37 (0.38 with examples). Three coded levels put 53 % of the passages about
  AI in the middle category without examples and 43 % with them; five coded levels, mapped, put 34 %
  (no examples) and 19 % (with examples) there; the raters put 22 % there.
- Examples help in both designs, and most where the levels are coarsest: three levels gain 0.08, five
  levels gain 0.03 on five levels and 0.01 after mapping. With examples the five-level model moves
  passages from `specific` to `generic` and `detailed`, towards the raters' distribution.
- The gain from examples on five levels (0.31 to 0.34) is within what 285 passages resolve; the loss
  from three levels (0.37 to 0.24) is not.

**Decision.** Five levels stay. The three categories, where needed, are a mapping of the five at
reporting time (boilerplate and generic to generic; specific to company-specific; detailed and
quantified to detailed), which keeps the information and gives the better agreement. Anchor examples
are worth adding to the codebook; before that, they have to come from outside the validation sample,
so that the sample stays usable for scoring, and one per level is a minimum (the two coarsest levels
showed the largest effect). Not done in this entry.

**Not better / open.** The anchors were taken from the test set and excluded from the scoring, so
the examples test is on 285 passages instead of 290 and the anchors are not independent of the
raters. Five anchors are one codebook; another five could give other figures. The three-level
definitions were written for this test and not iterated; a definition tuned on data could close part
of the gap, as could tuned particulars in entry 19. The raters' human-human kappa on five levels was
0.36 (`us-2025h1_V3`), so 0.34 against the raters is close to what the raters give each other.

---

## 21. Examples in the substantiveness section: the source's sentences, not corpus anchors (v0.10)

**Status: adopted on 2026-10-31 after round 5 of the subset test (entry 18); `src/airo/taxonomy.py`,
`SUBSTANTIVENESS_SOURCE_ILLUSTRATION`.**

**Before.** The substantiveness section of the codebook had the five levels with definition and
criteria and no examples (through round 3). Round 4 (entry 20) showed that one anchor passage per
level from the corpus raised agreement with the raters (0.31 to 0.34 on five levels) and that the
scale's source, Hope, Hu and Lu (2016), had not been drawn on for examples.

**Question.** Which examples serve the coder in this corpus: the source's own illustration of its
specificity scale, anchor passages from the filings rated by the project's coders, or both?

**Setup.** Hope, Hu and Lu (2016), Appendix B, illustrate their five-point rating for the students of
their validity test with five constructed sentences on one firm, from "The firm's main business is
facing fierce competition globally from other firms" (1) to "Google's main business in United States
Google Search, accounting 30% of the profit, is facing fierce competition from Microsoft's Bing" (5)
(copy of the paper: University of Toronto repository, `utoronto.scholaris.ca`, item
c3089f3f-31dd-4e0a-8ddb-a9775d5ba33c). Two codebooks were built from v0.10: `hope_only`, the five
levels followed by the source's definition of specific disclosure and the five sentences with their
score; `both`, the same followed by the five corpus anchors of round 4 with their level. Round 3 (no
examples) and round 4 `five_examples` (anchors only) are the other two variants. Same model and
settings as round 3; the five anchor passages are left out of the scoring of every variant. Files in
`gs://version10test/round5_examples_source/`.

**Result.** 339 human ratings on 285 passages, Cohen's kappa (share identical):

| Examples in the section | on five levels | mapped to three |
|---|---|---|
| none (round 3) | 0.31 (0.47) | 0.37 (0.54) |
| corpus anchors, one per level (round 4) | 0.34 (0.50) | 0.38 (0.57) |
| the source's five sentences | 0.36 (0.52) | 0.42 (0.60) |
| both | 0.30 (0.46) | 0.35 (0.53) |

Distributions on the passages about AI (`boilerplate` / `generic` / `specific` / `detailed` /
`quantified`): none 0 / 97 / 81 / 59 / 1; anchors 2 / 113 / 46 / 78 / 0; source sentences 4 / 110 /
68 / 58 / 1; both 3 / 94 / 77 / 67 / 1; the raters 50 / 125 / 59 / 28 / 5. Labelled 288 (source
sentences) and 290 (both) of 290. Tokens 311,957 / 62,503 and 280,793 / 62,757 input / output.
The other fields did not move.

**Decision.** The source's five sentences go into the codebook, as the illustration of the scale
under the five levels; the corpus anchors do not. The sentences are the best of the four variants on
both readings and the only one whose gain over no examples (0.05 on five levels, 0.05 mapped) is
consistent across kappa and share identical. Both together were worse than either alone and worse
than none; one run cannot say why, and the two sets of examples pull in different directions (the
anchors moved passages from `specific` to `detailed`, the sentences left `detailed` where it was).
The anchors stay documented in entry 20 and in `analysis/v010_subset/substantiveness_3_vs_5.py`.

**Not better / open.** Single runs on 285 passages; the differences between the variants are at the
edge of what the sample resolves, and the ordering could change with another five anchors or a
different trimming of the sentences. The source's sentences are about competition, not AI, and
about specificity alone, while levels 4 and 5 of this taxonomy also ask for the company's measures;
the sentences illustrate the direction of the scale, not its criteria. `boilerplate` is still given
far less often by the model (4) than by the raters (50); the examples did not change that.

