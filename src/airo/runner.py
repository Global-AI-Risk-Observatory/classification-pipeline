"""Stages 1+2 per file: filing -> docs/<doc_id>/, in parallel and resumable.

Every input file is an independent unit of work: parse it (ingest), attach its
manifest row, find the candidate passages (retrieve) and write the result to a
directory of its own. A file index records every file seen, so re-issuing the
same command after an interruption, or with new files added, processes only
what is missing.

    docs/<doc_id>/document.json    the document record
    docs/<doc_id>/blocks.jsonl     its ordered text blocks
    docs/<doc_id>/passages.jsonl   its candidate passages
    index/files.jsonl              one row per input file; appended, never rewritten

Files are keyed by the SHA-256 of their bytes in the index and by the hash of
their text in docs/: a second download of the same filing with different bytes
is parsed again, found to be a known document, and only adds its file name to
`source_files`.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from itertools import repeat
from pathlib import Path

from . import ingest, retrieve
from .glossary import load

_TMP = ".tmp-"  # prefix of a document directory that is still being written


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_doc(path: Path, doc: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_index(data: Path) -> dict[str, dict]:
    """The last index row per file hash; a truncated final line (killed run) is ignored."""
    path = data / "index" / "files.jsonl"
    rows: dict[str, dict] = {}
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rows[row["sha256"]] = row
    return rows


def _append_index(data: Path, row: dict) -> None:
    path = data / "index" / "files.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _add_source(doc_dir: Path, name: str) -> None:
    doc = json.loads((doc_dir / "document.json").read_text(encoding="utf-8"))
    if name not in doc["source_files"]:
        doc["source_files"] = sorted(doc["source_files"] + [name])
        _write_doc(doc_dir / "document.json", doc)


def process(
    path: Path,
    data: Path,
    meta: dict | None = None,
    context: int = 1,
    sha: str | None = None,
) -> dict:
    """One filing end to end: parse, attach `meta`, retrieve, write docs/<doc_id>/.

    Returns the index row. Never raises: a failure is recorded in the row's `error`.
    The directory is written under a temporary name and renamed when complete,
    so a reader never sees a half-written document and two workers that parse
    the same text at once end up with one directory.
    """
    path = Path(path)
    row = {"sha256": sha or sha256(path), "path": str(path), "started": _now()}
    try:
        doc, blocks = ingest.parse(path)
        doc.update(meta or {})
        row["doc_id"] = doc["doc_id"]
        out = data / "docs" / doc["doc_id"]
        if not out.exists():
            passages = retrieve.passages(doc, blocks, context=context, matcher=load(doc.get("isic_class")))
            tmp = out.with_name(f"{_TMP}{doc['doc_id']}-{os.getpid()}")
            tmp.mkdir(parents=True)
            _write_doc(tmp / "document.json", doc)
            _write_jsonl(tmp / "blocks.jsonl", blocks)
            _write_jsonl(tmp / "passages.jsonl", passages)
            try:
                tmp.rename(out)
                row["n_passages"] = len(passages)
            except OSError:  # another worker finished the same text first
                shutil.rmtree(tmp)
        if "n_passages" not in row:
            _add_source(out, path.name)
            row["duplicate"] = True
    except Exception as e:  # noqa: BLE001 - one bad file must not stop the run
        row["error"] = f"{type(e).__name__}: {e}"
    row["finished"] = _now()
    return row


def run(
    files: list[Path],
    data: Path,
    manifest: Path | None = None,
    workers: int | None = None,
    context: int = 1,
    retry_failed: bool = False,
    log=print,
) -> Counter:
    """Process the files not yet in the index, `workers` processes at a time.

    Returns the counters (done, duplicate, skipped, failed). A file whose bytes
    are already indexed is skipped, including a file that failed, unless
    `retry_failed` is set.
    """
    workers = workers or os.cpu_count() or 1
    meta = {}
    if manifest:
        # Provider metadata per file (ISIC class, country, filing id, ...).
        meta = {row.pop("file"): row for row in _read_jsonl(manifest)}
    known = read_index(data)
    for stale in (data / "docs").glob(f"{_TMP}*") if (data / "docs").exists() else []:
        shutil.rmtree(stale)  # left by a killed run; its file is not indexed and is redone

    counts: Counter = Counter()
    pool = ProcessPoolExecutor(workers) if workers > 1 else None
    t0 = time.perf_counter()
    try:
        hashes = pool.map(sha256, files, chunksize=64) if pool else map(sha256, files)
        todo = []
        for path, sha in zip(files, hashes):
            seen = known.get(sha)
            if seen and ("doc_id" in seen or not retry_failed):
                counts["skipped"] += 1
            else:
                todo.append((path, sha))
        log(f"{len(files)} file(s): {counts['skipped']} already indexed, {len(todo)} to process")

        paths = [p for p, _ in todo]
        args = (paths, repeat(data), [meta.get(p.name) for p in paths], repeat(context), [s for _, s in todo])
        rows = pool.map(process, *args) if pool else map(process, *args)
        for n, row in enumerate(rows, 1):
            _append_index(data, row)
            if "error" in row:
                counts["failed"] += 1
                log(f"{n}/{len(todo)}  failed  {row['path']}: {row['error']}")
            elif row.get("duplicate"):
                counts["duplicate"] += 1
                log(f"{n}/{len(todo)}  {row['doc_id']}  duplicate text, source added  {Path(row['path']).name}")
            else:
                counts["done"] += 1
                log(f"{n}/{len(todo)}  {row['doc_id']}  {row['n_passages']} candidate passage(s)  {Path(row['path']).name}")
    finally:
        if pool:
            pool.shutdown()
    elapsed = time.perf_counter() - t0
    rate = f", {len(todo) / elapsed:.2f} files/s" if todo and elapsed else ""
    log(
        f"{counts['done']} done, {counts['duplicate']} duplicate, {counts['skipped']} skipped, "
        f"{counts['failed']} failed in {elapsed:.1f}s{rate}"
    )
    return counts
