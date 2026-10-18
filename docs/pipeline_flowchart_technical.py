"""Technical flowchart of the US pipeline: per stage the command, the code that runs, what it
reads and writes, and where it runs. Counts are those of run us-2025h1_V3.

    python docs/pipeline_flowchart_technical.py  -> docs/pipeline-flowchart-technical.png and .pdf
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

OUT = Path(__file__).resolve().parent / "pipeline-flowchart-technical"

# (stage title, command, code, reads -> writes, where, highlight)
STAGES = [
    ("0  Fetch the filings",
     "python -m airo fetch gs://airo-filings-raw\n  --types 10-K --since 2025-01-01 --until 2025-06-30",
     "src/airo/fetch.py\nprovider API, personal key in .env.local\n(X-API-Key; never in the cloud)",
     "reads: the data provider's listing and filings\nwrites: raw bucket airo-filings-raw/\n  markdown/<filing id>.md, manifest/<filing id>.json,\n  companies/us.jsonl",
     "Team member's machine\n→ Cloud Storage", False),
    ("1+2  Parse and find candidate passages",
     "python -m airo --data <dir> run <raw>/markdown\n  --manifest <raw>/manifest [--workers N]",
     "src/airo/runner.py  one file per worker, resumable (index/files.jsonl)\n"
     "  → ingest.py   Markdown or HTML → document record + text blocks;\n"
     "                sections from the Form 10-K \"Item\" headings\n"
     "  → retrieve.py glossary hits ± 1 block, same section; overlapping\n"
     "                windows merge; ai-tier term → chunk, else context passage\n"
     "  → recall.py   66 UK keyword patterns counted outside every passage\n"
     "glossary.py builds one regex from glossaries/core.json (502 terms,\n"
     "tiers ai / context, 14 groups) + glossaries/isic/<division>.json\n"
     "(87 files, division and class terms); container: AIRO_GLOSSARIES",
     "reads: markdown/*.md, manifest/*.json\nwrites: docs/<doc_id>/document.json,\n  blocks.jsonl, passages.jsonl; index/files.jsonl\n"
     "V3: 7,794 filings → 28,378 chunks (5,368 filings),\n64,643 context passages, 2,426 filings without a hit",
     "Workstation or\nCloud Batch container\n(no model)", False),
    ("3a  Tasks and codebook",
     "python -m airo --data <dir> tasks",
     "src/airo/cli.py cmd_tasks → classify.tasks()\nsrc/airo/taxonomy.py renders the codebook: every field, value,\ndefinition and criteria; TAXONOMY_VERSION = \"0.9\"",
     "reads: docs/*/document.json, docs/*/passages.jsonl\nwrites: tasks.jsonl (one task per chunk: passage, company,\n  form, section, heading, matched terms), hints.jsonl, codebook.md",
     "Workstation or container\n(no model)", False),
    ("3b  Classification with Gemini",
     "python -m airo.coders.gemini --tasks tasks.jsonl\n  --codebook codebook.md --out labels_in/gemini.jsonl\n  --model gemini-2.5-flash --thinking-budget 0\n  --project <project> --location us-central1 --workers 16",
     "src/airo/coders/gemini.py\n"
     "  make_client()         genai.Client(vertexai=True, project, location)\n"
     "  build_batch_prompt()  codebook once + 40 tasks (BATCH_SIZE)\n"
     "  code_batch()          client.models.generate_content(): temperature 0,\n"
     "                        JSON bound to response_schema = taxonomy.Labels,\n"
     "                        thinking off, 5 retries on transient errors\n"
     "  _check()              classify.validate(): field rules, quotes verbatim\n"
     "  repair_prompt()       failed label asked again with the reason;\n"
     "  repair()              or deferred and re-asked in a later batch pass",
     "reads: tasks.jsonl, codebook.md\nwrites: labels_in/gemini.jsonl, gemini.jsonl.run.json\n  (tasks, failures, tokens, cost), *.deferred.jsonl\n"
     "V3: three passes; 49.9 M input, 7.6 M output tokens,\nabout USD 34; 470 chunks (1.7 %) stay without label",
     "Workstation or container\n→ Vertex AI, us-central1\n(the only model call)", True),
    ("3c  Accept and adjudicate",
     "python -m airo --data <dir> accept labels_in/gemini.jsonl\n  --coder gemini --partial\npython -m airo --data <dir> adjudicate",
     "src/airo/classify.py\n  validate()    pydantic Label schema (taxonomy.py), the field rules\n                (risk_types only with role risk, …), evidence verbatim\n  adjudicate()  majority per field across coders; one coder on V3,\n                so no vote; disputed fields flagged needs_review",
     "reads: labels_in/*.jsonl, docs/*/passages.jsonl\nwrites: labels/gemini.jsonl, labels_final.jsonl, agreement.json\n"
     "V3: 27,908 labelled: 24,765 explicit, 3,143 none",
     "Workstation or container\n(no model)", False),
    ("4  Aggregate",
     "python -m airo --data <dir> aggregate",
     "src/airo/aggregate.py  one summary row per filing (ai_mention,\nai_risk, ai_adoption, llm_adoption, cyber_risk, regulatory_risk,\nhighest substantiveness, entities) and a Markdown report per filing",
     "reads: docs/*/document.json, passages.jsonl, labels_final.jsonl\nwrites: report_summary.jsonl, reports/<doc_id>.md, recall_check.json\n"
     "V3: 4,924 filings mention AI, 3,999 AI risk, 2,696 adoption",
     "Workstation or container\n(no model)", False),
    ("5  Export the run",
     "python -m airo --data <dir> export\n  gs://airo-pipeline-data/us-2025h1_V3\n  --run-id us-2025h1_V3 --manifest <raw>/manifest",
     "src/airo/export.py  the dataset layout kept in the bucket",
     "reads: the working directory\nwrites: pipeline-data bucket us-2025h1_V3/\n  chunks.jsonl, context_passages.jsonl, documents_manifest.json,\n  results/classified_chunks.jsonl, filing_metrics.jsonl, codebook.md,\n  labels_final.jsonl, agreement.json, recall_check.json, gemini.jsonl,\n  docs.tar.gz, reports.tar.gz, README.md",
     "→ Cloud Storage\nairo-pipeline-data", False),
    ("6  Consumers of the dataset",
     "analysis/functional_fragmentation/functional_fragmentation.py\nanalysis/human_validation/human_validation.py\ndashboard/",
     "read results/classified_chunks.jsonl, chunks.jsonl and\ndocuments_manifest.json from the bucket; model calls of the\nanalyses go through Vertex AI in the caller's own project",
     "writes: analysis/<name>/results/ (counts, plots, kappa);\nquotes and passage text stay in work/ (git-ignored) or the bucket",
     "Workstation\n→ Vertex AI", False),
]

INFRA = ("Deployment: Dockerfile (python 3.12, src/ + glossaries/, ENTRYPOINT python -m airo) → cloudbuild.yaml: Cloud Build trigger on every push to main runs the tests "
         "and pushes the image to Artifact Registry → a Cloud Batch job (cloud/*.job.json) mounts both buckets and runs stages 1 to 4 in order. "
         "us-2025h1_V3 was run on a workstation with the buckets as source and target; the Batch run is pending. Settings: cloud/config.env; taxonomy and codebook: src/airo/taxonomy.py; "
         "stage docs: README.md \"Stages and files\", docs/changes.md; dataset: docs/us-2025h1_V3-dataset.md.")

W, H = 26, 26.5
fig, ax = plt.subplots(figsize=(W, H))
ax.set_xlim(0, W)
ax.set_ylim(0, H)
ax.axis("off")
ax.text(W / 2, H - 0.4, "The US pipeline, stage by stage: command, code, files, place", ha="center", va="top", fontsize=22, weight="bold")
ax.text(W / 2, H - 1.05, "Repository classification-pipeline; counts of run us-2025h1_V3 (taxonomy v0.9)", ha="center", va="top", fontsize=13, color="#444444")

cols = [("Stage and command", 0.3, 6.4), ("Code that runs", 6.9, 7.9), ("Reads → writes", 15.0, 8.0), ("Where", 23.2, 2.5)]
for label, x, w in cols:
    ax.text(x, H - 1.8, label, fontsize=12, weight="bold", color="#666666", va="top")

heights = [1.7, 3.5, 1.7, 3.5, 2.2, 1.7, 2.4, 1.9]
gap = 0.45
y = H - 2.1
rows = []
for (title, cmd, code, files, where, hl), h in zip(STAGES, heights):
    y0 = y - h
    for i, (_label, x, w) in enumerate(cols):
        fill = ("#dbe9f6" if hl else "#f4f4f4") if i == 0 else ("#eef4fb" if hl else "#fbfbfb")
        edge = "#2b6cb0" if hl else "#aaaaaa"
        ax.add_patch(FancyBboxPatch((x, y0), w, h, boxstyle="round,pad=0.02,rounding_size=0.12", facecolor=fill, edgecolor=edge, linewidth=1.3))
    ax.text(cols[0][1] + 0.15, y - 0.15, title, fontsize=13, weight="bold", va="top")
    ax.text(cols[0][1] + 0.15, y - 0.62, cmd, fontsize=9.3, va="top", family="monospace", linespacing=1.35)
    ax.text(cols[1][1] + 0.15, y - 0.15, code, fontsize=9.3, va="top", family="monospace", linespacing=1.35)
    ax.text(cols[2][1] + 0.15, y - 0.15, files, fontsize=9.3, va="top", family="monospace", linespacing=1.35)
    ax.text(cols[3][1] + cols[3][2] / 2, y - h / 2, where, fontsize=10.5, ha="center", va="center", linespacing=1.4)
    rows.append((y, y0))
    y = y0 - gap
for (_, y_bot), (ny_top, _) in zip(rows, rows[1:]):
    ax.add_patch(FancyArrowPatch((cols[0][1] + 1.2, y_bot), (cols[0][1] + 1.2, ny_top), arrowstyle="-|>", mutation_scale=16, color="#555555", linewidth=1.3))

import textwrap  # noqa: E402

ax.text(0.3, y - 0.1, "\n".join(textwrap.wrap(INFRA, 210)), fontsize=9.8, va="top", color="#333333", linespacing=1.4,
        bbox=dict(boxstyle="round,pad=0.5", facecolor="#fff7e0", edgecolor="#c9a227"))

fig.savefig(OUT.with_suffix(".png"), dpi=150, bbox_inches="tight")
fig.savefig(OUT.with_suffix(".pdf"), bbox_inches="tight")
print(f"wrote {OUT}.png and .pdf")
