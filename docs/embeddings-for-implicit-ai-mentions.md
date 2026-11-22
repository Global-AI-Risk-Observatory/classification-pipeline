# Embeddings for implicit AI mentions: test and result

Report on the question whether text embeddings should be added to the retrieval step of the EU
extension (branch `multi-region`) to find passages that describe AI without naming it.
Date: 2026-11-22.

## Summary

- Recommendation: do not add embeddings in the form tested here.
- On 233 passages judged as implicit AI mentions, the glossaries find 192 (82%). Embeddings find
  95 (41%) when they are allowed to pass the same share of passages that are not about AI.
- Of the 41 implicit passages the glossaries miss, embeddings find 18 at that setting. Finding 27
  of the 41 requires letting 20% of the passages that are not about AI through instead of 9%.
- Applied to every paragraph of the sample reports, the highest-scoring paragraphs without a
  glossary hit are general risk text. Of 85 such paragraphs read (German, Spanish, French), none
  describes AI.
- 39 of the 41 passages the glossaries miss are Spanish.
- Only one design was tested: similarity to twelve English descriptions of AI systems. Other
  designs were not tested (section 6).

## 1. Why this was tested

Retrieval uses a glossary with two tiers. A passage with a term of the `ai` tier goes to the
classifier. A passage that only has terms of the `context` tier (for example analytics, automation,
algorithm) is kept and counted, but it is not sent to the classifier. Under the codebook, a
description of analytics, automation or algorithms that does not name AI is `none` for
`ai_reference`.

Two concerns were raised in the team:

1. Passages that describe AI in several words without any AI term ("implicit mentions") may be
   missed or handled inconsistently.
2. A glossary matches single terms. It cannot recognize a paraphrase whose meaning only arises
   from several words together.

Embeddings compare the meaning of whole paragraphs, so they are the obvious candidate for the
second concern. The test asks: do embeddings find implicit AI mentions that neither the glossary
nor keyword probes find, at an acceptable amount of unrelated text?

## 2. Data

- Reports: the sector sample of the EU extension, annual reports in German, French, Spanish and
  Polish released in 2025.
- Unit: a paragraph of the report text ("block").
- Judgments: 8,439 blocks from the sector check of the glossaries, each judged as explicit (names
  AI), implicit (describes AI without naming it) or not about AI. The judgments were made by a
  language model reading each block, not by human raters. The blocks were chosen with keyword
  probes.

| Language | explicit | implicit | not about AI |
|---|---|---|---|
| German | 110 | 28 | 1,492 |
| French | 486 | 75 | 2,128 |
| Spanish | 411 | 126 | 2,112 |
| Polish | 15 | 4 | 1,286 |
| All | 1,022 | 233 | 7,018 |

Where the 233 implicit passages end up in the pipeline today: 185 have only a `context` term
(kept and counted, not classified), 41 have no glossary hit (not found), 7 have an `ai` term
(classified).

## 3. Method

Model: `gemini-embedding-001` on Vertex AI, 768 dimensions, task type semantic similarity.

**Test 1, judged blocks.** 20,796 blocks from 134 reports were embedded: the judged blocks plus 100
random other blocks per report. Three scores were computed per block:

- `description`: highest cosine similarity to twelve English descriptions of AI systems (for
  example "Software that learns from historical data and makes or prepares decisions on its own,
  without rules written by people.").
- `other_languages`: similarity to judged AI passages in the other three languages.
- `same_language`: similarity to judged AI passages of other reports in the same language.

To compare embeddings with the glossary, the threshold of a score was set so that the same share
of blocks judged "not about AI" passes as the glossaries hit today (9.2% over all four languages).

**Test 2, all paragraphs.** Every paragraph of at least 100 characters in every sample report was
embedded: 167,587 paragraphs from 130 reports (German 24,026, Spanish 55,941, French 76,458,
Polish 11,162). Score: `description`. The 1,500 highest-scoring paragraphs per language were
compared with the glossary and the judgments. The highest-scoring paragraphs that have no glossary
hit and had not been judged before were read: 30 German, 30 Spanish, 25 French.

Five Polish files that contain a structure dump instead of running text were left out.

## 4. Results

### 4.1 Judged blocks

`description` separated implicit passages from passages not about AI better than the other two
scores (AUC over all languages 0.774; `same_language` 0.711; `other_languages` 0.659). All numbers
below use `description`.

Implicit passages found, all four languages:

| Method | Share of "not about AI" passing | Implicit found (of 233) | Of the 41 without glossary hit |
|---|---|---|---|
| Glossaries | 9.2% | 192 (82%) | 0 |
| Embeddings | 5% | 66 (28%) | 13 |
| Embeddings | 9.2% | 95 (41%) | 18 |
| Embeddings | 20% | 141 (61%) | 27 |

Per language, at the pass rate of that language's glossary:

| Language | Glossary finds | Embeddings find | AUC |
|---|---|---|---|
| German | 26 of 28 | 13 of 28 | 0.826 |
| French | 75 of 75 | 29 of 75 | 0.734 |
| Spanish | 87 of 126 | 53 of 126 | 0.771 |
| Polish | 4 of 4 | 0 of 4 | 0.786 |

Of the random blocks, 1% to 4% pass at these thresholds.

### 4.2 All paragraphs

What the 100 highest-scoring paragraphs per language are:

| Language | explicit (judged) | implicit (judged) | not about AI (judged) | not judged, with glossary hit | not judged, no glossary hit |
|---|---|---|---|---|---|
| German | 27 | 5 | 14 | 0 | 54 |
| Spanish | 64 | 6 | 4 | 1 | 25 |
| French | 29 | 2 | 10 | 1 | 58 |
| Polish | 7 | 1 | 22 | 0 | 70 |

- Paragraphs that name AI rank high. The glossary finds these already.
- Of the 39 Spanish implicit passages without a glossary hit, 5 are among the 100 and 16 among the
  1,500 highest-scoring Spanish paragraphs.
- The 85 paragraphs read (highest-scoring, no glossary hit, not judged before) are general risk
  text: headings and lists on regulatory, compliance, operational and cyber risk. None of them
  describes AI. Three are borderline (a Spanish paragraph on model risk in the methodological
  sense, a Spanish paragraph on the introduction of IT tools, a French paragraph on intensive use
  of technology and data).

## 5. What worked and what did not

Worked:

- The score ranks paragraphs that name AI at the top, across four languages, with English
  descriptions only.
- It ranks implicit passages above average text (AUC 0.73 to 0.83 per language).

Did not work:

- At the same amount of unrelated text, embeddings find half as many implicit passages as the
  glossaries (95 against 192).
- They close the gap of the glossaries only at a pass rate of unrelated text that is about twice
  as high.
- On full reports, the additional paragraphs they bring up are risk text without a connection to
  AI.
- Comparing with judged passages (`same_language`, `other_languages`) was weaker than comparing
  with the descriptions.

Assumed cause, not verified: one of the twelve descriptions is about risks and regulation of
algorithmic systems and may pull up any risk paragraph. Only the highest similarity per paragraph
was stored, not the similarity per description, so this cannot be checked without a new run.

## 6. Limits

- The judgments come from a language model, not from human raters.
- The judged blocks were chosen with keyword probes. Implicit mentions without any probe word are
  not in the judged data; test 2 was the attempt to find such passages and found none in the 85
  paragraphs read.
- Small samples: 28 German and 4 Polish implicit passages. 39 of the 41 passages without a
  glossary hit are Spanish.
- The Polish paragraphs of test 2 and ranks below the first 25 to 30 candidates per language were
  not read.
- Not tested: a description set without the risk description, a classifier trained on the judged
  passages, other embedding models. There is no evidence that these would do better. The weaker
  result of the scores based on judged passages speaks against the trained classifier, and 233
  implicit passages are a small basis for training.
- Whether additional Spanish glossary terms would find the 39 missed Spanish passages was not
  checked.

## 7. Consequence for the pipeline

Implicit passages are counted but not classified, and the codebook codes them `none`. Finding more
of them would change the counts of context-only passages, not the classified results. Embeddings
would only have a purpose if the team decides that implicit passages are to be classified. That is
a codebook decision and was not part of this test.

## 8. Where the outputs are

In the bucket of the EU sample reports, folder `analysis/embeddings/`: `results.md` (all tables per
language and score), `results.json`, `scores.jsonl`, `judgments.jsonl`; subfolder `all_blocks/`:
`scores.jsonl` (score of every paragraph) and `top.jsonl` (the 1,500 highest-scoring paragraphs per
language). The reading of the 85 paragraphs is not stored there. The test scripts are not in the
repository, and nothing was built into the pipeline.
