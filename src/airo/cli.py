"""Command line: one sub-command per stage, files in, files out.

    python -m airo fetch <out> --types T      -> <out>/markdown/<filing id>.md, <out>/manifest/<filing id>.json
    python -m airo run <dir-or-files...>      -> docs/<doc_id>/{document.json,blocks.jsonl,passages.jsonl}, index/files.jsonl
    python -m airo tasks                      -> tasks.jsonl, codebook.md
    python -m airo accept <file> --coder X    -> labels/X.jsonl (validated)
    python -m airo adjudicate                 -> labels_final.jsonl, agreement.json
    python -m airo aggregate                  -> report_summary.jsonl, reports/<doc_id>.md, recall_check.json

Every stage reads only the previous stage's files, so stages can be re-run,
parallelised per document, or moved to another machine independently.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Iterator

from . import aggregate, classify, fetch, recall, runner, taxonomy


def _read(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _docs(data: Path) -> Iterator[tuple[dict, list[dict]]]:
    """(document record, its candidate passages) per directory under docs/, one at a time."""
    for d in sorted(p for p in (data / "docs").iterdir() if not p.name.startswith(".")):
        yield json.loads((d / "document.json").read_text(encoding="utf-8")), _read(d / "passages.jsonl")


def cmd_fetch(args) -> None:
    fetch.fetch(
        args.out, fetch.api_key(), args.types, form=args.form,
        since=args.since, until=args.until, limit=args.limit,
    )


def cmd_run(args) -> None:
    files = []
    for p in map(Path, args.inputs):
        files += sorted([*p.glob("*.md"), *p.glob("*.htm*")]) if p.is_dir() else [p]
    runner.run(
        files, args.data, manifest=args.manifest, workers=args.workers,
        context=args.context, retry_failed=args.retry_failed,
    )


def cmd_tasks(args) -> None:
    # Every candidate passage is a task, direct and implicit mentions alike.
    n: Counter = Counter()
    with open(args.data / "tasks.jsonl", "w", encoding="utf-8") as fh:
        for doc, passages in _docs(args.data):
            for row in classify.tasks([doc], passages):
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                n[row["mention"]] += 1
    (args.data / "codebook.md").write_text(taxonomy.codebook(), encoding="utf-8")
    print(
        f"{sum(n.values())} task(s): {n['direct']} direct and {n['implicit']} implicit mention(s), "
        f"codebook v{taxonomy.TAXONOMY_VERSION}"
    )


def cmd_accept(args) -> None:
    lines = Path(args.file).read_text(encoding="utf-8").splitlines()
    passages = [p for _, found in _docs(args.data) for p in found]
    labels, problems = classify.validate(lines, passages, args.coder)
    for p in problems:
        print("REJECTED:", p)
    if problems and not args.partial:
        sys.exit(f"{len(problems)} problem(s); nothing written. Fix the file or pass --partial.")
    _write(args.data / "labels" / f"{args.coder}.jsonl", labels)
    print(f"{len(labels)} label(s) accepted for coder {args.coder}")


def cmd_adjudicate(args) -> None:
    by_coder = {p.stem: _read(p) for p in sorted((args.data / "labels").glob("*.jsonl"))}
    final, agreement = classify.adjudicate(by_coder)
    _write(args.data / "labels_final.jsonl", final)
    (args.data / "agreement.json").write_text(json.dumps(agreement, indent=2), encoding="utf-8")
    print(json.dumps(agreement, indent=2))


def cmd_aggregate(args) -> None:
    labels = _read(args.data / "labels_final.jsonl")
    summaries = []
    for d, mine in _docs(args.data):
        summary = aggregate.summarise(d, mine, labels)
        summaries.append(summary)
        out = args.data / "reports" / f"{d['doc_id']}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(aggregate.render(d, mine, labels, summary), encoding="utf-8")
        print(out)
    _write(args.data / "report_summary.jsonl", summaries)
    check = recall.total(summaries)
    (args.data / "recall_check.json").write_text(json.dumps(check, indent=2), encoding="utf-8")
    print(
        f"recall check: {check['blocks_outside_passages']} block(s) in {check['documents_affected']} of "
        f"{check['documents']} document(s) match a reference pattern outside every passage"
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="airo", description=__doc__.split("\n")[0])
    parser.add_argument("--data", type=Path, default=Path("data"), help="working directory (default: data)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("fetch", help="store the Markdown of US companies' filings from the data provider, each filing once")
    p.add_argument("out", help="gs://bucket[/prefix] or a directory; receives markdown/ and manifest/")
    p.add_argument("--types", required=True, help="the provider's filing type codes, comma-separated (e.g. 10-K,10-Q)")
    p.add_argument("--form", help="only filings submitted as this form (e.g. 10-K, which leaves out 10-K/A, 20-F, ARS)")
    p.add_argument("--since", help="released on or after this date (YYYY-MM-DD)")
    p.add_argument("--until", help="released on or before this date (YYYY-MM-DD)")
    p.add_argument("--limit", type=int, default=10, help="filings to store at most in this call (default 10)")
    p.set_defaults(func=cmd_fetch)
    p = sub.add_parser("run", help="parse filings and find candidate passages, one directory per document")
    p.add_argument("inputs", nargs="+", help="Markdown or HTML files, or directories containing them")
    p.add_argument("--manifest", type=Path, help="one row per file (file, isic_class, ...): a JSONL file or a directory of JSON files")
    p.add_argument("--workers", type=int, help="processes (default: all CPUs)")
    p.add_argument("--context", type=int, default=1, help="neighbouring blocks on each side of a hit")
    p.add_argument("--retry-failed", action="store_true", help="process files whose last attempt failed again")
    p.set_defaults(func=cmd_run)
    sub.add_parser("tasks").set_defaults(func=cmd_tasks)
    p = sub.add_parser("accept")
    p.add_argument("file")
    p.add_argument("--coder", required=True)
    p.add_argument("--partial", action="store_true", help="write the valid labels even if some were rejected")
    p.set_defaults(func=cmd_accept)
    sub.add_parser("adjudicate").set_defaults(func=cmd_adjudicate)
    sub.add_parser("aggregate").set_defaults(func=cmd_aggregate)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
