"""The export stage: working directory -> the dataset layout kept in the bucket."""

import json
import tarfile

from airo import export


def doc(doc_id: str, filing_id: int, source_files: list[str], **meta) -> dict:
    return {"doc_id": doc_id, "filing_id": filing_id, "source_files": source_files, "company": "ACME", "cik": "0000000001",
            "form": "10-K", "fiscal_year": 2024, "ticker": "ACM", "exchange": "NYSE", "isic_class": "0721",
            "isic_division": "07", "filing_date": "2025-03-04", "n_words": 100, "sections": {}, **meta}


def passage(doc_id: str, blocks: tuple, mention: str, text: str, **extra) -> dict:
    matched = {"ai": ["artificial intelligence"]} if mention == "direct" else {"context": ["data center"]}
    return {"passage_id": f"{doc_id}:{blocks[0]}-{blocks[1]}", "doc_id": doc_id, "section": "Item 1A",
            "section_title": "Risk Factors", "heading": None, "blocks": list(blocks), "mention": mention,
            "matched": matched, "matched_text": {}, "text": text, **extra}


def label(pid: str, **fields) -> dict:
    base = {"passage_id": pid, "taxonomy_version": "0.9", "coders": ["gemini"], "ai_reference": "explicit",
            "frame": "risk_factor", "roles": ["risk"], "risk_types": ["cybersecurity"], "mit_subdomains": ["ai_system_security_vulnerabilities_attacks"],
            "adoption_stage": None, "business_functions": [], "governance_responses": [], "ai_kinds": ["unspecified"],
            "substantiveness": "specific", "disclosure_traits": ["hedging"], "entities": [], "evidence": ["AI"],
            "confidence": {"gemini": "high"}, "notes": [], "disputed": [], "needs_review": False}
    return {**base, **fields}


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_export_writes_the_bucket_layout(tmp_path):
    data = tmp_path / "work"
    # d1: one text carried by two filings (a 10-K and its ARS reprint); d2: one filing, context only.
    d1, d2 = doc("d1", 11, ["11.md", "12.md"]), doc("d2", 13, ["13.md"], company="BETA", cik="0000000002", filing_date="2025-04-01")
    for d in (d1, d2):
        (data / "docs" / d["doc_id"]).mkdir(parents=True)
        (data / "docs" / d["doc_id"] / "document.json").write_text(json.dumps(d), encoding="utf-8")
    write_jsonl(data / "docs" / "d1" / "passages.jsonl", [
        passage("d1", (0, 2), "direct", "We use artificial intelligence in underwriting."),
        passage("d1", (5, 6), "direct", "AI may fail."),
        passage("d1", (9, 9), "implicit", "Demand from data centers grew."),
    ])
    write_jsonl(data / "docs" / "d2" / "passages.jsonl", [passage("d2", (3, 4), "implicit", "Our data center is in Ohio.")])
    write_jsonl(data / "labels_final.jsonl", [
        label("d1:0-2", roles=["adoption", "risk"], adoption_stage="deployed", business_functions=["finance"],
              ai_kinds=["generative_llm"], entities=["OpenAI"], substantiveness="detailed"),
        label("d1:5-6", risk_types=["regulatory_legal"], mit_subdomains=["governance_failure"]),
    ])
    (data / "codebook.md").write_text("# codebook", encoding="utf-8")
    (data / "reports").mkdir()
    (data / "reports" / "d1.md").write_text("# report", encoding="utf-8")
    manifest = tmp_path / "manifest"
    manifest.mkdir()
    for name, fid, form, date in (("11.md", 11, "10-K", "2025-03-04"), ("12.md", 12, "ARS", "2025-03-20"), ("13.md", 13, "10-K", "2025-04-01")):
        (manifest / f"{fid}.json").write_text(json.dumps({"file": name, "filing_id": fid, "form": form, "filing_date": date,
                                                          "cik": "0000000001" if fid < 13 else "0000000002", "company": "ACME" if fid < 13 else "BETA",
                                                          "fiscal_year": 2024, "isic_class": "0721", "isic_division": "07", "ticker": "ACM", "exchange": "NYSE"}), encoding="utf-8")

    out = tmp_path / "us-test_V3"
    counts = export.export(data, out, run_id="us-test_V3", manifest=manifest, model="gemini-2.5-flash", log=lambda *_: None)

    assert counts == {"documents": 2, "chunks": 2, "labels": 2, "explicit": 2, "context": 2, "filings": 3}
    chunks = [json.loads(l) for l in (out / "chunks.jsonl").read_text().splitlines()]
    assert [c["chunk_id"] for c in chunks] == ["d1:0-2", "d1:5-6"]
    assert chunks[0] == {"chunk_id": "d1:0-2", "document_id": "11", "company_id": "0000000001", "company_name": "ACME",
                         "report_year": 2024, "report_sections": ["Item 1A Risk Factors"], "heading": None,
                         "chunk_text": "We use artificial intelligence in underwriting.", "chunk_word_len": 6,
                         "matched_keywords": ["artificial intelligence"], "blocks": [0, 2]}
    context = [json.loads(l) for l in (out / "context_passages.jsonl").read_text().splitlines()]
    assert [(c["chunk_id"], c["document_id"], c["matched_keywords"]) for c in context] == [("d1:9-9", "11", ["data center"]), ("d2:3-4", "13", ["data center"])]

    classified = [json.loads(l) for l in (out / "results" / "classified_chunks.jsonl").read_text().splitlines()]
    assert classified[0]["chunk_id"] == "d1:0-2" and classified[0]["mit_subdomains"] == ["ai_system_security_vulnerabilities_attacks"]
    assert "coders" not in classified[0] and classified[0]["taxonomy_version"] == "0.9"

    manifest_rows = json.loads((out / "documents_manifest.json").read_text())["documents"]
    assert [(r["document_id"], r["form"], r["text_id"]) for r in manifest_rows] == [("11", "10-K", "d1"), ("12", "ARS", "d1"), ("13", "10-K", "d2")]

    metrics = [json.loads(l) for l in (out / "results" / "filing_metrics.jsonl").read_text().splitlines()]
    m11, m12, m13 = metrics
    assert (m11["document_id"], m11["month"], m11["chunks"], m11["chunks_labelled"], m11["chunks_context"]) == ("11", "2025-03", 2, 2, 1)
    assert (m11["ai_mention"], m11["adoption"], m11["risk"], m11["harm"], m11["vendor"], m11["llm_adoption"]) == (True, True, True, False, True, True)
    assert (m11["cyber_risk"], m11["regulatory_risk"]) == (True, True)
    assert m11["mit_subdomains"] == ["ai_system_security_vulnerabilities_attacks", "governance_failure"]
    assert m11["business_functions"] == ["finance"] and m11["ai_kinds"] == ["generative_llm", "unspecified"]
    assert m11["substantiveness"] == {"boilerplate": 0, "generic": 0, "specific": 1, "detailed": 1, "quantified": 0}
    assert (m11["highest_substantiveness"], m11["trait_activation_rate"]) == ("detailed", 1.0)
    assert m12["document_id"] == "12" and m12["form"] == "ARS" and m12["month"] == "2025-03" and m12["ai_mention"] is True  # same text
    assert (m13["chunks"], m13["chunks_context"], m13["ai_mention"], m13["highest_substantiveness"]) == (0, 1, False, None)

    monthly = json.loads((out / "results" / "us-filing-metrics.json").read_text())
    assert (monthly["runId"], monthly["chunksTotal"], monthly["chunksClassified"], monthly["invalidRows"], monthly["filingsTotal"]) == ("us-test_V3", 2, 2, 0, 3)
    assert "gemini-2.5-flash" in monthly["source"] and "taxonomy v0.9" in monthly["source"]
    march, april = monthly["months"]
    assert (march["month"], march["filings"], march["aiMentionShare"], march["llmAdoptionShare"]) == ("2025-03", 2, 1.0, 1.0)
    assert (april["month"], april["filings"], april["aiMentionShare"]) == ("2025-04", 1, 0.0)
    assert march["highestSubstantivenessShare"]["detailed"] == 1.0

    assert (out / "results" / "codebook.md").read_text() == "# codebook" == (out / "results" / "classification_prompt.md").read_text()
    assert (out / "results" / "labels_final.jsonl").exists()
    with tarfile.open(out / "docs.tar.gz") as tar:
        assert "docs/d1/document.json" in tar.getnames()
    with tarfile.open(out / "reports.tar.gz") as tar:
        assert "reports/d1.md" in tar.getnames()
    readme = (out / "README.md").read_text()
    assert "run `us-test_V3`" in readme and "3 filings, 2 distinct texts" in readme and "| 2025-03 | 2 | 100% |" in readme


def test_export_without_manifest_uses_the_document_record(tmp_path):
    data = tmp_path / "work"
    d = doc("d9", 99, ["99.md"])
    (data / "docs" / "d9").mkdir(parents=True)
    (data / "docs" / "d9" / "document.json").write_text(json.dumps(d), encoding="utf-8")
    write_jsonl(data / "docs" / "d9" / "passages.jsonl", [passage("d9", (0, 1), "direct", "AI.")])
    counts = export.export(data, tmp_path / "out", run_id="r", log=lambda *_: None)
    rows = json.loads((tmp_path / "out" / "documents_manifest.json").read_text())["documents"]
    assert counts["labels"] == 0 and counts["chunks"] == 1
    assert rows == [{"document_id": "99", "company_id": "0000000001", "company_name": "ACME", "year": 2024, "market_segment": "NYSE",
                     "filing_date": "2025-03-04", "form": "10-K", "isic_division": "07", "isic_class": "0721", "ticker": "ACM", "text_id": "d9"}]
    monthly = json.loads((tmp_path / "out" / "results" / "us-filing-metrics.json").read_text())
    assert monthly["invalidRows"] == 1 and monthly["months"][0]["aiMentionShare"] == 0.0
