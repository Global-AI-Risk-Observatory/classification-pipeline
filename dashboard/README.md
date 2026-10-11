# Dashboard

Next.js app with two pages over the US 10-K corpus (`gs://airo-pipeline-data/us-2025h1`, see `docs/us-2025h1-dataset.md`):

- `/timeline-beta`: scroll through AI and tech regulation events in the US, EU and China month by month; a sticky panel shows the state of the US filing corpus and its disclosure signals at that point in time.
- `/timeline`: the same events as a filterable table with a filings-per-month chart.

Data files in `data/`:

- `regulation-timeline.json`: 163 dated regulatory events with primary source and verification status, generated from `docs/regulation-timeline.md` with `npm run build:timeline`.
- `us-filings-by-month.json`: filings per month in the bucket (from the manifest `filing_date`).
- `us-filing-metrics.json`: share of filings per month with AI mention, AI risk, LLM adoption and other labels, from the classification run described in `docs/us-2025h1-dataset.md`.

Run locally:

```bash
cd dashboard
npm install
npm run dev
```

Then open http://localhost:3000/timeline-beta.
