# One passage per request against 40 passages per request

Report on the question raised in the team thread "Pipeline: batch API and accuracy": whether sending
40 passages in one request changes the labels compared with one passage per request. Date: 2026-10-20.

## Summary

- Run `us-2025h1_V2` (2026-10-12) was classified with both settings in the same run: the first
  11,804 passages in task order with one passage per request, the remaining 16,591 with 40 per
  request. The switch happened mid-run when the coder got its batch mode.
- The same 11,500 passages that were labelled one per request were labelled again on 2026-10-20 with
  40 per request, identical code, codebook, model and settings. Direct same-passage agreement:
  ai_reference 95.6% (kappa 0.76), frame 93.3% (0.88), ai_kind 92.4% (0.83), role `risk` kappa 0.89;
  substantiveness 64.8% (0.49), disclosure traits kappa 0.20 to 0.55, secondary risk types 0.44 to 0.56.
  All core fields identical: 30.5% of passages.
- The fields with low agreement are the judgement fields. The same fields are the weak ones in the
  model-against-model comparison on run V3, independent of the request size.
- The differences are directed, not random: one per request assigns more roles and risk types per
  passage; 40 per request sets substantiveness higher.
- Cost: one per request about 7,500 input tokens per passage; 40 per request about 2,400 per passage
  including the single re-asks (USD 14.79 for 11,500 passages).
- Not available yet: the model's own repeat variance at one per request, and human labels (the V3
  rater sheets exist, the label files are empty as of 2026-10-18).

## 1. How run V2 was classified

Commit `c0dd254` (2026-10-12, 21:49 CEST, "Gemini coder: 40 tasks per request by default") added
the batch mode. The run was already in progress. The Vertex AI metrics of the project that served the
requests show the switch (gemini-2.5-flash, 10-minute bins):

| Time (CEST) | Requests per 10 min | Input tokens per request | Output tokens per request |
|---|---|---|---|
| 21:00 to 21:50 | 2,477 to 2,898 | 7,100 to 8,700 | 215 to 220 |
| 21:50 to 22:00 | 0 | | |
| 22:00 to 23:10 | 316 to 429 | 12,800 to 20,400 | 1,460 to 1,750 |

The first phase is codebook v0.5 (23.7 KB, about 6,000 tokens) plus one passage per request. The
second phase is codebook plus 40 passages per request, mixed with single re-asks of rejected labels;
a 40-passage answer alone has about 10,000 output tokens, so most requests of the second phase were
re-asks (estimated 2,000 of 2,371). Output tokens, 2.83 million in phase 1 and 3.80 million in
phase 2, add up to the 28,395 tasks of the run, so nothing was labelled twice. The export to the
bucket followed at 23:00 CEST.

`classified_chunks.jsonl` is in task order (text id, then block). A change-point test on "roles per
passage" puts the switch at position 11,804 of 28,395. The 127-passage test before the run
(`us-2025h1_V2/results/gemini.jsonl.run.json`: 825,290 input tokens for 127 tasks, 6,498 per task)
was also one per request. The run's README does not mention any of this; `docs/changes.md` says the
comparison of 2026-10-12 is "not recorded in this repository".

## 2. Between-sample comparison inside run V2

Part A (positions 0 to 11,499, one per request) against part B (positions 12,200 to 28,394, 40 per
request). Both are random draws from the corpus because the order is a hash. The noise column is the
difference between the even and the odd positions of part B.

| Measure | A (1 per request) | B (40 per request) | A minus B | Noise within B |
|---|---|---|---|---|
| no accepted label % | 2.0 | 1.4 | +0.6 | 0.1 |
| ai_reference = none % | 10.0 | 8.4 | +1.7 | 0.0 |
| frame = risk_factor % | 47.2 | 41.8 | +5.4 | 0.5 |
| role risk % | 49.0 | 42.1 | +6.9 | 0.7 |
| role market_driver % | 13.7 | 8.5 | +5.2 | 0.7 |
| role general % | 3.4 | 6.3 | -2.9 | 0.4 |
| roles per passage | 1.34 | 1.19 | +0.15 | 0.00 |
| risk types per risk passage | 2.10 | 1.82 | +0.28 | 0.03 |
| operational_reliability % of risk passages | 34.7 | 26.5 | +8.3 | 1.5 |
| market_demand % of risk passages | 12.4 | 6.3 | +6.1 | 0.8 |
| third_party % of risk passages | 11.7 | 6.5 | +5.1 | 0.6 |
| substantiveness = specific % | 41.1 | 34.3 | +6.7 | 1.4 |
| substantiveness = detailed % | 25.7 | 33.4 | -7.7 | 1.4 |
| trait hedging % | 26.6 | 20.2 | +6.4 | 0.0 |
| trait vagueness % | 13.2 | 8.4 | +4.9 | 0.2 |
| no trait % | 68.0 | 72.9 | -4.9 | 0.1 |
| ai_kind = non_generative % | 13.1 | 10.1 | +3.0 | 0.3 |
| confidence = high % | 99.7 | 98.5 | +1.2 | 0.1 |

Unchanged between A and B: cybersecurity (34.8 / 34.2), strategic_competitive, generative
(17.6 / 17.3), role adoption (24.1 / 23.1), entity named (23.4 / 23.8). Part A has slightly more ARS
and 20-F filings (10-K 48.7% against 53.4% of passages); the differences persist within 10-K, ARS and
20-F taken separately.

## 3. Direct comparison: the same 11,500 passages labelled both ways

Setup of the second labelling (2026-10-20), all files in `gs://chunk_validation40_or1`:

| | |
|---|---|
| Code | `src/airo/coders/gemini.py` at commit `c0dd254`, the code of the 40-per-request part of run V2 |
| Codebook | v0.5, byte-identical to `us-2025h1_V2/results/codebook.md` |
| Tasks | rebuilt from the raw filings with `airo run` and `airo tasks` at the same commit; all 11,500 passage texts identical to `us-2025h1_V2/chunks.jsonl` |
| Model | gemini-2.5-flash on Vertex AI, temperature 0, thinking budget 0, JSON output bound to the label schema |
| Request | 40 passages per request, codebook once per request; a rejected label is asked again on its own with the reason, up to two times; 16 concurrent requests |
| Parts | four consecutive runs of 2,880 / 2,880 / 2,880 / 2,860 tasks, so the grouping into 40s equals one run |
| Result | 11,346 of 11,500 labelled; 154 rejected after repairs (evidence not verbatim 153, invalid JSON 1); 1,131 tasks asked again on their own |
| Tokens | 27,214,640 input, 2,651,977 output; USD 14.79 at 0.30 / 2.50 per million; 20.6 minutes |

The one-per-request labels are the stored labels of run V2 for these passages (11,270 of 11,500 have
one; 230 were rejected in that run, 2.0%).

### Agreement per field

11,216 passages have a label from both labellings; 9,995 are labelled as about AI by both.

| Field | n | Agreement | Kappa |
|---|---|---|---|
| ai_reference | 11,216 | 95.6% | 0.76 |
| frame | 9,995 | 93.3% | 0.88 |
| ai_kind | 9,995 | 92.4% | 0.83 |
| adoption_stage (both adoption) | 1,829 | 83.9% | 0.64 |
| substantiveness | 9,995 | 64.8% | 0.49 (weighted 0.61) |
| roles, set identical | 9,995 | 70.2% | mean Jaccard 0.81 |
| risk_types, set identical (both risk) | 4,414 | 59.7% | mean Jaccard 0.80 |
| disclosure_traits, set identical | 9,995 | 67.8% | mean Jaccard 0.73 |
| entities, set identical | 9,995 | 82.0% | |
| evidence, same first quote | 9,995 | 75.7% | |

Identical on ai_reference, frame and roles: 68.7%. Identical on all core fields (ai_reference,
frame, roles, risk_types, adoption_stage, ai_kind, substantiveness, disclosure_traits): 30.5%.

### Per value

| Field | Value | 1 per request | 40 per request | both | only 1/req | only 40/req | Kappa |
|---|---|---|---|---|---|---|---|
| roles | risk | 4,932 | 4,434 | 4,414 | 518 | 20 | 0.89 |
| roles | offering | 3,569 | 3,301 | 2,924 | 645 | 377 | 0.77 |
| roles | adoption | 2,408 | 2,329 | 1,829 | 579 | 500 | 0.70 |
| roles | market_driver | 1,361 | 861 | 731 | 630 | 130 | 0.62 |
| roles | general | 323 | 460 | 248 | 75 | 212 | 0.62 |
| roles | governance | 834 | 554 | 390 | 444 | 164 | 0.53 |
| risk_types | cybersecurity | 1,676 | 1,603 | 1,517 | 159 | 86 | 0.88 |
| risk_types | regulatory_legal | 2,176 | 2,029 | 1,970 | 206 | 59 | 0.88 |
| risk_types | strategic_competitive | 1,299 | 1,284 | 1,149 | 150 | 135 | 0.84 |
| risk_types | reputational_ethical | 1,088 | 922 | 839 | 249 | 83 | 0.79 |
| risk_types | operational_reliability | 1,648 | 1,227 | 1,175 | 473 | 52 | 0.73 |
| risk_types | workforce | 176 | 113 | 107 | 69 | 6 | 0.73 |
| risk_types | third_party | 555 | 262 | 244 | 311 | 18 | 0.56 |
| risk_types | market_demand | 523 | 258 | 232 | 291 | 26 | 0.56 |
| risk_types | information_integrity | 487 | 270 | 183 | 304 | 87 | 0.44 |
| disclosure_traits | hedging | 2,685 | 2,145 | 1,583 | 1,102 | 562 | 0.55 |
| disclosure_traits | externalisation | 354 | 235 | 119 | 235 | 116 | 0.39 |
| disclosure_traits | vagueness | 1,337 | 909 | 343 | 994 | 566 | 0.22 |
| disclosure_traits | boilerplate | 744 | 415 | 141 | 603 | 274 | 0.20 |

### Direction of the differences

- One per request assigns more labels per passage: 13,427 role assignments against 11,939 on the
  same 9,995 passages; for risk types the gap is in operational_reliability, third_party,
  market_demand and information_integrity. The role `risk` itself and the main risk types
  (cybersecurity, regulatory_legal, strategic_competitive) hardly move.
- Substantiveness goes up with 40 per request: 2,107 passages higher, 1,409 lower; the most frequent
  change is specific to detailed (959), followed by specific to generic (746) and generic to
  specific (558).
- ai_kind: 443 passages go from non_generative to unspecified.
- ai_reference: 266 passages go from none to explicit, 73 the other way.
- adoption_stage: 117 passages go from deployed to unclear, 44 the other way.
- Rejected labels: 2.0% with one per request, 1.3% with 40 per request.

## 4. What the figures say and what they do not

- The weak fields are the judgement fields: substantiveness, disclosure traits and the secondary risk
  types. The fields with a clear definition agree at kappa 0.76 to 0.89.
- The same pattern appears in the model-against-model comparison on run V3
  (`jev_results_us-2025h1_V3/kappa.jsonl`, 1,197 passages): substantiveness 0.29,
  information_integrity 0.27, market_demand 0.36, third_party 0.49, against risk 0.89,
  regulatory_legal 0.88, cybersecurity 0.82. The instability belongs to the field, not to one setup.
- The shift between the two settings is directed (more labels with one per request, higher
  substantiveness with 40), so it is not only random scatter in a fuzzy field. Random scatter would go
  both ways in about equal numbers.
- Missing to separate the two: the model's repeat variance at the same setting. For 60 implicit-sample
  passages the same 40-passage request sent twice gave identical labels on 59 of 59 (`docs/changes.md`,
  section 12). There is no such figure for one per request.
- No human reference exists yet: the V3 validation sheets (290 passages, 60 double-rated, 7 raters)
  are in `us-2025h1_V3/human_validation/`, and the label files `labels/human_1..7.jsonl` are empty
  (0 bytes, 2026-10-18).

## 5. Cost

| Setting | Input tokens per passage | Source |
|---|---|---|
| 1 per request | about 7,500 | V2 phase 1 metrics; 127-passage test 6,498 |
| 40 per request, including single re-asks | about 2,400 | this validation: 27.2 million for 11,500 |
| 40 per request, batch share only | about 780 | `docs/changes.md` measurement |

The single re-asks (9.8% of the tasks here, each with the whole codebook) make up most of the input
of the 40-per-request setting.

## 6. Side finding

The Gemini part of run `us-2025h1` (UK pipeline on the US filings, 2026-10-11) shows 14,302
requests for 14,298 chunks in the same metrics, so it ran one chunk per request, not in batches of
40 as its README states.

## Files

- `gs://chunk_validation40_or1/`: README.md, passage_ids.json, tasks.jsonl, codebook.md,
  labels_1per_request.jsonl, labels_40per_request.jsonl, parts/ (four coder runs with run files),
  comparison.json, comparison.md, compare_direct.py.
- `gs://airo-pipeline-data/us-2025h1_V2/`: the run compared.
