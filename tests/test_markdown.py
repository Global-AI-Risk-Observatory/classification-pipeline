"""Tests for reading a filing from the data provider's Markdown (airo.ingest.parse_markdown)."""

from __future__ import annotations

from airo import ingest


def parse(tmp_path, text: str):
    path = tmp_path / "filing.md"
    path.write_text(text, encoding="utf-8")
    return ingest.parse(path)


COVER = """**UNITED STATES**

**FORM 10-K**

☒ ANNUAL REPORT PURSUANT TO SECTION 13 OR 15(d) OF THE SECURITIES EXCHANGE ACT OF 1934

For the fiscal year ended September 30 , 2025

ACME MINING CORP

"""


def test_paragraphs_headings_bullets_and_table_rows_become_blocks(tmp_path):
    doc, blocks = parse(tmp_path, COVER + """**Item 1. Business**

We mine *uranium* in Texas and **Wyoming**.

**Our Strategy**

• Grow output; and

• cut costs.

***Critical accounting estimates***

| Mine | **2025** |  | 2024 |
| --- | --- | --- | --- |
| Rosita | 100 |  | 90 |

# Appendix
""")

    body = [(b["kind"], b["text"]) for b in blocks if b["section"]]
    assert body == [
        ("heading", "Item 1. Business"),
        ("text", "We mine uranium in Texas and Wyoming."),
        ("heading", "Our Strategy"),
        ("text", "Grow output; and"),
        ("text", "cut costs."),
        ("heading", "Critical accounting estimates"),
        ("row", "Mine | 2025 | 2024"),
        ("row", "Rosita | 100 | 90"),
        ("heading", "Appendix"),
    ]
    assert [b["i"] for b in blocks] == list(range(len(blocks)))
    assert blocks[-2]["heading"] == "Critical accounting estimates"
    assert doc["n_blocks"] == len(blocks)
    assert doc["text_coverage"] > 0.95


def test_form_and_fiscal_period_come_from_the_cover_page(tmp_path):
    doc, _ = parse(tmp_path, COVER + "**Item 1. Business**\n\nWe mine uranium.\n")
    assert (doc["form"], doc["period_end"], doc["fiscal_year"]) == ("10-K", "2025-09-30", 2025)
    assert doc["company"] is None and doc["cik"] is None


def test_a_filing_without_a_cover_page_has_no_form_or_period(tmp_path):
    doc, _ = parse(tmp_path, "**Annual Report**\n\nWe mine uranium. For the fiscal year ended June 31, 2025 we grew.\n")
    assert (doc["form"], doc["period_end"], doc["fiscal_year"]) == (None, None, None)


def test_items_open_sections_and_contents_rows_do_not(tmp_path):
    doc, blocks = parse(tmp_path, COVER + """| Item 1. | Business | 3 |
| --- | --- | --- |
| Item 1A. | Risk Factors | 9 |

Table of Contents

**Item 1. Business**

We mine uranium. As described in Item 7 of this report, prices rose.

Table of Contents

**Item 1A. Risk Factors**

Prices may fall.
""")

    assert list(doc["sections"]) == ["Item 1", "Item 1A"]
    assert doc["sections"]["Item 1A"]["title"] == "Risk Factors"
    assert [b["kind"] for b in blocks if b["text"] == "Table of Contents"] == ["furniture", "furniture"]
    assert [b["section"] for b in blocks if b["text"].startswith("Prices may fall")] == ["Item 1A"]
    assert all(b["section"] is None for b in blocks if b["kind"] == "row")


def test_the_same_text_gives_the_same_document_id_whatever_the_file_is_called(tmp_path):
    text = COVER + "**Item 1. Business**\n\nWe mine uranium.\n"
    a = tmp_path / "1.md"
    b = tmp_path / "2.md"
    a.write_text(text, encoding="utf-8")
    b.write_text(text.replace("\n\n", "\n\n\n") + "\n", encoding="utf-8")
    assert ingest.parse(a)[0]["doc_id"] == ingest.parse(b)[0]["doc_id"]


def test_ticker_and_exchange_come_from_the_first_security_on_the_cover_page(tmp_path):
    table = """| Title of each class | Trading Symbol(s) | Name of each exchange on which registered |
| --- | --- | --- |
| Common Stock, $5.00 Par Value | BA | New York Stock Exchange |
| Depositary Shares | BA-PRA | New York Stock Exchange |

"""
    doc, _ = parse(tmp_path, COVER + table + "**Item 1. Business**\n\nWe mine uranium.\n")
    assert (doc["ticker"], doc["exchange"]) == ("BA", "New York Stock Exchange")
    assert ingest.cover_metadata(COVER + table) == {
        "company": None, "cik": None, "form": "10-K", "period_end": "2025-09-30", "fiscal_year": 2025,
        "ticker": "BA", "exchange": "New York Stock Exchange", "filer_category": None,
    }


def test_a_cover_page_without_listed_securities_has_no_ticker(tmp_path):
    table = """| Title of each class | Trading Symbol(s) | Name of each exchange on which registered |
| --- | --- | --- |
| None | N/A | N/A |

"""
    doc, _ = parse(tmp_path, COVER + table + "**Item 1. Business**\n\nWe mine uranium.\n")
    assert (doc["ticker"], doc["exchange"]) == (None, None)
