"""Flowchart of the US pipeline for readers outside the project: what happens to a filing at
each step, where the step runs, and the counts of run us-2025h1_V3 (docs/us-2025h1_V3-dataset.md).

    python docs/pipeline_flowchart.py  -> docs/pipeline-flowchart.png and .pdf
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

OUT = Path(__file__).resolve().parent / "pipeline-flowchart"

# One row per step: title, what happens (plain words), the run's numbers, where it runs.
STEPS = [
    ("1  Collect the filings",
     "US annual-report filings (10-K, ARS, 20-F and others) filed between January\n"
     "and June 2025, downloaded as text from the data provider.",
     "7,794 filings",
     "Data provider's API\n→ Google Cloud Storage"),
    ("2  Read each filing",
     "The filing is split into its paragraphs, headings and table rows,\n"
     "and the report sections (Risk Factors, Business, …) are recognised.",
     "7,794 filings read",
     "Pipeline software,\nno model"),
    ("3  Find the passages that may be about AI",
     "A list of 502 AI terms plus terms of the company's industry is searched in the text.\n"
     "Each hit and its neighbouring paragraphs form one passage.",
     "28,378 passages with an AI term\nfrom 5,368 filings",
     "Pipeline software,\nno model"),
    ("4  Classify each passage",
     "Gemini 2.5 Flash reads 40 passages per request together with the codebook\n"
     "(taxonomy v0.9: definitions and criteria for every label) and returns one label per passage:\n"
     "is it about AI; its frame; AI's role; risk types; MIT risk subdomains; adoption stage;\n"
     "business function; governance response; kind of AI; disclosure traits; substantiveness;\n"
     "one to three verbatim quotes as evidence.",
     "28,378 passages sent\nabout USD 34 of model calls",
     "Gemini on Google Cloud\n(Vertex AI)"),
    ("5  Check every label",
     "Each label is checked automatically: allowed values, field rules, and every quote\n"
     "must appear word for word in the passage. A failed label is asked again.",
     "27,908 labelled (98.3 %)\n24,765 about AI · 3,143 not about AI\n470 without label (1.7 %)",
     "Pipeline software,\nno model"),
    ("6  Add up per filing",
     "The passage labels are turned into statements about the filing:\n"
     "mentions AI, states an AI risk, reports its own use of AI, names a kind of AI, …",
     "4,924 filings mention AI (63 %)\n3,999 state an AI risk\n2,696 report their own use of AI\n2,870 have no AI statement",
     "Pipeline software,\nno model"),
    ("7  Publish the dataset",
     "Passages, labels, evidence quotes and filing metrics are written as one dataset\n"
     "that the analyses and the human validation read.",
     "39,579 evidence quotes\nhuman validation:\n290 passages, 7 raters",
     "Google Cloud Storage\n(run us-2025h1_V3)"),
]

SIDE = {
    2: ("Passages with context terms only\n(data centre, analytics, …): kept and counted,\n"
        "not classified: 64,643 passages.\nFilings without any candidate passage: 2,426."),
    4: ("Not about AI: the AI term was used in\nanother sense (a product name, an abbreviation).\n"
        "These 3,143 passages are dropped from the\nAI counts."),
}

W, H = 17.5, 21
fig, ax = plt.subplots(figsize=(W, H))
ax.set_xlim(0, W)
ax.set_ylim(0, H)
ax.axis("off")

ax.text(W / 2, H - 0.45, "How the US pipeline classifies AI statements in company filings", ha="center", va="top",
        fontsize=20, weight="bold")
ax.text(W / 2, H - 1.05, "Run us-2025h1_V3: 7,794 US filings, January to June 2025, taxonomy v0.9", ha="center",
        va="top", fontsize=13, color="#444444")
for x, label in ((0.4, "Step"), (9.4, "Counts of this run"), (13.6, "Where it runs")):
    ax.text(x, H - 1.75, label, fontsize=11, weight="bold", color="#666666", va="top")

main_x, main_w = 0.4, 8.7
count_x, count_w = 9.4, 3.9
where_x, where_w = 13.6, 3.5
top = H - 2.0
heights = [1.55, 1.55, 1.7, 2.5, 1.95, 1.95, 1.75]
gap = 0.55
SIDE_GAP = 1.75  # room for a side note under steps 3 and 5
y = top
boxes = []
for (title, what, counts, where), h in zip(STEPS, heights):
    y0 = y - h
    fill = "#dbe9f6" if title.startswith("4") else "#f2f2f2"
    edge = "#2b6cb0" if title.startswith("4") else "#999999"
    ax.add_patch(FancyBboxPatch((main_x, y0), main_w, h, boxstyle="round,pad=0.02,rounding_size=0.15",
                                facecolor=fill, edgecolor=edge, linewidth=1.6))
    ax.text(main_x + 0.2, y - 0.18, title, fontsize=13.5, weight="bold", va="top")
    ax.text(main_x + 0.2, y - 0.62, what, fontsize=10.5, va="top", linespacing=1.35)
    ax.add_patch(FancyBboxPatch((count_x, y0), count_w, h, boxstyle="round,pad=0.02,rounding_size=0.15",
                                facecolor="#fff7e0", edgecolor="#c9a227", linewidth=1.2))
    ax.text(count_x + count_w / 2, y - h / 2, counts, fontsize=10.2, ha="center", va="center", linespacing=1.45)
    ax.text(where_x + where_w / 2, y - h / 2, where, fontsize=10.5, ha="center", va="center", color="#333333",
            linespacing=1.4)
    boxes.append((y, y0))
    y = y0 - (SIDE_GAP if len(boxes) - 1 in SIDE else gap)

for (y_top, y_bot), (ny_top, _) in zip(boxes, boxes[1:]):
    ax.add_patch(FancyArrowPatch((main_x + main_w / 2, y_bot), (main_x + main_w / 2, ny_top),
                                 arrowstyle="-|>", mutation_scale=18, color="#555555", linewidth=1.4))

# Side notes for what leaves the main path at steps 3 and 5.
for idx, text in SIDE.items():
    y_top, y_bot = boxes[idx]
    ny = y_bot - SIDE_GAP / 2
    ax.annotate(text, xy=(main_x + main_w / 2, ny), xytext=(main_x + main_w / 2 + 0.6, ny), fontsize=10,
                ha="left", va="center", color="#444444", linespacing=1.3,
                bbox=dict(boxstyle="round,pad=0.4", facecolor="white", edgecolor="#bbbbbb"),
                arrowprops=dict(arrowstyle="-|>", color="#999999", mutation_scale=14))

fig.savefig(OUT.with_suffix(".png"), dpi=170, bbox_inches="tight")
fig.savefig(OUT.with_suffix(".pdf"), bbox_inches="tight")
print(f"wrote {OUT}.png and .pdf")
