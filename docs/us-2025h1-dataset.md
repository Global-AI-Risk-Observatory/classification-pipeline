# US 10-K AI Disclosure Dataset, filings 2025 H1 (`us-2025h1`)

Chunk-level AI mentions extracted and classified from US annual-report filings filed between 2025-01-02 and 2025-06-30. This run used the chunker, taxonomy and prompts of the predecessor UK pipeline (`84rt/AI-Risk-Observatory`, `pipeline/`), not the `airo` taxonomy v0.3 of this repository; it is a first corpus-wide pass to make the filings usable while the `airo` classifier is being validated.

## Location

All files live in the project's Google Cloud bucket:

```
gs://airo-pipeline-data/us-2025h1/
├── chunks.jsonl                      48,978 chunks, 187 MB
├── documents_manifest.json           7,794 filings
└── results/
    ├── classified_chunks.jsonl       48,978 classified chunks, 18 MB
    ├── filing_metrics.jsonl          one row per filing
    ├── us-filing-metrics.json        shares per filing month
    └── classification_prompt.md      the exact prompt used
```

Raw filings (markdown) are in `gs://airo-filings-raw/markdown/<filing_id>.md` with metadata in `gs://airo-filings-raw/manifest/<filing_id>.json`. Raw filings are not redistributed outside the bucket.

## Corpus

| | |
|---|---|
| Filings | 7,794 |
| Unique companies (CIK) | 4,743 |
| Filing dates | 2025-01-02 to 2025-06-30 |
| Fiscal year 2024 | 6,298 filings |
| Form types | 10-K 4,027; ARS 2,524; 10-K/A 453; 20-F 394; N-CSR 224; other 172 |
| Source | financialfilings.com via `gs://airo-filings-raw` |

Filings per month: Jan 224, Feb 1,955, Mar 2,736, Apr 2,300, May 408, Jun 171.

## Processing

1. **Chunking:** `pipeline/scripts/chunk_markdown.py` of the UK pipeline with default settings (AI keyword gate, 2 paragraphs of context before and after each match, chunks capped at 600 words). 5,387 of 7,794 filings contain at least one AI-keyword chunk; the remaining 2,407 have no AI keyword and count as "no AI mention".
2. **Classification:** one pass per chunk with the merged prompt in `results/classification_prompt.md`, which reproduces the Stage 1 and Stage 2 definitions from the UK pipeline's `pipeline/prompts/classifiers.yaml`. Temperature 0, no extended thinking.
   - Chunks were processed in 1,225 batches of 40. Batches 0 to 866 (34,680 chunks) were classified with Claude Sonnet; the remaining 358 batches (14,298 chunks) with `gemini-2.5-flash` on Vertex AI. Both used the identical prompt and output schema; the dataset does not distinguish them.
3. **Aggregation:** `filing_metrics.jsonl` and `us-filing-metrics.json` roll chunk labels up to filings and filing months.

## Taxonomy

Identical to the UK pipeline (not the `airo` taxonomy of this repository):

- **Mention types** (multi-label): `adoption`, `risk`, `harm`, `vendor`, `general_other_or_ambiguous`, `none`; confidence 0 to 1 per label.
- **Risk types** (when `risk` present): `strategic_competitive`, `operational_technical`, `cybersecurity`, `workforce_impacts`, `regulatory_compliance`, `information_integrity`, `reputational_ethical`, `third_party_supply_chain`, `environmental_impact`, `national_security`, `none`; signal 1 to 3 per type; `risk_substantiveness` in `boilerplate`, `moderate`, `substantive`.
- **Adoption signals** (when `adoption` present): `non_llm`, `llm`, `agentic`, `ambiguous`, each 0 to 3; `adoption_substantiveness` as above.

Not included: the UK vendor sub-classifier (vendor tags and vendor substantiveness). `vendor` appears only as a Stage 1 mention type.

## File schemas

`chunks.jsonl`, one JSON object per line, fields as produced by `chunk_markdown.py`: `chunk_id`, `document_id` (filing_id), `company_id` (CIK), `company_name`, `report_year`, `report_sections`, `chunk_text`, `chunk_word_len`, `matched_keywords`, position fields.

`classified_chunks.jsonl`, one object per chunk:

```json
{"chunk_id": "10001275-chunk-69a692149446",
 "mention_types": ["risk"],
 "confidence_scores": {"risk": 0.9},
 "risk_types": ["cybersecurity", "third_party_supply_chain"],
 "risk_signals": {"cybersecurity": 3, "third_party_supply_chain": 1},
 "risk_substantiveness": "moderate",
 "adoption_signals": {"non_llm": 0, "llm": 3, "agentic": 0, "ambiguous": 0},
 "adoption_substantiveness": "substantive",
 "reasoning": "one sentence"}
```

`risk_*` fields appear only when `risk` is in `mention_types`; `adoption_*` only when `adoption` is. Signals are stored as objects keyed by label, not as lists of `{type, signal}` as in the UK annotations.

`documents_manifest.json`: `{"documents": [...]}` with `document_id`, `company_id`, `company_name`, `year`, `market_segment` (exchange), `filing_date`, `form`, `isic_division`, `isic_class`, `ticker`.

`filing_metrics.jsonl`, one object per filing: identifiers, `filing_date`, `month`, `form`, `isic_division`, `chunks`, and booleans `ai_mention`, `adoption`, `risk`, `harm`, `vendor`, `llm_adoption` (any chunk with llm signal 2 or more), `cyber_risk`, `regulatory_risk`, `risk_substantive`, plus `risk_types`.

`us-filing-metrics.json`: per month, number of filings and the share with each of the booleans above.

## Headline counts

Chunk labels (48,978 chunks): risk 20,011; adoption 19,601; general/ambiguous 7,836; none 8,525; vendor 2,529; harm 149.

Risk types across chunks: regulatory_compliance 11,585; strategic_competitive 8,005; cybersecurity 7,850; operational_technical 7,730; reputational_ethical 7,597; information_integrity 3,390; third_party_supply_chain 3,389; workforce_impacts 522; national_security 161; environmental_impact 70.

Filings (7,794): any AI mention 4,826; AI risk 3,997; AI adoption 2,547; LLM adoption 992; vendor named 636; AI harm 47.

| Month | Filings | AI mention | AI risk | LLM adoption | Cyber risk | Regulatory risk |
|---|---|---|---|---|---|---|
| 2025-01 | 224 | 51% | 34% | 9% | 28% | 22% |
| 2025-02 | 1,955 | 74% | 67% | 16% | 55% | 46% |
| 2025-03 | 2,736 | 57% | 45% | 9% | 35% | 30% |
| 2025-04 | 2,300 | 60% | 49% | 15% | 38% | 35% |
| 2025-05 | 408 | 54% | 39% | 14% | 29% | 28% |
| 2025-06 | 171 | 52% | 39% | 12% | 32% | 27% |

## Known limitations

- No human validation set exists for the US corpus yet; the UK golden set was not re-annotated for US filings.
- Some chunks are unreadable (base64 or binary residue from conversion); these are labelled `none`.
- Chunk-level reasoning strings are one sentence and were not reviewed.
- Filing month is the SEC filing date, not the fiscal period end.

## Loading

```bash
gcloud storage cp -r gs://airo-pipeline-data/us-2025h1/ ./us-2025h1/
```

```python
import json
chunks = [json.loads(l) for l in open("us-2025h1/results/classified_chunks.jsonl")]
```

Dashboard pages that read `us-filing-metrics.json`: `/timeline` and `/timeline-beta` in `dashboard/` of this repository. The regulatory events shown next to the filings are in `docs/regulation-timeline.md`.
