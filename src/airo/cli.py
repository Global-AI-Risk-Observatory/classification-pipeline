"""Command line: one sub-command per stage, files in, files out.

    python -m airo fetch <out> --types T      -> <out>/markdown/<filing id>.md, <out>/manifest/<filing id>.json
    python -m airo run <dir-or-files...>      -> docs/<doc_id>/{document.json,blocks.jsonl,passages.jsonl}, index/files.jsonl
    python -m airo tasks                      -> tasks.jsonl, copies.jsonl, near_held.jsonl, codebook.md, hints.jsonl
    python -m airo accept <file> --coder X    -> labels/X.jsonl (validated)
    python -m airo adjudicate                 -> labels_final.jsonl, agreement.json
    python -m airo near                       -> copies.jsonl (near copies added), tasks_near.jsonl
    (the coder on tasks_near.jsonl, `accept --tasks tasks_near.jsonl --append`, `adjudicate` again)
    python -m airo aggregate                  -> report_summary.jsonl, reports/<doc_id>.md, recall_check.json
    python -m airo export <out> --run-id X    -> the dataset layout of the run under <out>

Every stage reads only the previous stage's files, so stages can be re-run,
parallelised per document, or moved to another machine independently.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterator

from . import aggregate, classify, export, fetch, recall, runner, taxonomy


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


def _direct(passages: list[dict]) -> list[dict]:
    """The passages that are classified. Implicit mentions are context and get no label."""
    return [p for p in passages if p["mention"] == "direct"]


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
    hints = 0
    entries = []
    with open(args.data / "hints.jsonl", "w", encoding="utf-8") as hh:
        for doc, passages in _docs(args.data):
            entries += [(row, doc) for row in classify.tasks([doc], _direct(passages))]
            # Implicit mentions are context, not AI statements: handed on with
            # their text for a reader, never classified.
            for row in classify.tasks([doc], [p for p in passages if p["mention"] == "implicit"]):
                hh.write(json.dumps(row, ensure_ascii=False) + "\n")
                hints += 1
    # The same text within a company and release year is labelled once; the copies take its label in `adjudicate`.
    tasks, copies = classify.collapse_copies(entries)
    # A near copy waits until its original is labelled; `near` then decides whether it takes that label.
    kept = {t["passage_id"] for t in tasks}
    tasks, held = classify.hold_near([(t, d) for t, d in entries if t["passage_id"] in kept])
    _write(args.data / "tasks.jsonl", tasks)
    _write(args.data / "copies.jsonl", copies)
    _write(args.data / "near_held.jsonl", held)
    (args.data / "tasks_near.jsonl").unlink(missing_ok=True)
    (args.data / "codebook.md").write_text(taxonomy.codebook(), encoding="utf-8")
    print(
        f"{len(tasks)} task(s) from direct mentions, {len(copies)} copies take the label of another task, "
        f"{len(held)} near copies held for `near`, {hints} context passage(s) as hints, codebook v{taxonomy.TAXONOMY_VERSION}"
    )


def cmd_accept(args) -> None:
    lines = Path(args.file).read_text(encoding="utf-8").splitlines()
    # Labels are checked against the tasks the coder was given (tasks.jsonl, or tasks_near.jsonl in the second round).
    passages = _read(args.tasks or args.data / "tasks.jsonl")
    labels, problems = classify.validate(lines, passages, args.coder)
    for p in problems:
        print("REJECTED:", p)
    if problems and not args.partial:
        sys.exit(f"{len(problems)} problem(s); nothing written. Fix the file or pass --partial.")
    out = args.data / "labels" / f"{args.coder}.jsonl"
    if args.append and out.exists():
        new = {l["passage_id"] for l in labels}
        labels = [l for l in _read(out) if l["passage_id"] not in new] + labels
    _write(out, labels)
    print(f"{len(labels)} label(s) for coder {args.coder}")


def cmd_near(args) -> None:
    held = _read(args.data / "near_held.jsonl") if (args.data / "near_held.jsonl").exists() else []
    copies, tasks = classify.release_near(held, _read(args.data / "labels_final.jsonl"))
    exact = [c for c in _read(args.data / "copies.jsonl") if c.get("match") != "near"] if (args.data / "copies.jsonl").exists() else []
    _write(args.data / "copies.jsonl", exact + copies)
    _write(args.data / "tasks_near.jsonl", tasks)
    print(
        f"{len(held)} near copies held: {len(copies)} take the label of their original, "
        f"{len(tasks)} are tasks in tasks_near.jsonl (an evidence quote of the original is not in their text, or the original has no label)"
    )


def cmd_adjudicate(args) -> None:
    by_coder = {p.stem: _read(p) for p in sorted((args.data / "labels").glob("*.jsonl"))}
    final, agreement = classify.adjudicate(by_coder)
    copies = _read(args.data / "copies.jsonl") if (args.data / "copies.jsonl").exists() else []
    if copies:
        wanted = {c["passage_id"] for c in copies}
        text_by_id = {p["passage_id"]: p["text"] for _, found in _docs(args.data) for p in found if p["passage_id"] in wanted}
        final, agreement["n_copies_labelled"] = classify.copy_labels(final, copies, text_by_id)
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


def cmd_export(args) -> None:
    export.export(args.data, Path(args.out), run_id=args.run_id, manifest=args.manifest, model=args.model)


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
    p.add_argument("--tasks", type=Path, help="the task file the coder labelled (default: tasks.jsonl in the working directory)")
    p.add_argument("--append", action="store_true", help="add to the coder's accepted labels instead of replacing them")
    p.set_defaults(func=cmd_accept)
    sub.add_parser("adjudicate").set_defaults(func=cmd_adjudicate)
    sub.add_parser("near", help="after `adjudicate`: near copies take their original's label or become tasks_near.jsonl").set_defaults(func=cmd_near)
    sub.add_parser("aggregate").set_defaults(func=cmd_aggregate)
    p = sub.add_parser("export", help="write the dataset layout of the run (as kept in the bucket) to a directory")
    p.add_argument("out", help="target directory, e.g. the mounted bucket folder of the run")
    p.add_argument("--run-id", required=True, help="name of the run, e.g. us-2025h1_V3")
    p.add_argument("--manifest", type=Path, help="the provider manifest given to `run`, for one row per filing")
    p.add_argument("--model", help="model name written into the README and the metrics file")
    p.set_defaults(func=cmd_export)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
