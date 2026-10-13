"""Stage 5: a run's working directory -> the dataset layout kept in the bucket.

    python -m airo --data <dir> export <out> --run-id us-2025h1_V3 [--manifest <raw>/manifest]

Writes, under `<out>` (a directory; in a Batch job the mounted bucket folder), the layout of
`gs://airo-pipeline-data/us-2025h1_V2/` so that runs can be compared file by file:

    chunks.jsonl                  one row per classified passage (direct mention), with its text
    context_passages.jsonl        one row per context passage (implicit mention), not classified
    documents_manifest.json       one row per filing, with `text_id` (filings with the same text share it)
    README.md                     generated description with the counts of this run
    docs.tar.gz, reports.tar.gz   the per-document files and the report views of the working directory
    results/classified_chunks.jsonl   one row per labelled passage: every label field
    results/filing_metrics.jsonl      one row per filing: counts, booleans, per-field tallies
    results/us-filing-metrics.json    shares per filing month
    results/codebook.md, classification_prompt.md, labels_final.jsonl, agreement.json,
    results/report_summary.jsonl, recall_check.json, and the coder's files from labels_in/

A document is one text; its `source_files` are the filings that carry that text. Rows of
`chunks.jsonl` use the document's own filing id; `documents_manifest.json` and
`filing_metrics.jsonl` have one row per filing, so a duplicate filing repeats its text's values.
"""

from __future__ import annotations

import json
import shutil
import tarfile
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Iterator

from .taxonomy import SUBSTANTIVENESS, TAXONOMY_VERSION

LABEL_FIELDS = (
    "ai_reference", "frame", "roles", "risk_types", "mit_subdomains", "adoption_stage", "business_functions",
    "governance_responses", "ai_kinds", "substantiveness", "disclosure_traits", "entities", "evidence",
    "confidence", "taxonomy_version", "needs_review", "disputed",
)
METRIC_BOOLEANS = ("ai_mention", "adoption", "risk", "harm", "vendor", "llm_adoption", "cyber_risk", "regulatory_risk")


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _write(path: Path, rows) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    return n


def _docs(data: Path) -> Iterator[tuple[dict, list[dict]]]:
    for d in sorted(p for p in (data / "docs").iterdir() if p.is_dir() and not p.name.startswith(".")):
        yield json.loads((d / "document.json").read_text(encoding="utf-8")), _read(d / "passages.jsonl")


def _manifest(manifest: Path | None) -> dict[str, dict]:
    """Provider metadata per file name, as `run` reads it; {} if no manifest is given."""
    if manifest is None:
        return {}
    rows = (
        [json.loads(f.read_text(encoding="utf-8")) for f in sorted(manifest.glob("*.json"))]
        if manifest.is_dir()
        else _read(manifest)
    )
    return {row["file"]: row for row in rows}


def _filing_id(name: str) -> str:
    return Path(name).stem


def _chunk(doc: dict, p: dict) -> dict:
    terms = [t for tier in ("ai", "context") for t in p["matched"].get(tier, [])]
    return {
        "chunk_id": p["passage_id"],
        "document_id": str(doc.get("filing_id") or _filing_id(doc["source_files"][0])),
        "company_id": doc.get("cik"),
        "company_name": doc.get("company"),
        "report_year": doc.get("fiscal_year"),
        "report_sections": [x for x in (" ".join(y for y in (p["section"], p["section_title"]) if y),) if x],
        "heading": p.get("heading"),
        "chunk_text": p["text"],
        "chunk_word_len": len(p["text"].split()),
        "matched_keywords": terms,
        "blocks": p["blocks"],
    }


def _filing_row(name: str, meta: dict, doc: dict, direct: list[dict], context: list[dict],
                labels: dict[str, dict]) -> dict:
    mine = [labels[p["passage_id"]] for p in direct if p["passage_id"] in labels]
    ai = [l for l in mine if l["ai_reference"] == "explicit"]

    def tally(field: str) -> dict:
        c = Counter()
        for l in ai:
            v = l.get(field)
            c.update(v if isinstance(v, list) else [v] if v else [])
        return dict(c.most_common())

    levels = {s: 0 for s in SUBSTANTIVENESS}
    for l in ai:
        if l.get("substantiveness") in levels:
            levels[l["substantiveness"]] += 1
    highest = next((s for s in reversed(list(SUBSTANTIVENESS)) if levels[s]), None)
    roles = tally("roles")
    filing_date = meta.get("filing_date") or doc.get("filing_date")
    return {
        # The filing is the file; its id comes from the manifest row or, without one, from the file name.
        "document_id": str(meta.get("filing_id") or _filing_id(name)),
        "text_id": doc["doc_id"],
        "company_id": meta.get("cik") or doc.get("cik"),
        "company_name": meta.get("company") or doc.get("company"),
        "filing_date": filing_date,
        "month": filing_date[:7] if filing_date else None,
        "form": meta.get("form") or doc.get("form"),
        "isic_division": meta.get("isic_division") or doc.get("isic_division"),
        "chunks": len(direct),
        "chunks_labelled": len(mine),
        "chunks_without_label": len(direct) - len(mine),
        "chunks_context": len(context),
        "ai_mention": bool(ai),
        "adoption": "adoption" in roles,
        "risk": "risk" in roles,
        "harm": "incident" in roles,
        "vendor": any(l.get("entities") for l in ai),
        "llm_adoption": any("adoption" in l["roles"] and "generative_llm" in l.get("ai_kinds", []) for l in ai),
        "cyber_risk": "cybersecurity" in tally("risk_types"),
        "regulatory_risk": "regulatory_legal" in tally("risk_types"),
        "risk_types": sorted(tally("risk_types")),
        "mit_subdomains": sorted(tally("mit_subdomains")),
        "roles": sorted(roles),
        "ai_kinds": sorted(tally("ai_kinds")),
        "business_functions": sorted(tally("business_functions")),
        "governance_responses": sorted(tally("governance_responses")),
        "substantiveness": levels,
        "highest_substantiveness": highest,
        "trait_activation_rate": round(sum(bool(l.get("disclosure_traits")) for l in ai) / len(ai), 3) if ai else None,
    }


def _months(rows: list[dict]) -> list[dict]:
    by_month: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_month[r["month"] or "unknown"].append(r)
    out = []
    for month in sorted(by_month):
        rs = by_month[month]
        n = len(rs)
        share = lambda key: round(sum(bool(r[key]) for r in rs) / n, 4)  # noqa: E731
        out.append({
            "month": month,
            "filingsTotal": n,
            "filings": n,
            "aiMentionShare": share("ai_mention"),
            "aiRiskShare": share("risk"),
            "llmAdoptionShare": share("llm_adoption"),
            "cyberRiskShare": share("cyber_risk"),
            "regulatoryRiskShare": share("regulatory_risk"),
            "adoptionShare": share("adoption"),
            "harmShare": share("harm"),
            "vendorShare": share("vendor"),
            "highestSubstantivenessShare": {
                s: round(sum(r["highest_substantiveness"] == s for r in rs) / n, 4) for s in SUBSTANTIVENESS
            },
        })
    return out


def _tar(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    with tarfile.open(dst, "w:gz") as tar:
        tar.add(src, arcname=src.name)
    return True


def _readme(run_id: str, model: str | None, counts: dict, months: list[dict]) -> str:
    rows = "\n".join(
        f"| {m['month']} | {m['filings']} | {m['aiMentionShare']:.0%} | {m['aiRiskShare']:.0%} | "
        f"{m['adoptionShare']:.0%} | {m['llmAdoptionShare']:.0%} |"
        for m in months
    )
    return "\n".join([
        f"# US AI disclosure dataset, run `{run_id}`",
        "",
        f"Produced with the `airo` pipeline (`src/airo`, taxonomy v{TAXONOMY_VERSION})"
        + (f" and `{model}`" if model else "") + f" on {date.today().isoformat()}.",
        "",
        "## Files",
        "",
        "```",
        f"{run_id}/",
        f"├── chunks.jsonl                  {counts['chunks']:,} classified passages (direct mentions), with text",
        f"├── context_passages.jsonl        {counts['context']:,} context passages (implicit mentions), not classified",
        f"├── documents_manifest.json       {counts['filings']:,} filings, {counts['documents']:,} distinct texts",
        "├── docs.tar.gz                   per-document files: document.json, blocks.jsonl, passages.jsonl",
        "├── reports.tar.gz                one report view per document",
        "└── results/",
        f"    ├── classified_chunks.jsonl   {counts['labels']:,} labelled passages, every label field",
        "    ├── filing_metrics.jsonl      one row per filing",
        "    ├── us-filing-metrics.json    shares per filing month",
        "    ├── codebook.md               the codebook used (classification_prompt.md is the same file)",
        "    ├── labels_final.jsonl, agreement.json, report_summary.jsonl, recall_check.json",
        "    └── the coder's label and run files",
        "```",
        "",
        "## Counts",
        "",
        f"- Filings: {counts['filings']:,}; distinct texts: {counts['documents']:,}",
        f"- Classified passages: {counts['chunks']:,}, of which labelled {counts['labels']:,}, "
        f"without label {counts['chunks'] - counts['labels']:,}; about AI (`explicit`): {counts['explicit']:,}",
        f"- Context passages (not classified): {counts['context']:,}",
        "",
        "| Month | Filings | AI mention | AI risk | Adoption | LLM adoption |",
        "|---|---|---|---|---|---|",
        rows,
        "",
        "## Definitions",
        "",
        "A passage is a task when it contains a glossary term of tier `ai`; a passage with `context` terms only is "
        "context and is not labelled. `ai_mention` is true for a filing with at least one passage labelled "
        "`explicit`. `adoption`, `risk`, `harm` (role `incident`), `vendor` (an entity named), `llm_adoption` "
        "(role `adoption` with kind `generative_llm`), `cyber_risk` and `regulatory_risk` follow the labels. "
        "Field definitions: `results/codebook.md`.",
        "",
    ])


def export(data: Path, out: Path, *, run_id: str, manifest: Path | None = None, model: str | None = None,
           log=print) -> dict:
    """Write the dataset layout of a run to `out`. Returns the counts."""
    out = Path(out)
    (out / "results").mkdir(parents=True, exist_ok=True)
    meta_by_file = _manifest(manifest)
    labels = {l["passage_id"]: l for l in _read(data / "labels_final.jsonl")}

    counts = Counter({k: 0 for k in ("filings", "documents", "chunks", "labels", "explicit", "context")})
    manifest_rows, metric_rows = [], []
    with open(out / "chunks.jsonl", "w", encoding="utf-8") as chunks, open(
        out / "context_passages.jsonl", "w", encoding="utf-8"
    ) as context_fh, open(out / "results" / "classified_chunks.jsonl", "w", encoding="utf-8") as classified:
        for doc, passages in _docs(data):
            counts["documents"] += 1
            direct = [p for p in passages if p["mention"] == "direct"]
            context = [p for p in passages if p["mention"] == "implicit"]
            for p in direct:
                chunks.write(json.dumps(_chunk(doc, p), ensure_ascii=False) + "\n")
                counts["chunks"] += 1
                if l := labels.get(p["passage_id"]):
                    row = {"chunk_id": p["passage_id"], **{k: l.get(k) for k in LABEL_FIELDS if k in l}}
                    classified.write(json.dumps(row, ensure_ascii=False) + "\n")
                    counts["labels"] += 1
                    counts["explicit"] += l["ai_reference"] == "explicit"
            for p in context:
                context_fh.write(json.dumps(_chunk(doc, p), ensure_ascii=False) + "\n")
                counts["context"] += 1
            for name in doc.get("source_files") or [f"{doc.get('filing_id')}.md"]:
                meta = meta_by_file.get(name, {})
                row = _filing_row(name, meta, doc, direct, context, labels)
                metric_rows.append(row)
                manifest_rows.append({
                    "document_id": row["document_id"],
                    "company_id": row["company_id"],
                    "company_name": row["company_name"],
                    "year": meta.get("fiscal_year", doc.get("fiscal_year")),
                    "market_segment": meta.get("exchange") or doc.get("exchange"),
                    "filing_date": row["filing_date"],
                    "form": row["form"],
                    "isic_division": row["isic_division"],
                    "isic_class": meta.get("isic_class") or doc.get("isic_class"),
                    "ticker": meta.get("ticker") or doc.get("ticker"),
                    "text_id": doc["doc_id"],
                })
                counts["filings"] += 1

    (out / "documents_manifest.json").write_text(
        json.dumps({"documents": manifest_rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    _write(out / "results" / "filing_metrics.jsonl", metric_rows)
    months = _months(metric_rows)
    (out / "results" / "us-filing-metrics.json").write_text(
        json.dumps({
            "source": f"airo pipeline (src/airo, taxonomy v{TAXONOMY_VERSION})" + (f" with {model}" if model else ""),
            "runId": run_id,
            "asOf": date.today().isoformat(),
            "chunksTotal": counts["chunks"],
            "chunksClassified": counts["labels"],
            "invalidRows": counts["chunks"] - counts["labels"],
            "filingsTotal": counts["filings"],
            "filingsCovered": counts["filings"],
            "months": months,
        }, indent=2) + "\n", encoding="utf-8",
    )
    for name in ("codebook.md", "labels_final.jsonl", "agreement.json", "report_summary.jsonl", "recall_check.json"):
        if (data / name).exists():
            shutil.copyfile(data / name, out / "results" / name)
    if (data / "codebook.md").exists():
        shutil.copyfile(data / "codebook.md", out / "results" / "classification_prompt.md")
    for f in sorted((data / "labels_in").glob("*")) if (data / "labels_in").exists() else []:
        shutil.copyfile(f, out / "results" / f.name)
    _tar(data / "docs", out / "docs.tar.gz")
    _tar(data / "reports", out / "reports.tar.gz")
    (out / "README.md").write_text(_readme(run_id, model, counts, months), encoding="utf-8")
    log(
        f"{run_id}: {counts['filings']} filing(s), {counts['documents']} text(s), {counts['chunks']} chunk(s) "
        f"({counts['labels']} labelled, {counts['explicit']} about AI), {counts['context']} context passage(s) -> {out}"
    )
    return dict(counts)
