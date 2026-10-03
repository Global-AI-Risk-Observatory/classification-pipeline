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
