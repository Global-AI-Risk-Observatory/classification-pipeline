# Research plan: evaluation design for the classifier

Status: proposal, 2026-10-03. Scope of the first phase: US filings (Form 10-K and related SEC
forms). Other jurisdictions follow once the US pipeline is validated. Items 1 and 2 of the original list (criteria-based value
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
`aggregate.py`; reported per report, then per year and ISIC division.

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
   and do they increase after regulatory pressure (SEC cybersecurity disclosure rule, Item 1C,
   effective for fiscal years ending on or after 15 December 2023; SEC enforcement and comment
   letters on misleading AI claims, "AI washing", since 2024)? Metric: activation rate per
   report, year, industry.
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

# Jesse's Research Thoughts

## High Level
- RQ1 - What are the dominant discourse themes regarding AI in USA SEC Form 10-K filings, and have these shifted over time.
- RQ 2 - How has the substantiveness of AI related discourse in USA SEC Form 10-K filings shifted over time.

## Specific Questions
- Can these shifts be mapped to external factors (inform a hypothesis based on literature review from policy team) 
- Does discourse/substantiveness change at different business ‘levels’ (i.e. state vs federal, different industries, F500 vs rest) and how do these map to external factors.

## Corpus
- All US based companies annual report filings from 2020 - Current day 
- Only ONE 10-K form per issuer/fiscal year.
- Thanks financial filings :) 

## Methodology
### 1 - Extract AI related mentions 
- Use Diana’s glossaries (direct AI mention vs general industry specific contextual mentions)
- LLM evaluator/human QA to check accuracy 
- Evaluate precision vs recall of extraction
### 2 - Classify data points 
- Possibly conduct EDA to identify groupings
  - Potential to use Evalet for this.
  - Alternatively use embedding/clustering methods to identify text groupings and qualitative evaluation to get themes.
- Otherwise define groupings based on policy team literature review for relevant AI-discourse themes (slightly changes RQ1)
- Classify data at scale using LLM with strict guidelines
  - JEV vs DSpy vs Normal LLM
  - Note (DSPy requires training data to optimize classification accuracy, would need large enough human annotated dataset)
### 3 - Evaluate classifier performance (Quality Assurance)
- Compare with the human annotated ‘golden set’?
- Inter-rater reliability (Cohens Kappa, Threshold = 0.8)
### 4 - Analyse classified data trends (RQ1)
- Provides broad high-level response to RQ1.
- What classification is mentioned most?
- What is the change in mentions over time?
- Hypothesis - Strong increase in adoption/risk related mentions over time
### 5 - Link classified data trends to external factors (RQ1)
- Can specific external factors be linked to changes in reporting?
- Have policy/regulations lagged behind company AI disclosures or preceded?
### 6 - Evaluate substantiveness (RQ2)
- Use Evalet to analyse substantiveness scores across classification groups/business levels over 2020 - Current time period.
- Exploratory data analysis to find trends in substantiveness.
- Evalet identifies functions that are relevant to the evaluation criteria.
- This can be used as a method to identify discourse trends.
Further informs exploratory data analysis linking to external factors.
- E.g. High substantiveness datapoints all reference clear roadmaps for delivery as a function. Through further analysis we find that there was a significant increase in references to clear roadmaps for delivery after the EU Artificial Intelligence Act (2024) was passed. This trend was observed first in predominantly F500 companies, with smaller, non-international businesses lagging behind by 1-2 fiscal years.

## Note - External Factors Definition
- Below is a list of things that can be considered ‘external factors’. List can be adjusted over time as research goes on. These are just potential things to consider right now.
- Any state, federal, or international government policies, frameworks, or regulations related to AI governance and use. (primary focus factor)
- Global economic factors such as recession or hardware availability and price.
- Highly publicised AI ‘scandals’. I.e. OpenAI breach of Australian health system/hugging face
Social sentiment

## Note - Substantiveness
- Substantiveness is just a placeholder definition to mean the quality of a datapoint, which is the extracted text of an AI mention.
- It is being used because that was the terminology Bart defined in the UKAIRO project.
- The term is open to change depending on results of literature reviews and relevant research that further informs this topic.
There is strong potential to add further criteria that relate to the perceived ‘quality’ of a datapoint. Examples below.
- Relevance (How relevant is this datapoint to global discourse around AI at the time it was published)
- Social acceptability (Does the content of the datapoint describe any actions that may not be well received by the public?)
- Morality (Is the use of AI described in the datapoint likely to produce discriminatory systems that violate human rights, autonomy,  or social and cultural values?)
- Believability (Similar to substantiveness but focuses on if the claim made in the datapoint is believable/realistic. E.g. not believable = Elon Musk promising 1 million fully automatic robotaxis by end of 2020 in 2019)
- These criteria all provide rich avenues of evaluation, but mostly derive from how substantive a datapoint is. If a datapoint is not substantive and just contains boilerplate, then it is unlikely to generate a strong signal from any of these other criteria too.
- A potential analysis option could be evaluate substantiveness → Filter out low substantive data points → Evaluate additional criteria

## Notes - Quality Assurance
- Need to design a technical evaluation of classification performance to verify data quality.
- Most likely using multiple human annotators on the same subset of data points then verifying inter-rater agreement between human annotators (human - human) and annotators to LLM classifier (annotators - LLM)
- If classification categories are similar to UKAIRO, compare with that data too.

# Dan's Research Thoughts

## High Level

- RQ1 - To what extent are AI risks disclosed by companies avoidable, reducible, trade-off bound, irreducible, or better addressed by not using AI for the relevant task?
  - Go beyond identifying which risks companies mention and consider how far those risks can be addressed. This might be more relevant to some risk categories than others.
- RQ2 - When a company discloses a specific AI risk, does it subsequently make observable changes that appear to address that risk?
  - Possible changes could include governance, controls, mitigation, adoption decisions, vendor choices or policies.
- RQ3 - To what extent do companies demonstrate awareness of the AI risks associated with their own AI use, adoption, products or dependencies?
  - Distinguish generic acknowledgement from understanding of concrete risks connected to the company's activities and responses. This concerns what companies demonstrate through disclosure, rather than what they know internally.

## Notes / Other Ideas

- Compare changes in AI disclosures with model releases and vendor activity.
- Explore a lightweight, reproducible report labeler using lexical retrieval and a small trained classifier, rather than repeated general-purpose LLM calls.
- Use cosine similarity / embeddings to classify mentions into the taxonomy and explore how clearly categories can be distinguished.
- Use interpretable ML to inspect what distinguishes taxonomy categories and whether some should be merged, split or redefined.
- Compare LLM-written and human-written disclosures: do they mention different risks, or differ in specificity or how they obscure risks?
- Explore compliance-oriented versus concern-oriented disclosure through observable language characteristics, potentially as part of RQ3.

# Rahul's Research Thoughts

## Research Questions
-RQ1- How can the MIT taxonomy be extended to rate the severity of AI risks, not only their type,
based on the level of AI adoption and exposure to market risk?

-RQ2- How well do the AI risks companies disclose match the risks implied by their AI adoption,
and what explains the gaps?

-RQ3- What new AI risks have emerged since the last version of the taxonomy, and what changes
to its domains or subdomains would be needed to cover them?

## Proposed Methodologies
For RQ1- The framework employed in this paper (https://arxiv.org/pdf/2602.04358) could be used for reference along with the domains and subdomains in MIT Risk Taxonomy.

For RQ2- Could use AI Incident tracker to obtain risks associated with particular uses of AI and use that as reference to cross check with disclosure by the company. Can be combined with Dan's RQ3.

For RQ3- Probably classification and then modifying Evalet for clustering similar new risks.

