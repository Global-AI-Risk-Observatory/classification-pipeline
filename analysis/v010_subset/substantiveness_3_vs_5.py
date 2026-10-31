"""Substantiveness: three levels against five, each with anchor examples in the codebook.

Round 4 of the v0.10 subset test (2026-10-31; docs/changes.md entry 20). The 290 passages of the
us-2025h1_V3 human validation are labelled with three variants of the v0.10 codebook that differ
only in the `substantiveness` section:

    five_examples   the five levels of v0.9/v0.10, plus one anchor passage per level
    three_examples  the three levels the policy team asked for (generic, company_specific,
                    detailed), plus the same anchor passages, each given its three-level value
    three_plain     the three levels without examples (to tell the effect of the levels from
                    the effect of the examples)

The anchors are passages of the test set on which the raters agreed (both raters where there were
two); they are left out of the scoring of every variant, including the reference runs, so the test
is not scored on its own examples. The anchor texts are read from the task file, not kept here.
Round 3 (five levels, no examples) is the reference for the five-level variant.

The raters coded five levels. The three-level variants are scored against the raters' levels mapped
to three (boilerplate, generic -> generic; specific -> company_specific; detailed, quantified ->
detailed), and the five-level variants both on five levels and mapped the same way, so that every
column of the three-level comparison is like for like.

    python analysis/v010_subset/substantiveness_3_vs_5.py codebooks --tasks <tasks.jsonl> --out <dir>
    python analysis/v010_subset/substantiveness_3_vs_5.py run --tasks <tasks.jsonl> --codebooks <dir> --out <dir> \\
        --model gemini-2.5-flash --project <project> --location us-central1
    python analysis/v010_subset/substantiveness_3_vs_5.py compare --run gs://airo-pipeline-data/us-2025h1_V3 \\
        --labels five_examples=<path> three_examples=<path> three_plain=<path> five_plain=<path> --out <agreement.md>

`run` calls the Gemini coder in-process so that the three-level variants can be validated and
requested with a three-level schema without changing the pipeline's own `Label`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Literal, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "human_validation"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from airo import taxonomy as tx  # noqa: E402
from subset_test import FIELDS_MULTI, FIELDS_SINGLE, agreement, read_jsonl, write_text  # noqa: E402

# The anchors: (passage id, first words, last words) of the stretch shown; the raters' five-level value.
ANCHORS: dict[str, tuple[str, str, str]] = {
    "boilerplate": ("df4be75bd6b98d7c:383-385", "reviewing and discussing policies", "artificial intelligence; and"),
    "generic": ("49fc17764e09581c:663-664", "Regulators are also increasing", "results of operations."),
    "specific": ("b6683c4854ff66c4:1525-1527", "Docsumo Pte. Ltd.", "for all periods presented."),
    "detailed": ("607554886c8f7bce:660-662", "Advanced Cyber Threats", "security protocols in place."),
    "quantified": ("438acfa1617fbb15:1694-1696", "GreenBox was established", "automated case handling systems."),
}
FIVE_TO_THREE = {"boilerplate": "generic", "generic": "generic", "specific": "company_specific",
                 "detailed": "detailed", "quantified": "detailed"}

# The three levels as the policy team asked for them, written in the taxonomy's form (definition,
# criteria that must all hold), with the same content as the five levels joined two by two.
SUBSTANTIVENESS_THREE: dict[str, tx.Definition] = {
    "generic": (
        "Level 1. A statement that could appear unchanged in another company's report: at most an area "
        "the AI statement applies to is named, nothing specific to the company.",
        (
            "no concrete system, use case, counterparty or mechanism of effect of this company is named",
            "no concrete measure, responsibility, figure, date or realised outcome is given for the AI statement",
        ),
    ),
    "company_specific": (
        "Level 2. Names a concrete system, use case, counterparty or mechanism of this company, without "
        "saying what the company does about it.",
        (
            "a named or described system, product, use case, counterparty or mechanism of effect that "
            "belongs to this company's own situation",
            "no concrete measure, responsibility or commitment is stated for it",
        ),
    ),
    "detailed": (
        "Level 3. As level 2, and states what the company does or has decided about it, or gives "
        "verifiable particulars.",
        (
            "meets the first criterion of `company_specific`",
            "states a measure, mitigation, assigned responsibility, policy or commitment of the company, "
            "or gives a verifiable figure, amount, date, share or realised outcome about the AI statement",
        ),
    ),
}

Substantiveness3 = Literal["generic", "company_specific", "detailed"]


# --------------------------------------------------------------------------
# codebooks
# --------------------------------------------------------------------------


def anchor_texts(tasks_path: str) -> dict[str, str]:
    by_id = {t["passage_id"]: t for t in read_jsonl(tasks_path)}
    out = {}
    for level, (pid, first, last) in ANCHORS.items():
        text = " ".join(by_id[pid]["text"].split())
        start, end = text.index(first), text.index(last) + len(last)
        out[level] = text[start:end]
    return out


def examples_block(anchors: dict[str, str], levels: Literal[3, 5]) -> str:
    lines = ["Examples, one passage per level, as rated by trained coders (the level is for the AI statement in the passage):", ""]
    for level5, text in anchors.items():
        level = level5 if levels == 5 else FIVE_TO_THREE[level5]
        lines.append(f"- `{level}`: \"{text}\"")
    return "\n".join(lines) + "\n"


def section_bounds(codebook: str) -> tuple[int, int]:
    start = codebook.index("### How substantive is the AI statement? (`substantiveness`)")
    end = codebook.index("### Other fields", start)
    return start, end


def three_level_table() -> str:
    return tx._table(
        "How substantive is the AI statement?", "substantiveness",
        "Exactly one value when `ai_reference` is `explicit`; `null` when it is `none`. "
        "Three levels, ordered from 1 (`generic`) to 3 (`detailed`). Judged on the AI-related "
        "statements of the passage as a whole: give the highest level whose criteria they meet. "
        "Particulars that are not about AI (the company's revenue, the date of the report) do not "
        "count.",
        SUBSTANTIVENESS_THREE,
    )


def codebooks(anchors: dict[str, str]) -> dict[str, str]:
    base = tx.codebook()
    start, end = section_bounds(base)
    five_section = base[start:end]
    return {
        "five_examples": base[:start] + five_section + examples_block(anchors, 5) + "\n" + base[end:],
        "three_examples": base[:start] + three_level_table() + "\n" + examples_block(anchors, 3) + "\n" + base[end:],
        "three_plain": base[:start] + three_level_table() + "\n" + base[end:],
    }


def cmd_codebooks(args) -> None:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, text in codebooks(anchor_texts(args.tasks)).items():
        (out / f"codebook_{name}.md").write_text(text, encoding="utf-8")
        print(f"codebooks: {name}: {len(text):,} characters -> {out / f'codebook_{name}.md'}")


# --------------------------------------------------------------------------
# run: the Gemini coder in-process, with a three-level schema where the codebook has three levels
# --------------------------------------------------------------------------


def three_level_schema():
    from pydantic import BaseModel

    class Label3(tx.Label):
        substantiveness: Optional[Substantiveness3] = None  # type: ignore[assignment]

    class Labels3(BaseModel):
        labels: list[Label3]

    return Label3, Labels3


def run_variant(name: str, tasks: str, codebook: str, out: str, *, model: str, project: str, location: str,
                batch_size: int) -> None:
    from airo import classify
    from airo.coders import gemini

    original = (classify.Label, gemini.Label, gemini.Labels, gemini.request_config.__defaults__)
    if name.startswith("three"):
        label3, labels3 = three_level_schema()
        classify.Label, gemini.Label, gemini.Labels = label3, label3, labels3
        gemini.request_config.__defaults__ = (None, gemini.MAX_OUTPUT_TOKENS, label3)
    try:
        gemini.main(["--tasks", tasks, "--codebook", codebook, "--out", out, "--model", model,
                     "--thinking-budget", "0", "--batch-size", str(batch_size), "--project", project, "--location", location])
    finally:
        classify.Label, gemini.Label, gemini.Labels, gemini.request_config.__defaults__ = original


def cmd_run(args) -> None:
    for name in args.variants:
        run_variant(name, args.tasks, str(Path(args.codebooks) / f"codebook_{name}.md"), str(Path(args.out) / f"{name}.jsonl"),
                    model=args.model, project=args.project, location=args.location, batch_size=args.batch_size)


# --------------------------------------------------------------------------
# compare
# --------------------------------------------------------------------------


def to_three(label: dict) -> dict:
    s = label.get("substantiveness")
    return {**label, "substantiveness": FIVE_TO_THREE.get(s, s)}


def cmd_compare(args) -> None:
    run = args.run.rstrip("/")
    anchors = {pid for pid, _, _ in ANCHORS.values()}
    humans = [l for k in range(1, 8) for l in read_jsonl(f"{run}/human_validation/labels/human_{k}.jsonl")
              if l["passage_id"] not in anchors]
    sample_ids = {s["passage_id"] for s in read_jsonl(f"{run}/human_validation/sample.jsonl")} - anchors
    variants: dict[str, dict[str, dict]] = {
        "V3 model (v0.9)": {l["passage_id"]: l for l in read_jsonl(f"{run}/results/labels_final.jsonl") if l["passage_id"] in sample_ids},
    }
    for spec in args.labels:
        name, path = spec.split("=", 1)
        variants[name] = {l["passage_id"]: l for l in read_jsonl(path) if l["passage_id"] in sample_ids}
    five = {n for n, labels in variants.items()
            if any(l.get("substantiveness") in ("boilerplate", "specific", "quantified") for l in labels.values())}

    def row(unit: str, table: dict) -> str:
        v = table.get(unit)
        return "" if v is None or v[0] is None else f"{v[0]:.2f} ({v[1]:.2f})"

    on_five = {n: agreement(humans, labels) for n, labels in variants.items() if n in five}
    humans3 = [to_three(h) for h in humans]
    on_three = {n: agreement(humans3, {p: to_three(l) for p, l in labels.items()}) for n, labels in variants.items()}
    names = list(variants)
    lines = [
        "# Substantiveness: three levels against five, with and without examples (round 4)",
        "",
        f"{len(humans)} human ratings on {len(sample_ids)} passages (the {len(anchors)} anchor passages shown as examples are left out). "
        "Cohen's kappa (share identical in brackets), human against model.",
        "",
        "## Substantiveness, on the raters' five levels (variants with five levels only)",
        "",
        "| Variant | kappa (agree) |", "|---|---|",
        *[f"| {n} | {row('substantiveness', on_five[n])} |" for n in names if n in five],
        "",
        "## Substantiveness, raters and models mapped to three levels",
        "",
        "| Variant | kappa (agree) |", "|---|---|",
        *[f"| {n} | {row('substantiveness', on_three[n])} |" for n in names],
        "",
        "## The other fields did not change (roles as exact set, mapped table)",
        "",
        "| Variant | roles (exact set) | ai_reference | disclosure_traits (exact set) |", "|---|---|---|---|",
        *[f"| {n} | {row('roles (exact set)', on_three[n])} | {row('ai_reference', on_three[n])} | {row('disclosure_traits (exact set)', on_three[n])} |" for n in names],
        "",
        "## Distribution per variant (passages about AI)",
        "",
    ]
    for n, labels in variants.items():
        dist = Counter(l.get("substantiveness") for l in labels.values() if l.get("ai_reference") == "explicit")
        lines.append(f"- {n}: {len(labels)} labelled; {dict(dist.most_common())}")
    rater_dist = Counter(h.get("substantiveness") for h in humans if h.get("ai_reference") == "explicit")
    lines += ["", f"Raters: {dict(rater_dist.most_common())}", ""]
    text = "\n".join(lines) + "\n"
    write_text(args.out, text)
    print(text)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("codebooks")
    c.add_argument("--tasks", required=True, help="tasks.jsonl of the subset (local path or gs://)")
    c.add_argument("--out", required=True, help="directory for codebook_<variant>.md")
    c.set_defaults(func=cmd_codebooks)
    r = sub.add_parser("run")
    r.add_argument("--tasks", required=True)
    r.add_argument("--codebooks", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--variants", nargs="+", default=["five_examples", "three_examples", "three_plain"])
    r.add_argument("--model", default="gemini-2.5-flash")
    r.add_argument("--project", required=True)
    r.add_argument("--location", default="us-central1")
    r.add_argument("--batch-size", type=int, default=40)
    r.set_defaults(func=cmd_run)
    m = sub.add_parser("compare")
    m.add_argument("--run", required=True)
    m.add_argument("--labels", nargs="+", required=True, help="name=path, one per variant")
    m.add_argument("--out", required=True)
    m.set_defaults(func=cmd_compare)
    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
