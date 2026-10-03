# Research plan: evaluation design for the classifier

Status: proposal, 2026-10-03. Items 1 and 2 of the original list (criteria-based value
definitions, disclosure traits as a label field) are implemented in taxonomy v0.3 and are not
repeated here. Everything below is open.

The design: a construct grounded in prior theory with checkable criteria per trait, perspectives
with different information access, an activation metric and a detection metric, and human
annotation as validation of the measurement rather than as the research question itself.

## 1. Second perspective: passage-only vs. full-context coding

**Today.** The classifier sees one passage: the hit block and one neighbouring block on each
side, plus company, form, year, section and heading. The codebook says to judge from the passage
alone.

**Change.** A `tasks --perspective full` option that adds to each task the whole section the
passage sits in and, when available, the matching passage of the previous year's report. Labels
carry a `perspective` field (`passage` or `full`). `adjudicate` compares the two perspectives
on the same passages.

**What it measures.** The share of labels that change when context is added, per field. This is
the detection gap of the passage-only design and tells us which fields need context (expected:
`adoption_stage`, `disclosure_traits`) and which do not (expected: `ai_reference`, `roles`).

**Prerequisites.** Several years of the same company (needs the provider API), and section
boundaries for non-10-K formats.

## 2. Activation rate and detection accuracy as report-level metrics

**Activation rate.** Per report: the share of AI passages with at least one disclosure trait, and
the share per trait (boilerplate, hedging, externalisation, vagueness, safe harbour). Ten lines in
`aggregate.py`; reported per report, then per year, ISIC division and country.

**Detection accuracy.** Per field: the share of passages on which the passage-only label equals
the full-context label (item 1), and, once human labels exist, equals the human label.

**Hypothesis to test.** Detection accuracy falls as the activation rate rises: the more a report
obscures, the less reliably passage-level classification recovers the risk.

## 3. Human annotation protocol

- Unit: the task (one passage), labelled with the current codebook.
- Sample: stratified by ISIC section, form type and year; 20 % of tasks double-annotated by
  two humans.
- Tooling: `tasks --sample <share> --double` writes the sample and an annotator sheet (one row
  per passage, one column per field with the allowed values); an import turns the sheet back into
  a coder file for `accept`.
- Agreement: Cohen's kappa per field in `adjudicate`, human-human and human-model, in addition to
  the current unanimity share. Target before scaling classification: kappa >= 0.65 on
  `ai_reference`, `roles` and `risk_types`.
- Model accuracy against the human majority per field, overall and per ISIC section.
- Disagreements are read, not just counted: systematic ones (the model reads presupposed use as
  adoption) go back into the codebook; random ones justify majority voting.
- The 474 human annotations of the earlier UK pipeline (15 companies, old taxonomy) can serve as
  a first comparison for `risk_types`, where the two taxonomies overlap.

## 4. Boilerplate measured, not judged

**Method.** Normalise every sentence of every AI passage (case, numbers, company names), hash
sentence shingles, and index them across all reports (MinHash/LSH once the corpus is large).
Per passage, store a `boilerplate_score`: the share of its sentences that occur, near-verbatim,
in reports of other companies.

**Use.** An objective counterpart to the model's `boilerplate` trait, a check on the model, and
the basis for the template-diffusion question: which sentences spread between which companies,
when, and whether the paths follow auditors, law firms, sectors or countries.

**Prerequisites.** Thousands of reports; the code itself is small.

## 5. Research questions the pipeline is being built to answer

1. **Obscuring traits in AI risk disclosure.** Which disclosure traits dominate AI risk language,
   and do they increase after regulatory pressure (SEC Item 1C from 2023, EU AI Act)? Metric:
   activation rate per report, year, industry.
2. **How much of the label lies outside the passage.** Divergence between passage-only and
   full-context coding, per field (item 1).
3. **Detection asymmetry.** Does classification accuracy, for models and for humans, fall as the
   obscuring of a report rises (item 2)?
4. **Template diffusion.** Do AI risk sentences travel verbatim between companies, and along which
   paths (item 4)?
5. **LLM-written AI risk disclosure.** Is the share of model-generated passages rising, and is
   obscuring in model-written text detected worse? Needs a detector for model-generated text;
   not part of the current pipeline.
6. **Role instead of risk.** In industries where AI is a demand driver (energy, mining,
   semiconductors), AI risk appears as market risk, not technology risk. Does the risk type shift
   systematically with the company's position in the AI value chain (ISIC division)?
