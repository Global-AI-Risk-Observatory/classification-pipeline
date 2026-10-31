"""Subset test of a taxonomy version on the 290 passages of the us-2025h1_V3 human validation.

The passages the seven raters coded under v0.9 are labelled again with the current codebook, and
each label file is scored against the raters (Cohen's kappa per field) next to the V3 model's own
labels. Everything is read from and written to the bucket; nothing of the data stays on the machine.
The test rounds of 2026-10-31 that led to v0.10 are documented in docs/changes.md, entries 18 and 19.

    # 1. the tasks of the 290 passages and the current codebook, into a bucket folder of your choice
    python analysis/v010_subset/subset_test.py tasks --run gs://airo-pipeline-data/us-2025h1_V3 --out gs://<bucket>/<folder>

    # 2. label them (the coder reads and writes local paths; copy the folder with gsutil cp, delete it after the upload)
    python -m airo.coders.gemini --tasks tasks.jsonl --codebook codebook.md --out labels.jsonl \
        --model gemini-2.5-flash --thinking-budget 0 --batch-size 40 --project <project> --location us-central1

    # 3. agreement of each label file with the seven raters, next to the V3 model's, per field
    python analysis/v010_subset/subset_test.py compare --run gs://airo-pipeline-data/us-2025h1_V3 \
        --labels v010=gs://<bucket>/<folder>/labels.jsonl --out gs://<bucket>/<folder>/agreement.md

Single-valued fields are compared as they are; a label file whose values differ from the raters'
(as the count-based substantiveness of the tested, not adopted, design did) needs a mapping of its own.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "human_validation"))

from airo import taxonomy as tx  # noqa: E402
from human_validation import kappa  # noqa: E402

FIELDS_SINGLE = ("ai_reference", "adoption_stage", "substantiveness")  # `frame` is gone in v0.10
FIELDS_MULTI = ("roles", "risk_types", "mit_subdomains", "business_functions", "governance_responses", "disclosure_traits")


# --------------------------------------------------------------------------
# bucket I/O through gsutil, so no extra dependency and the same credentials as the rest
# --------------------------------------------------------------------------


def read_text(path: str) -> str:
    if path.startswith("gs://"):
        return subprocess.run(["gsutil", "cat", path], capture_output=True, check=True).stdout.decode("utf-8")
    return Path(path).read_text(encoding="utf-8")


def read_jsonl(path: str) -> list[dict]:
    return [json.loads(line) for line in read_text(path).splitlines() if line.strip()]


def write_text(path: str, text: str) -> None:
    if path.startswith("gs://"):
        subprocess.run(["gsutil", "cp", "-", path], input=text.encode("utf-8"), check=True)
    else:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(text, encoding="utf-8")


def write_jsonl(path: str, rows: list[dict]) -> None:
    write_text(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


# --------------------------------------------------------------------------
# tasks
# --------------------------------------------------------------------------


def build_tasks(run: str) -> list[dict]:
    """The 290 sample passages as tasks, in the shape `airo tasks` writes.

    Context comes from the run's `chunks.jsonl` (text, section, heading, matched terms) and
    `documents_manifest.json` (form, fiscal year); `sample.jsonl` gives the passage ids and the
    stratum. The run's chunk rows carry the matched terms as one flat list, so the task shows them
    under `ai`; the live run showed `ai` and `context` terms apart. That is the one difference
    from the tasks of the run.
    """
    sample = read_jsonl(f"{run}/human_validation/sample.jsonl")
    wanted = {s["passage_id"]: s for s in sample}
    docs = {d["document_id"]: d for d in json.loads(read_text(f"{run}/documents_manifest.json"))["documents"]}
    tasks = []
    # chunks.jsonl is about 100 MB: streamed, one line at a time.
    proc = subprocess.Popen(["gsutil", "cat", f"{run}/chunks.jsonl"], stdout=subprocess.PIPE)
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.decode("utf-8")
        if not line.strip():
            continue
        c = json.loads(line)
        s = wanted.get(c["chunk_id"])
        if s is None:
            continue
        d = docs.get(c["document_id"], {})
        tasks.append({
            "passage_id": c["chunk_id"],
            "company": c.get("company_name"),
            "form": d.get("form") or s.get("form"),
            "fiscal_year": c.get("report_year") or d.get("year"),
            "section": " ".join(c.get("report_sections") or []) or None,
            "heading": c.get("heading"),
            "matched_terms": {"ai": c.get("matched_keywords") or []},
            "text": c["chunk_text"],
            "stratum": s.get("stratum"),
        })
        wanted.pop(c["chunk_id"])
        if not wanted:
            proc.stdout.close()
            proc.terminate()
            break
    proc.wait()
    if wanted:
        print(f"tasks: {len(wanted)} sample passages not found in chunks.jsonl: {sorted(wanted)[:5]} ...", file=sys.stderr)
    tasks.sort(key=lambda t: t["passage_id"])
    return tasks


def cmd_tasks(args) -> None:
    tasks = build_tasks(args.run)
    out = args.out.rstrip("/")
    write_jsonl(f"{out}/tasks.jsonl", tasks)
    write_text(f"{out}/codebook.md", tx.codebook())
    strata = Counter(t["stratum"] for t in tasks)
    print(f"tasks: {len(tasks)} passages -> {out}/tasks.jsonl; strata {dict(strata)}; codebook v{tx.TAXONOMY_VERSION} beside it")


# --------------------------------------------------------------------------
# compare
# --------------------------------------------------------------------------


def units(a: dict, b: dict) -> dict[str, tuple[str, str]]:
    out = {}
    for f in FIELDS_SINGLE:
        out[f] = (str(a.get(f) or ""), str(b.get(f) or ""))
    for f in FIELDS_MULTI:
        out[f + " (exact set)"] = (",".join(sorted(a.get(f) or [])), ",".join(sorted(b.get(f) or [])))
        values = {
            "roles": tx.ROLES, "risk_types": tx.RISK_TYPES, "mit_subdomains": tx.MIT_SUBDOMAINS,
            "business_functions": tx.BUSINESS_FUNCTIONS, "governance_responses": tx.GOVERNANCE_RESPONSES,
            "disclosure_traits": tx.DISCLOSURE_TRAITS,
        }[f]
        for v in values:
            out[f"{f}:{v}"] = (str(v in (a.get(f) or [])), str(v in (b.get(f) or [])))
    return out


def agreement(humans: list[dict], model: dict[str, dict]) -> dict[str, tuple[float | None, float | None, int]]:
    """Per unit: (kappa, share identical, n pairs) of every human rating against the model's label of the same passage."""
    pairs: dict[str, list[tuple[str, str]]] = {}
    for h in humans:
        m = model.get(h["passage_id"])
        if m is None:
            continue
        for unit, pair in units(h, m).items():
            pairs.setdefault(unit, []).append(pair)
    return {u: (kappa(p), sum(a == b for a, b in p) / len(p) if p else None, len(p)) for u, p in pairs.items()}


def cmd_compare(args) -> None:
    run = args.run.rstrip("/")
    humans = [l for k in range(1, 8) for l in read_jsonl(f"{run}/human_validation/labels/human_{k}.jsonl")]
    sample_ids = {s["passage_id"] for s in read_jsonl(f"{run}/human_validation/sample.jsonl")}
    variants: dict[str, dict[str, dict]] = {
        # The run's final labels (one coder, passed through adjudication); `results/gemini.jsonl` holds the first pass only.
        "V3 model (v0.9)": {l["passage_id"]: l for l in read_jsonl(f"{run}/results/labels_final.jsonl") if l["passage_id"] in sample_ids},
    }
    for spec in args.labels:
        name, path = spec.split("=", 1)
        variants[name] = {l["passage_id"]: l for l in read_jsonl(path)}
    tables = {name: agreement(humans, labels) for name, labels in variants.items()}
    order = [u for u in tables["V3 model (v0.9)"]]
    for t in tables.values():
        order += [u for u in t if u not in order]

    def cell(t, u, i):
        v = t.get(u)
        if v is None or v[i] is None:
            return ""
        return f"{v[i]:.2f}"

    names = list(tables)
    lines = [
        f"# Taxonomy v{tx.TAXONOMY_VERSION} subset test: agreement with the seven raters of us-2025h1_V3",
        "",
        f"{len(humans)} human ratings on {len(sample_ids)} passages. Cohen's kappa and share of identical ratings, human against model, "
        "per field; list fields as exact set and per value. The raters coded under taxonomy v0.9.",
        "",
        "| Field | " + " | ".join(f"{n} kappa | {n} agree | n" for n in names) + " |",
        "|---|" + "---|" * (3 * len(names)),
    ]
    for u in order:
        lines.append(f"| {u} | " + " | ".join(
            f"{cell(tables[n], u, 0)} | {cell(tables[n], u, 1)} | {tables[n][u][2] if u in tables[n] else ''}" for n in names) + " |")
    lines += ["", "## Labelled passages per variant", ""]
    for n, labels in variants.items():
        lines.append(f"- {n}: {len(labels)} of {len(sample_ids)}")
    lines += ["", "## Substantiveness distribution per variant (passages about AI)", ""]
    for n, labels in variants.items():
        dist = Counter(l.get("substantiveness") for l in labels.values() if l.get("ai_reference") == "explicit")
        lines.append(f"- {n}: {dict(dist.most_common())}")
    text = "\n".join(lines) + "\n"
    write_text(args.out, text)
    print(text)


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="command", required=True)
    t = sub.add_parser("tasks", help="write the tasks of the 290 sample passages and the current codebook to --out")
    t.add_argument("--run", required=True, help="the run folder, e.g. gs://airo-pipeline-data/us-2025h1_V3")
    t.add_argument("--out", required=True, help="bucket folder (or directory) to write tasks.jsonl and the codebooks to")
    t.set_defaults(func=cmd_tasks)
    c = sub.add_parser("compare", help="agreement of label files with the seven raters, next to the V3 model")
    c.add_argument("--run", required=True)
    c.add_argument("--labels", nargs="+", required=True, help="name=path of a labels file (gs:// or local), one or more")
    c.add_argument("--out", required=True, help="where to write agreement.md (gs:// or local)")
    c.set_defaults(func=cmd_compare)
    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
