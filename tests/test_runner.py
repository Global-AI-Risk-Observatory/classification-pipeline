"""Tests for the per-file runner: one directory per document, append-only index, resume."""

from __future__ import annotations

import json
from pathlib import Path

from airo import cli, runner
from test_pipeline import filing, read_jsonl, write


def run(data: Path, *args: str) -> None:
    cli.main(["--data", str(data), "run", *args])


def snapshot(data: Path) -> dict[str, str]:
    """Every file under docs/, by relative path."""
    return {str(p.relative_to(data)): p.read_text(encoding="utf-8") for p in sorted((data / "docs").rglob("*")) if p.is_file()}


def test_run_writes_one_directory_per_document_and_one_index_row_per_file(tmp_path):
    filings = tmp_path / "filings"
    filings.mkdir()
    write(filings, "a.htm", filing())
    write(filings, "b.htm", filing(business="We mine lithium in Nevada."))
    data = tmp_path / "work"

    counts = runner.run([filings / "a.htm", filings / "b.htm"], data, workers=1, log=lambda *_: None)

    assert counts == {"done": 2}
    dirs = sorted(p.name for p in (data / "docs").iterdir())
    assert len(dirs) == 2
    for d in dirs:
        doc = json.loads((data / "docs" / d / "document.json").read_text(encoding="utf-8"))
        assert doc["doc_id"] == d
        assert len(read_jsonl(data / "docs" / d / "blocks.jsonl")) == doc["n_blocks"]
        assert all(p["doc_id"] == d for p in read_jsonl(data / "docs" / d / "passages.jsonl"))
    rows = read_jsonl(data / "index" / "files.jsonl")
    assert [Path(r["path"]).name for r in rows] == ["a.htm", "b.htm"]
    assert sorted(r["doc_id"] for r in rows) == dirs
    assert all({"sha256", "started", "finished", "n_passages"} <= set(r) for r in rows)


def test_run_attaches_manifest_row_to_the_document(tmp_path):
    write(tmp_path, "a.htm", filing())
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(json.dumps({"file": "a.htm", "isic_class": "0721", "country": "US"}) + "\n", encoding="utf-8")
    data = tmp_path / "work"

    run(data, str(tmp_path / "a.htm"), "--manifest", str(manifest), "--workers", "1")

    (doc_dir,) = list((data / "docs").iterdir())
    doc = json.loads((doc_dir / "document.json").read_text(encoding="utf-8"))
    assert (doc["isic_class"], doc["country"], doc["company"]) == ("0721", "US", "ACME URANIUM CORP")


def test_run_second_run_skips_every_indexed_file(tmp_path):
    filings = tmp_path / "filings"
    filings.mkdir()
    write(filings, "a.htm", filing())
    write(filings, "b.htm", filing(business="We mine lithium in Nevada."))
    data = tmp_path / "work"
    files = [filings / "a.htm", filings / "b.htm"]

    runner.run(files, data, workers=1, log=lambda *_: None)
    before = snapshot(data)
    index_before = (data / "index" / "files.jsonl").read_text(encoding="utf-8")

    counts = runner.run(files, data, workers=1, log=lambda *_: None)

    assert counts == {"skipped": 2}
    assert snapshot(data) == before
    assert (data / "index" / "files.jsonl").read_text(encoding="utf-8") == index_before

    # A file added later is the only one processed.
    write(filings, "c.htm", filing(business="We mine copper in Chile."))
    counts = runner.run(files + [filings / "c.htm"], data, workers=1, log=lambda *_: None)
    assert counts == {"skipped": 2, "done": 1}
    assert len(list((data / "docs").iterdir())) == 3
    assert len(read_jsonl(data / "index" / "files.jsonl")) == 3


def test_run_duplicate_text_collapses_into_one_directory_with_two_source_files(tmp_path):
    filings = tmp_path / "filings"
    filings.mkdir()
    write(filings, "download_a.htm", filing(token="aa11"))
    write(filings, "download_b.html", filing(token="bb22"))
    data = tmp_path / "work"

    counts = runner.run(sorted(filings.iterdir()), data, workers=1, log=lambda *_: None)

    assert counts == {"done": 1, "duplicate": 1}
    (doc_dir,) = list((data / "docs").iterdir())
    doc = json.loads((doc_dir / "document.json").read_text(encoding="utf-8"))
    assert doc["source_files"] == ["download_a.htm", "download_b.html"]
    rows = read_jsonl(data / "index" / "files.jsonl")
    assert [r["doc_id"] for r in rows] == [doc["doc_id"]] * 2
    assert [r.get("duplicate", False) for r in rows] == [False, True]

    # The same bytes seen again are skipped, not merged again.
    counts = runner.run(sorted(filings.iterdir()), data, workers=1, log=lambda *_: None)
    assert counts == {"skipped": 2}
    assert json.loads((doc_dir / "document.json").read_text(encoding="utf-8"))["source_files"] == doc["source_files"]


def test_run_records_a_corrupt_file_as_failed_and_continues(tmp_path):
    filings = tmp_path / "filings"
    filings.mkdir()
    write(filings, "a.htm", filing())
    (filings / "broken.htm").write_bytes(b"")
    write(filings, "c.htm", filing(business="We mine lithium in Nevada."))
    data = tmp_path / "work"
    files = sorted(filings.iterdir())

    counts = runner.run(files, data, workers=1, log=lambda *_: None)

    assert counts == {"done": 2, "failed": 1}
    rows = {Path(r["path"]).name: r for r in read_jsonl(data / "index" / "files.jsonl")}
    assert set(rows) == {"a.htm", "broken.htm", "c.htm"}
    assert "doc_id" not in rows["broken.htm"] and rows["broken.htm"]["error"].startswith("ParserError")
    assert len(list((data / "docs").iterdir())) == 2
    assert not list((data / "docs").glob(".tmp-*"))

    # A failed file is skipped like any indexed file, unless retried explicitly.
    assert runner.run(files, data, workers=1, log=lambda *_: None) == {"skipped": 3}
    assert runner.run(files, data, workers=1, retry_failed=True, log=lambda *_: None) == {"skipped": 2, "failed": 1}


def test_run_with_two_workers_gives_the_same_output_as_one(tmp_path):
    filings = tmp_path / "filings"
    filings.mkdir()
    write(filings, "a.htm", filing())
    write(filings, "b.htm", filing(business="We mine lithium in Nevada."))
    write(filings, "c.htm", filing(business="We mine copper in Chile."))
    write(filings, "a_again.htm", filing(token="bb22"))
    (filings / "broken.htm").write_bytes(b"")
    one, two = tmp_path / "one", tmp_path / "two"

    run(one, str(filings), "--workers", "1")
    run(two, str(filings), "--workers", "2")

    assert snapshot(two) == snapshot(one)
    rows_one = {r["sha256"]: (r.get("doc_id"), r.get("error")) for r in read_jsonl(one / "index" / "files.jsonl")}
    rows_two = {r["sha256"]: (r.get("doc_id"), r.get("error")) for r in read_jsonl(two / "index" / "files.jsonl")}
    assert rows_two == rows_one
    assert len(rows_one) == 5
