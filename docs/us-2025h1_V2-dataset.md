# US 10-K AI Disclosure Dataset, filings 2025 H1, run V2 (`us-2025h1_V2`)

Chunk-level AI mentions extracted and classified from US annual-report filings filed between 2025-01-02 and 2025-06-30, produced with the `airo` pipeline of this repository (`src/airo`, taxonomy v0.5). It covers the same 7,794 filings as `us-2025h1`, which was produced with the chunker, taxonomy and prompts of the predecessor UK pipeline. Both runs are kept side by side in the bucket so that they can be compared; `us-2025h1` is unchanged.

## Location

All files live in the project's Google Cloud bucket:

```
gs://airo-pipeline-data/us-2025h1_V2/
├── chunks.jsonl                      28,395 chunks, 104 MB
├── documents_manifest.json           7,794 filings
├── README.md                         this description
└── results/
    ├── classified_chunks.jsonl       27,931 classified chunks, 20 MB
    ├── filing_metrics.jsonl          one row per filing
    ├── us-filing-metrics.json        shares per filing month
    └── classification_prompt.md      the codebook used (taxonomy v0.5)
```

The same folder also holds the files of a 40-filing test of the same pipeline (`chunks/tasks.jsonl`, `chunks/hints.jsonl`, `results/labels_final.jsonl`, `results/gemini.jsonl`, `results/gemini.jsonl.run.json`, `results/report_summary.jsonl`, `results/codebook.md`, `results/agreement.json`, `results/reports/`). Its 127 labels are part of this dataset.

Raw filings (markdown) are in `gs://airo-filings-raw/markdown/<filing_id>.md` with metadata in `gs://airo-filings-raw/manifest/<filing_id>.json`. Raw filings are not redistributed outside the bucket.

## Corpus

| | |
|---|---|
| Filings | 7,794 |
| Distinct texts | 7,782 (12 filings have the same text as another filing) |
| Unique companies (CIK) | 4,742 (19 filings carry no CIK) |
| Filing dates | 2025-01-02 to 2025-06-30 |
| Fiscal year 2024 | 6,298 filings (2025: 487; 2023: 36; not given by the data provider: 967) |
| Form types | 10-K 4,027; ARS 2,524; 10-K/A 453; 20-F 394; N-CSR 224; 20-F/A 32; 40-F 27; other 73; not given 40 |
| Source | financialfilings.com via `gs://airo-filings-raw` |

Filings per month: Jan 224, Feb 1,955, Mar 2,736, Apr 2,300, May 408, Jun 171.

## Processing

1. **Parsing:** `python -m airo run` (`src/airo/ingest.py`) reads each filing's Markdown into ordered text blocks (paragraphs, headings, list items, table rows), attaches the Form 10-K Item and the nearest heading to every block, and takes the filing's metadata from its manifest file. Filings with identical text are merged into one document.
2. **Chunks:** `src/airo/retrieve.py` searches the blocks with the core glossary (500 terms) plus the glossary of the company's ISIC division and class, and joins every hit with one neighbouring block on each side, within the same section, into a passage. A passage with at least one term that itself denotes AI is a direct mention and is a chunk of this dataset: 28,395 chunks from 5,368 filings. The remaining 2,426 filings have no such passage and count as "no AI mention". Passages that only contain industry context terms (63,801) are not classified and are not part of this folder.
3. **Classification:** `python -m airo.coders.gemini` with `gemini-2.5-flash` on Vertex AI, temperature 0, thinking switched off, JSON output bound to the label schema, and the codebook in `results/classification_prompt.md`. Every label is checked by the pipeline's acceptance check (`classify.validate`): the schema's rules, and every evidence quote must be a verbatim stretch of the chunk. A quote that differs from the chunk only in quotation marks, apostrophes or dashes is stored in the chunk's own characters. A chunk whose label is rejected is asked again, with the rejected answer and the reason, up to two times. A label that is still rejected is left out: 464 chunks (1.6%) have no label (evidence not verbatim 443, `frame` missing 13, no evidence 5, other 3).
4. **Aggregation:** `accept` and `adjudicate` (one coder), then `filing_metrics.jsonl` and `us-filing-metrics.json` roll the chunk labels up to filings and filing months.

## Taxonomy

The `airo` taxonomy v0.5 of this repository (`src/airo/taxonomy.py`), not the taxonomy of `us-2025h1`:

- **`ai_reference`**: `explicit`, `implicit`, `none`. With `none` all other fields are empty.
- **`frame`** (one): `risk_factor`, `governance`, `business`, `market`.
- **`roles`** (one or more): `market_driver`, `adoption`, `offering`, `risk`, `governance`, `incident`, `general`.
- **`risk_types`** (if and only if `risk` is a role): `market_demand`, `strategic_competitive`, `operational_reliability`, `cybersecurity`, `third_party`, `regulatory_legal`, `workforce`, `reputational_ethical`, `information_integrity`, `environmental`, `other`.
- **`adoption_stage`** (if and only if `adoption` is a role): `planned`, `piloting`, `deployed`, `unclear`.
- **`ai_kind`** (one): `generative`, `non_generative`, `unspecified`.
- **`substantiveness`** (one, five ordered levels): `boilerplate`, `generic`, `specific`, `detailed`, `quantified`.
- **`disclosure_traits`** (zero or more): `boilerplate`, `hedging`, `externalisation`, `vagueness`, `safe_harbour`.
- **`entities`**, **`evidence`** (1 to 3 verbatim quotes), **`confidence`** (`low`, `medium`, `high`).

## File schemas

`chunks.jsonl`, one JSON object per line: `chunk_id` (`<text id>:<first block>-<last block>`), `document_id` (filing_id), `company_id` (CIK), `company_name`, `report_year`, `report_sections`, `heading`, `chunk_text`, `chunk_word_len`, `matched_keywords`, `blocks`.

`classified_chunks.jsonl`, one object per classified chunk:

```json
{"chunk_id": "0005a4f1c2d3e4f5:120-122",
 "ai_reference": "explicit",
 "frame": "risk_factor",
 "roles": ["risk"],
 "risk_types": ["cybersecurity", "third_party"],
 "adoption_stage": null,
 "ai_kind": "unspecified",
 "substantiveness": "generic",
 "disclosure_traits": ["hedging"],
 "entities": [],
 "evidence": ["a verbatim quote from the chunk"],
 "confidence": "high",
 "taxonomy_version": "0.5"}
```

The `chunk_id` above only illustrates the format. Chunks without a label (464) have no line.

`documents_manifest.json`: `{"documents": [...]}` with `document_id`, `company_id`, `company_name`, `year`, `market_segment` (exchange), `filing_date`, `form`, `isic_division`, `isic_class`, `ticker`, `text_id` (the same for filings with identical text).

`filing_metrics.jsonl`, one object per filing: identifiers, `filing_date`, `month`, `form`, `isic_division`, `chunks`, `chunks_labelled`, `chunks_without_label`, the booleans below, `risk_types`, `roles`, `substantiveness` (chunks per level) and `highest_substantiveness`.

| Boolean | True if at least one chunk of the filing about AI has |
|---|---|
| `ai_mention` | `ai_reference` `explicit` or `implicit` |
| `adoption` | role `adoption` |
| `risk` | role `risk` |
| `harm` | role `incident` |
| `vendor` | at least one entity named |
| `llm_adoption` | role `adoption` and `ai_kind` `generative` |
| `cyber_risk` | risk type `cybersecurity` |
| `regulatory_risk` | risk type `regulatory_legal` |

`us-filing-metrics.json`: per month, number of filings, the share with each of the booleans above, and `highestSubstantivenessShare`, the share of filings by their highest substantiveness level.

## Headline counts

Chunks (28,395): classified 27,931, of which `explicit` 25,150, `implicit` 212, `none` 2,569; without label 464.

Roles across the 25,362 chunks about AI: risk 11,387; offering 8,662; adoption 5,973; market_driver 2,696; governance 1,769; general 1,291; incident 8.

Frames: business 12,048; risk_factor 11,155; market 1,388; governance 771.

Risk types: regulatory_legal 5,348; cybersecurity 3,920; operational_reliability 3,442; strategic_competitive 3,359; reputational_ethical 2,502; market_demand 1,025; third_party 1,008; information_integrity 924; workforce 347; other 279; environmental 62.

Adoption stage: deployed 4,254; planned 863; unclear 738; piloting 118.

Kind of AI: unspecified 18,083; generative 4,425; non_generative 2,854.

Substantiveness: boilerplate 823; generic 7,273; specific 9,445; detailed 7,655; quantified 166.

Disclosure traits: hedging 5,779; vagueness 2,625; boilerplate 1,275; externalisation 752; safe_harbour 56; none 17,986.

Evidence: 40,241 quotes, each a verbatim stretch of its chunk.

Filings (7,794): any AI mention 4,992; AI risk 4,079; AI adoption 2,646; LLM adoption 1,128; entity named 2,052; AI incident 3; cyber risk 2,996; regulatory risk 2,845. Highest substantiveness: boilerplate 51; generic 942; specific 1,152; detailed 2,759; quantified 88.

| Month | Filings | AI mention | AI risk | LLM adoption | Cyber risk | Regulatory risk | Adoption |
|---|---|---|---|---|---|---|---|
| 2025-01 | 224 | 53% | 38% | 9% | 28% | 25% | 22% |
| 2025-02 | 1,955 | 75% | 68% | 19% | 52% | 47% | 41% |
| 2025-03 | 2,736 | 60% | 46% | 11% | 33% | 31% | 29% |
| 2025-04 | 2,300 | 63% | 51% | 16% | 36% | 38% | 37% |
| 2025-05 | 408 | 58% | 39% | 13% | 28% | 29% | 31% |
| 2025-06 | 171 | 56% | 40% | 11% | 29% | 28% | 23% |

## Relation to `us-2025h1`

Same filings, different pipeline. The two runs differ in how chunks are found and cut (glossary with industry terms and one neighbouring block here; a fixed keyword list with two paragraphs of context and a 600-word cap there), in the taxonomy and in the prompt. Figures of the two runs with the same name are therefore not the same measure: `adoption` here includes planned use (`adoption_stage` `planned`) and separates the company's own AI products (`offering`), and substantiveness has five levels here against three there.

## Known limitations

- No human validation set exists for the US corpus yet.
- 464 chunks have no label; 352 filings contain at least one of them, so their filing-level booleans can be understated.
- Passages with industry context terms only are not classified.
- Sections are detected from Form 10-K "Item" headings only; other forms get no sections.
- Chunks are not capped in length: the median is 282 words, the mean 398, the longest 31,849.
- The same report can appear under two filing ids (a 10-K and the ARS that reprints it); only filings with identical text are merged.
- `vendor` is set by any named entity, which includes organisations that are not AI vendors.
- Filing month is the SEC filing date, not the fiscal period end.

## Loading

```bash
gcloud storage cp gs://airo-pipeline-data/us-2025h1_V2/results/classified_chunks.jsonl .
```

```python
import json
labels = [json.loads(l) for l in open("classified_chunks.jsonl")]
```
