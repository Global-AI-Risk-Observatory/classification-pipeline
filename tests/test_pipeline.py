"""Tests for the airo pipeline.

Synthetic fixtures only: every filing is a small HTML string written to
tmp_path. No network, no dependence on data/ or on any real filing.

Tests marked xfail(strict=True) document confirmed bugs in src/airo. They state
the intended behaviour; when the bug is fixed the test passes, strict xfail then
fails the run, and the marker has to be removed.
"""

from __future__ import annotations

import json
import re
from typing import get_args

import pytest
from pydantic import ValidationError

from airo import aggregate, classify, cli, glossary, ingest, retrieve, taxonomy
from airo.taxonomy import Label

# --------------------------------------------------------------------------
# Fixtures: a small inline-XBRL "10-K"
# --------------------------------------------------------------------------


def table(*rows: tuple[str, ...]) -> str:
    """An HTML table with every cell on its own line."""
    body = "\n".join(
        "<tr>\n" + "\n".join(f"<td>{cell}</td>" for cell in row) + "\n</tr>" for row in rows
    )
    return f"<table>\n{body}\n</table>"


def email(token: str) -> str:
    """A Cloudflare-obfuscated e-mail address; `token` changes on every download."""
    return (
        '<a href="/cdn-cgi/l/email-protection" class="__cf_email__" '
        f'data-cfemail="{token}">[email&#160;protected]</a>'
    )


TOC = table(
    ("Item 1.", "Business", "3"),
    ("Item 1A.", "Risk Factors", "9"),
    ("Item 7.", "Management's Discussion and Analysis", "20"),
)
BETWEEN_TOC_AND_PART_ONE = "This note on forward-looking statements follows the contents table."


def filing(token: str = "aa11", business: str = "We mine uranium in Texas and Wyoming.") -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL">
<head>
<title>acme-10k</title>
<style>p {{ margin: 0 }}</style>
</head>
<body>
<div style="display:none">
<ix:header>
<ix:hidden>
<ix:nonNumeric name="dei:EntityCentralIndexKey" contextRef="c1">0000123456</ix:nonNumeric>
<ix:nonNumeric name="dei:DocumentFiscalYearFocus" contextRef="c1">2026</ix:nonNumeric>
</ix:hidden>
</ix:header>
</div>
<ix:header>
<ix:resources>HEADERONLYTOKEN</ix:resources>
</ix:header>
<p style="color: red; display: none">HIDDENTOKEN in a hidden paragraph</p>
<script>var SCRIPTTOKEN = 1;</script>
<p><b>FORM <ix:nonNumeric name="dei:DocumentType" contextRef="c1">10-K</ix:nonNumeric></b></p>
<p>For the fiscal year ended <ix:nonNumeric name="dei:DocumentPeriodEndDate" contextRef="c1">July 31, 2026</ix:nonNumeric></p>
<p><ix:nonNumeric name="dei:EntityRegistrantName" contextRef="c1">ACME URANIUM CORP</ix:nonNumeric></p>
<p>Investor contact: {email(token)}</p>
{TOC}
<p>{BETWEEN_TOC_AND_PART_ONE}</p>
<p><b>Item 1. Business</b></p>
<p>{business}</p>
<p><b>Customers</b></p>
<p>Utilities buy our product under long-term contracts.</p>
<p>Demand for electricity from AI data centers is growing.</p>
<p><b>Item 1A. Risk Factors</b></p>
<p>Our business is subject to many risks.</p>
<p><b><i>Demand for nuclear power may not develop</i></b></p>
<p>Demand for <b>nuclear power</b> may not grow as we expect.</p>
{table(("Mine", "Tonnes"), ("<p>Palangana</p>", "<p>1,200</p>"))}
<p><b>Item 7. Management's Discussion and Analysis</b></p>
<p>Revenue rose.<br/>Costs fell.</p>
<p>Our backup data center is in Austin.</p>
<script data-cfasync="false" src="/cdn-cgi/scripts/email-decode.min.js"></script>
</body>
</html>
"""


def write(tmp_path, name: str, html: str):
    path = tmp_path / name
    path.write_text(html, encoding="utf-8")
    return path


def parse_html(tmp_path, html: str, name: str = "filing.htm"):
    return ingest.parse(write(tmp_path, name, html))


def parse_body(tmp_path, body: str):
    return parse_html(tmp_path, f"<html><body>\n{body}\n</body></html>")


def block_with(blocks: list[dict], text: str) -> dict:
    """The single block whose text starts with `text`."""
    found = [b for b in blocks if b["text"].startswith(text)]
    assert len(found) == 1, f"expected one block starting with {text!r}, found {len(found)}"
    return found[0]


def texts(blocks: list[dict]) -> list[str]:
    return [b["text"] for b in blocks]


# --------------------------------------------------------------------------
# ingest: document identity
# --------------------------------------------------------------------------


def test_ingest_collapses_files_that_differ_only_in_cloudflare_email_token(tmp_path):
    a = write(tmp_path, "download_a.htm", filing(token="aa11"))
    b = write(tmp_path, "download_b.htm", filing(token="bb22"))
    assert a.read_bytes() != b.read_bytes()

    docs, blocks = ingest.ingest([b, a])

    assert len(docs) == 1
    assert docs[0]["source_files"] == ["download_a.htm", "download_b.htm"]
    assert list(blocks) == [docs[0]["doc_id"]]
    assert len(blocks[docs[0]["doc_id"]]) == docs[0]["n_blocks"]


def test_ingest_gives_different_text_a_different_doc_id(tmp_path):
    a = write(tmp_path, "a.htm", filing())
    b = write(tmp_path, "b.htm", filing(business="We mine copper in Arizona."))

    docs, blocks = ingest.ingest([a, b])

    assert len(docs) == 2
    assert docs[0]["doc_id"] != docs[1]["doc_id"]
    assert [d["source_files"] for d in docs] == [["a.htm"], ["b.htm"]]
    assert set(blocks) == {d["doc_id"] for d in docs}


def test_ingest_doc_id_ignores_whitespace_between_tags(tmp_path):
    pretty = filing()
    minified = re.sub(r">\s+<", "><", pretty)
    assert minified != pretty

    doc_p, blocks_p = parse_html(tmp_path, pretty, "pretty.htm")
    doc_m, blocks_m = parse_html(tmp_path, minified, "minified.htm")

    assert texts(blocks_m) == texts(blocks_p)
    assert doc_m["doc_id"] == doc_p["doc_id"]


# --------------------------------------------------------------------------
# ingest: inline-XBRL metadata and invisible content
# --------------------------------------------------------------------------


def test_ingest_reads_inline_xbrl_metadata(tmp_path):
    doc, _ = parse_html(tmp_path, filing())

    assert doc["company"] == "ACME URANIUM CORP"
    assert doc["form"] == "10-K"
    assert doc["period_end"] == "2026-07-31"
    assert doc["fiscal_year"] == 2026
    assert isinstance(doc["fiscal_year"], int)
    assert doc["cik"] == "0000123456"  # read from the hidden ix:header
    assert doc["ticker"] is None  # fact absent from the filing


def test_ingest_drops_ix_header_and_hidden_elements_from_blocks(tmp_path):
    _, blocks = parse_html(tmp_path, filing())
    full_text = "\n".join(texts(blocks))

    assert "HEADERONLYTOKEN" not in full_text  # <ix:header> outside any hidden div
    assert "HIDDENTOKEN" not in full_text  # style="... display: none"
    assert "0000123456" not in full_text  # ix:header inside a display:none div
    assert "SCRIPTTOKEN" not in full_text
    assert "ACME URANIUM CORP" in full_text  # visible facts stay


# --------------------------------------------------------------------------
# ingest: sections and headings
# --------------------------------------------------------------------------


def test_ingest_item_headings_set_section_for_following_blocks(tmp_path):
    doc, blocks = parse_html(tmp_path, filing())

    assert block_with(blocks, "ACME URANIUM CORP")["section"] is None  # cover page
    item_1 = block_with(blocks, "Item 1. Business")
    assert (item_1["kind"], item_1["section"]) == ("heading", "Item 1")
    assert block_with(blocks, "We mine uranium")["section"] == "Item 1"
    assert block_with(blocks, "Demand for electricity")["section"] == "Item 1"
    assert block_with(blocks, "Item 1A. Risk Factors")["section"] == "Item 1A"
    assert block_with(blocks, "Our business is subject")["section"] == "Item 1A"
    assert block_with(blocks, "Palangana")["section"] == "Item 1A"
    assert block_with(blocks, "Revenue rose")["section"] == "Item 7"
    assert list(doc["sections"]) == ["Item 1", "Item 1A", "Item 7"]


def test_ingest_item_heading_variants(tmp_path):
    _, blocks = parse_body(
        tmp_path,
        "<p><b>ITEM 1A.&#160;&#160;RISK FACTORS</b></p>\n<p>Risk text.</p>\n"
        "<h2>Item 1B: Unresolved Staff Comments</h2>\n<p>None.</p>\n"
        "<p>Item 10. Directors</p>\n<p>Director text.</p>",
    )

    assert block_with(blocks, "Risk text.")["section"] == "Item 1A"
    assert block_with(blocks, "None.")["section"] == "Item 1B"
    assert block_with(blocks, "Director text.")["section"] == "Item 10"


def test_ingest_toc_does_not_misplace_content_under_real_headings(tmp_path):
    doc, blocks = parse_html(tmp_path, filing())

    # The contents table lists Item 7 last; the real headings further down win.
    assert block_with(blocks, "We mine uranium")["section"] == "Item 1"
    assert block_with(blocks, "Our business is subject")["section"] == "Item 1A"
    # Titles come from the real headings, not from the contents rows ("Business | 3").
    assert doc["sections"]["Item 1"]["title"] == "Business"
    assert doc["sections"]["Item 1A"]["title"] == "Risk Factors"
    assert doc["sections"]["Item 7"]["title"] == "Management's Discussion and Analysis"
    # Section word counts restart at the real heading.
    assert doc["sections"]["Item 7"]["n_words"] == len(
        "Item 7. Management's Discussion and Analysis Revenue rose. Costs fell. "
        "Our backup data center is in Austin.".split()
    )


def test_ingest_toc_does_not_leak_last_item_into_content_before_first_heading(tmp_path):
    _, blocks = parse_html(tmp_path, filing())

    assert block_with(blocks, BETWEEN_TOC_AND_PART_ONE)["section"] is None
    # A contents entry stays a plain table row and opens no section.
    toc_row = block_with(blocks, "Item 7. | Management")
    assert (toc_row["kind"], toc_row["section"]) == ("row", None)


def test_ingest_item_heading_laid_out_as_table_row_opens_a_section(tmp_path):
    # Unlike a contents entry, the row does not end in a page-number cell.
    doc, blocks = parse_body(tmp_path, table(("Item 1.", "Business")) + "\n<p>We mine uranium.</p>")

    assert block_with(blocks, "We mine uranium.")["section"] == "Item 1"
    assert doc["sections"]["Item 1"]["title"] == "Business"


@pytest.mark.parametrize(
    "sentence",
    [
        "Item 7 of this report discusses our results.",
        "Item 405 of Regulation S-K requires disclosure of late filings.",
    ],
)
def test_ingest_sentence_starting_with_item_is_not_a_section_heading(tmp_path, sentence):
    doc, blocks = parse_body(
        tmp_path,
        f"<p><b>Item 1. Business</b></p>\n<p>We mine uranium.</p>\n<p>{sentence}</p>\n<p>We also sell it.</p>",
    )

    assert block_with(blocks, sentence)["kind"] == "text"
    assert block_with(blocks, "We also sell it.")["section"] == "Item 1"
    assert list(doc["sections"]) == ["Item 1"]


@pytest.mark.parametrize(
    ("heading", "section", "title"),
    [
        ("Item 1A", "Item 1A", None),  # number only; the title is a block of its own
        ("ITEM 7 \u2013 MANAGEMENT\u2019S DISCUSSION", "Item 7", "MANAGEMENT\u2019S DISCUSSION"),
        ("Item 9A(T). Controls and Procedures", "Item 9A(T)", "Controls and Procedures"),
    ],
)
def test_ingest_item_heading_without_title_or_with_other_delimiter(tmp_path, heading, section, title):
    markup = heading.encode("ascii", "xmlcharrefreplace").decode()  # parse_body declares no charset
    doc, blocks = parse_body(tmp_path, f"<p>{markup}</p>\n<p>Body text.</p>")

    assert block_with(blocks, "Body text.")["section"] == section
    assert doc["sections"] == {section: {"title": title, "n_words": len(heading.split()) + 2}}


def test_ingest_bold_only_short_paragraph_becomes_heading_of_following_blocks(tmp_path):
    _, blocks = parse_html(tmp_path, filing())

    customers = block_with(blocks, "Customers")
    assert (customers["kind"], customers["heading"]) == ("heading", "Customers")
    assert block_with(blocks, "Utilities buy our product")["heading"] == "Customers"
    assert block_with(blocks, "Demand for electricity")["heading"] == "Customers"

    # An Item heading resets the sub-heading.
    assert block_with(blocks, "Item 1A. Risk Factors")["heading"] is None
    assert block_with(blocks, "Our business is subject")["heading"] is None

    # Nested bold+italic counts as emphasis-only.
    sub = "Demand for nuclear power may not develop"
    assert block_with(blocks, sub)["kind"] == "heading"
    # A paragraph with one bold phrase is ordinary text and keeps the heading above it.
    partly_bold = block_with(blocks, "Demand for nuclear power may not grow")
    assert (partly_bold["kind"], partly_bold["heading"]) == ("text", sub)
    assert block_with(blocks, "Palangana")["heading"] == sub


def test_ingest_long_bold_paragraph_is_not_a_heading(tmp_path):
    long_bold = " ".join(["word"] * 70)  # 349 characters, above the 300 limit
    _, blocks = parse_body(tmp_path, f"<p><b>Short title</b></p>\n<p><b>{long_bold}</b></p>\n<p>Body.</p>")

    assert block_with(blocks, "word")["kind"] == "text"
    assert block_with(blocks, "Body.")["heading"] == "Short title"


# --------------------------------------------------------------------------
# ingest: tables, duplicates, coverage
# --------------------------------------------------------------------------


def test_ingest_table_row_is_one_block_with_cells_joined_by_pipe(tmp_path):
    _, blocks = parse_html(tmp_path, filing())

    header = block_with(blocks, "Mine")
    assert (header["kind"], header["text"]) == ("row", "Mine | Tonnes")
    assert block_with(blocks, "Item 1A. | Risk Factors")["text"] == "Item 1A. | Risk Factors | 9"


def test_ingest_paragraph_inside_table_cell_is_not_emitted_twice(tmp_path):
    _, blocks = parse_html(tmp_path, filing())

    assert [t for t in texts(blocks) if "Palangana" in t] == ["Palangana | 1,200"]
    assert [t for t in texts(blocks) if "1,200" in t] == ["Palangana | 1,200"]


def test_ingest_layout_table_emits_inner_content_once(tmp_path):
    _, blocks = parse_body(
        tmp_path,
        "<table>\n<tr>\n<td>\n<p>Outer paragraph.</p>\n"
        + table(("a", "b"))
        + "\n</td>\n</tr>\n</table>",
    )

    assert texts(blocks) == ["Outer paragraph.", "a | b"]


def test_ingest_list_item_content_is_not_emitted_twice(tmp_path):
    _, blocks = parse_body(
        tmp_path,
        "<ul>\n<li><p>First point about pumps.</p></li>\n"
        "<li>Outer point.\n<ul>\n<li>Inner point.</li>\n</ul>\n</li>\n</ul>",
    )

    assert sum("First point about pumps." in t for t in texts(blocks)) == 1
    assert sum("Inner point." in t for t in texts(blocks)) == 1
    # The text of the outer item itself is kept, without the nested item.
    assert texts(blocks) == ["First point about pumps.", "Outer point.", "Inner point."]


def test_ingest_text_coverage_is_close_to_one(tmp_path):
    doc, blocks = parse_html(tmp_path, filing())

    assert doc["n_blocks"] == len(blocks)
    assert doc["text_coverage"] == pytest.approx(1.0, abs=0.02)


def test_ingest_text_coverage_does_not_depend_on_whitespace_between_tags(tmp_path):
    minified = re.sub(r">\s+<", "><", filing())

    doc, _ = parse_html(tmp_path, minified)

    assert doc["text_coverage"] == pytest.approx(1.0, abs=0.02)
    assert doc["text_coverage"] == parse_html(tmp_path, filing(), "pretty.htm")[0]["text_coverage"]


def test_ingest_text_coverage_does_not_split_words_at_inline_tags(tmp_path):
    doc, blocks = parse_body(tmp_path, "<p>Our 10<sup>th</sup> mine is in <b>W</b>yoming.</p>")

    assert texts(blocks) == ["Our 10th mine is in Wyoming."]
    assert doc["text_coverage"] == 1.0


def test_ingest_text_coverage_drops_when_markup_is_missed(tmp_path):
    # Loose text in a container <div> and a bare <span> are not picked up by the block walker.
    doc, blocks = parse_body(tmp_path, "<div>Loose text <p>para</p> tail</div>\n<span>bare span</span>")

    assert texts(blocks) == ["para"]
    assert doc["text_coverage"] < 0.5


# --------------------------------------------------------------------------
# ingest: page furniture
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["12", "F-7", "Page 12", "page 12", "iv", "III", "Table of Contents", "TABLE OF CONTENTS"],
)
def test_ingest_page_number_or_contents_link_is_furniture(tmp_path, text):
    _, blocks = parse_body(tmp_path, f"<p>Real text.</p>\n<p>{text}</p>\n<p><b>{text}</b></p>\n{table((text,))}")

    assert [b["kind"] for b in blocks] == ["text", "furniture", "furniture", "furniture"]


@pytest.mark.parametrize(
    "text",
    ["12 employees", "Page 12 of the agreement", "None.", "or", "2026 | 2025 | 2024", "Item 1. Business | 5", "Item 1A."],
)
def test_ingest_text_that_only_contains_a_number_is_not_furniture(tmp_path, text):
    _, blocks = parse_body(tmp_path, f"<p>{text}</p>")

    assert blocks[0]["kind"] != "furniture"


def test_ingest_furniture_stays_in_the_block_list_and_in_the_doc_id(tmp_path):
    with_furniture = "<p>Before.</p>\n<p>12</p>\n<p>Table of Contents</p>\n<p>After.</p>"
    doc, blocks = parse_body(tmp_path, with_furniture)
    other, _ = parse_body(tmp_path, "<p>Before.</p>\n<p>After.</p>")

    assert texts(blocks) == ["Before.", "12", "Table of Contents", "After."]
    assert [b["i"] for b in blocks] == [0, 1, 2, 3]
    assert doc["n_blocks"] == 4
    assert doc["doc_id"] != other["doc_id"]


def test_ingest_bold_contents_link_does_not_become_the_heading_of_following_blocks(tmp_path):
    _, blocks = parse_body(tmp_path, "<p><b>Customers</b></p>\n<p><b>Table of Contents</b></p>\n<p>Utilities buy our product.</p>")

    assert block_with(blocks, "Utilities")["heading"] == "Customers"


# --------------------------------------------------------------------------
# retrieve: passage windows
# --------------------------------------------------------------------------

# A small synthetic glossary; the real ones under glossaries/ are never read.
# Matching itself is covered in test_glossary.py.
GLOSSARY_TERMS = [
    {"term": "artificial intelligence", "tier": "ai", "variants": ["AI"], "case_sensitive_variants": ["AI"]},
    {"term": "machine learning", "tier": "ai"},
    {"term": "chatbot", "tier": "ai"},
    {"term": "data center", "tier": "context", "variants": ["data centre"]},
]
MATCHER = glossary.Matcher([("test", GLOSSARY_TERMS)])
DOC = {"doc_id": "d1", "sections": {"Item 1": {"title": "Business"}, "Item 1A": {"title": "Risk Factors"}}}


def make_blocks(
    n: int,
    hits: dict[int, str],
    sections: dict[int, str] | None = None,
    kinds: dict[int, str] | None = None,
) -> list[dict]:
    """n neutral text blocks; `hits` replaces the text of some; `sections` / `kinds` map index -> value."""
    return [
        {
            "i": i,
            "kind": (kinds or {}).get(i, "text"),
            "section": (sections or {}).get(i, "Item 1"),
            "heading": f"Heading {i}",
            "text": hits.get(i, f"Neutral sentence number {i}."),
        }
        for i in range(n)
    ]


def find(blocks: list[dict], **kwargs) -> list[dict]:
    return retrieve.passages(DOC, blocks, matcher=MATCHER, **kwargs)


def spans(passages: list[dict]) -> list[list[int]]:
    return [p["blocks"] for p in passages]


def test_retrieve_hit_takes_one_neighbour_on_each_side():
    blocks = make_blocks(8, {3: "We use AI in our mills."})

    (p,) = find(blocks)

    assert p["blocks"] == [2, 4]
    assert p["hit_blocks"] == [3]
    assert p["passage_id"] == "d1:2-4"
    assert p["doc_id"] == "d1"
    assert p["text"] == "Neutral sentence number 2.\n\nWe use AI in our mills.\n\nNeutral sentence number 4."
    assert p["matched"] == {"ai": ["artificial intelligence"]}
    assert p["glossaries"] == ["test"]
    assert (p["section"], p["section_title"], p["heading"]) == ("Item 1", "Business", "Heading 3")


def test_retrieve_window_is_clipped_at_document_edges():
    blocks = make_blocks(6, {0: "We use AI.", 5: "A chatbot answers calls."})

    assert spans(find(blocks)) == [[0, 1], [4, 5]]


def test_retrieve_no_hit_gives_no_passage():
    assert find(make_blocks(5, {})) == []


def test_retrieve_overlapping_windows_merge():
    blocks = make_blocks(8, {1: "We use AI.", 3: "Our data centers use power."})

    (p,) = find(blocks)

    assert p["blocks"] == [0, 4]
    assert p["hit_blocks"] == [1, 3]
    assert p["matched"] == {"ai": ["artificial intelligence"], "context": ["data center"]}
    assert p["text"].count("\n\n") == 4


def test_retrieve_touching_windows_merge():
    blocks = make_blocks(8, {1: "We use AI.", 4: "We use machine learning."})

    (p,) = find(blocks)

    assert p["blocks"] == [0, 5]
    assert p["hit_blocks"] == [1, 4]


def test_retrieve_windows_with_a_gap_stay_separate():
    blocks = make_blocks(8, {1: "We use AI.", 5: "We use machine learning."})

    assert spans(find(blocks)) == [[0, 2], [4, 6]]


def test_retrieve_window_does_not_cross_section_boundary():
    sections = {3: "Item 1A", 4: "Item 1A", 5: "Item 1A"}

    before = find(make_blocks(6, {2: "We use AI."}, sections))
    after = find(make_blocks(6, {3: "We use AI."}, sections))

    assert spans(before) == [[1, 2]]
    assert before[0]["section"] == "Item 1"
    assert spans(after) == [[3, 4]]
    assert (after[0]["section"], after[0]["section_title"]) == ("Item 1A", "Risk Factors")


def test_retrieve_adjacent_hits_in_different_sections_do_not_merge():
    sections = {3: "Item 1A", 4: "Item 1A", 5: "Item 1A"}
    blocks = make_blocks(6, {2: "We use AI.", 3: "AI is a risk."}, sections)

    assert spans(find(blocks)) == [[1, 2], [3, 4]]


def test_retrieve_context_parameter_sets_window_size():
    blocks = make_blocks(9, {4: "We use AI."})

    assert spans(find(blocks, context=0)) == [[4, 4]]
    assert spans(find(blocks, context=2)) == [[2, 6]]


def test_retrieve_uses_the_glossary_of_the_document_industry_by_default(tmp_path, monkeypatch):
    """Without an explicit matcher, passages() loads core + the ISIC glossary of doc["isic_class"]."""
    core = {"id": "core", "terms": [{"term": "artificial intelligence", "tier": "ai", "variants": ["AI"]}]}
    mining = {
        "id": "07",
        "terms": [{"term": "autonomous haulage", "tier": "ai", "variants": ["driverless truck"]}],
        "class_terms": {"0721": [{"term": "in-situ recovery", "tier": "context", "variants": ["ISR"]}]},
    }
    (tmp_path / "isic").mkdir()
    (tmp_path / "core.json").write_text(json.dumps(core), encoding="utf-8")
    (tmp_path / "isic" / "07.json").write_text(json.dumps(mining), encoding="utf-8")
    monkeypatch.setattr(retrieve, "load", lambda isic_class: glossary.load(isic_class, root=tmp_path))
    blocks = make_blocks(4, {1: "Driverless trucks haul ore.", 3: "We use ISR wells."})

    mining = retrieve.passages({**DOC, "isic_class": "0721"}, blocks)
    unknown = retrieve.passages({**DOC, "isic_class": None}, blocks)

    assert [p["matched"] for p in mining] == [{"ai": ["autonomous haulage"], "context": ["in-situ recovery"]}]
    assert mining[0]["glossaries"] == ["core", "isic:07", "isic:0721"]
    assert unknown == []


# --------------------------------------------------------------------------
# retrieve: direct vs implicit mentions
# --------------------------------------------------------------------------


def test_retrieve_context_only_passage_is_an_implicit_mention():
    blocks = make_blocks(8, {5: "Our data center is in Austin."})

    (p,) = find(blocks)

    assert p["hit_blocks"] == [5]
    assert p["matched"] == {"context": ["data center"]}
    assert p["mention"] == "implicit"


def test_retrieve_ai_term_makes_a_direct_mention_even_with_context_terms():
    blocks = make_blocks(8, {1: "We use AI.", 5: "Our data center is in Austin."})

    direct, implicit = find(blocks)

    assert (direct["hit_blocks"], direct["mention"]) == ([1], "direct")
    assert (implicit["hit_blocks"], implicit["mention"]) == ([5], "implicit")


def test_retrieve_merged_window_with_one_ai_hit_is_direct():
    blocks = make_blocks(8, {4: "We use AI.", 5: "Our data center is in Austin."})

    (p,) = find(blocks)

    assert p["hit_blocks"] == [4, 5]
    assert p["mention"] == "direct"


def test_retrieve_mentions_are_the_two_documented_kinds():
    assert retrieve.MENTIONS == ("direct", "implicit")


# --------------------------------------------------------------------------
# retrieve: page furniture and headings
# --------------------------------------------------------------------------


def test_retrieve_furniture_block_never_hits():
    blocks = make_blocks(5, {2: "AI"}, kinds={2: "furniture"})

    assert find(blocks) == []


def test_retrieve_window_steps_over_furniture_to_the_next_real_block():
    blocks = make_blocks(6, {1: "12", 2: "We use AI.", 3: "Table of Contents"}, kinds={1: "furniture", 3: "furniture"})

    (p,) = find(blocks)

    assert p["blocks"] == [0, 4]
    assert p["hit_blocks"] == [2]
    assert p["text"] == "Neutral sentence number 0.\n\nWe use AI.\n\nNeutral sentence number 4."


def test_retrieve_furniture_does_not_use_up_the_context_budget():
    kinds = {1: "furniture", 2: "furniture", 4: "furniture", 6: "furniture"}
    blocks = make_blocks(8, {3: "We use AI."}, kinds=kinds)

    assert spans(find(blocks, context=1)) == [[0, 5]]
    assert spans(find(blocks, context=2)) == [[0, 7]]


def test_retrieve_window_does_not_end_on_furniture_at_a_section_boundary():
    blocks = make_blocks(5, {2: "We use AI."}, sections={4: "Item 1A"}, kinds={3: "furniture"})

    assert spans(find(blocks)) == [[1, 2]]


def test_retrieve_window_does_not_extend_forward_onto_a_heading():
    blocks = make_blocks(5, {1: "We use AI."}, kinds={2: "heading"})

    assert spans(find(blocks, context=2)) == [[0, 1]]


def test_retrieve_window_extends_backward_onto_a_heading():
    blocks = make_blocks(5, {1: "We use AI."}, kinds={0: "heading"})

    assert spans(find(blocks)) == [[0, 2]]


def test_retrieve_heading_that_hits_takes_the_text_after_it():
    blocks = make_blocks(5, {1: "Risks related to AI"}, kinds={1: "heading"})

    assert spans(find(blocks)) == [[0, 2]]


def test_retrieve_furniture_between_a_hit_and_a_heading_still_stops_at_the_heading():
    blocks = make_blocks(5, {1: "We use AI."}, kinds={2: "furniture", 3: "heading"})

    (p,) = find(blocks, context=2)

    assert p["blocks"] == [0, 1]
    assert p["text"] == "Neutral sentence number 0.\n\nWe use AI."


# --------------------------------------------------------------------------
# taxonomy: Label
# --------------------------------------------------------------------------


def label_fields(**overrides) -> dict:
    """A valid about-AI label; overrides replace single fields."""
    fields = {
        "passage_id": "d1:0-2",
        "ai_reference": "explicit",
        "frame": "risk_factor",
        "roles": ["market_driver"],
        "ai_kinds": ["unspecified"],
        "disclosure_traits": ["hedging"],
        "substantiveness": "generic",
        "evidence": ["Demand for AI data centers is growing."],
        "confidence": "high",
    }
    fields.update(overrides)
    # The fields a role requires, unless the test sets them itself.
    if "adoption" in fields["roles"]:
        fields.setdefault("business_functions", ["not_stated"])
    if "risk" in fields["roles"] or "incident" in fields["roles"]:
        fields.setdefault("mit_subdomains", ["other"])
    if "governance" in fields["roles"]:
        fields.setdefault("governance_responses", ["policies_processes"])
    return fields


def test_label_accepts_valid_labels():
    plain = Label(**label_fields())
    assert plain.risk_types == [] and plain.adoption_stage is None and plain.entities == []

    full = Label(
        **label_fields(
            roles=["adoption", "risk"],
            risk_types=["cybersecurity", "third_party"],
            adoption_stage="piloting",
            ai_kinds=["generative_llm"],
            disclosure_traits=["boilerplate", "hedging"],
            entities=["Microsoft"],
        )
    )
    assert full.roles == ["adoption", "risk"]
    assert full.disclosure_traits == ["boilerplate", "hedging"]

    none = Label(passage_id="d1:0-2", ai_reference="none", confidence="high", note="keyword false positive")
    assert none.roles == [] and none.ai_kinds == [] and none.evidence == [] and none.disclosure_traits == []
    assert none.frame is None


@pytest.mark.parametrize("ai_reference", ["explicit"])
def test_label_requires_frame_when_the_passage_is_about_ai(ai_reference):
    assert Label(**label_fields(ai_reference=ai_reference, frame="market")).frame == "market"
    with pytest.raises(ValidationError, match="frame is required"):
        Label(**label_fields(ai_reference=ai_reference, frame=None))
    fields = label_fields(ai_reference=ai_reference)
    del fields["frame"]
    with pytest.raises(ValidationError, match="frame is required"):
        Label(**fields)


def test_label_rejects_none_reference_with_frame():
    with pytest.raises(ValidationError, match="must leave all other label fields empty"):
        Label(passage_id="d1:0-2", ai_reference="none", frame="business", confidence="high")


def test_label_rejects_unknown_frame():
    with pytest.raises(ValidationError, match="frame"):
        Label(**label_fields(frame="outlook"))


def test_label_rejects_externalisation_in_market_frame():
    ok = Label(**label_fields(frame="risk_factor", roles=["risk"], risk_types=["third_party"],
                              disclosure_traits=["externalisation"]))
    assert ok.disclosure_traits == ["externalisation"]
    with pytest.raises(ValidationError, match="not applicable in frame 'market'"):
        Label(**label_fields(frame="market", disclosure_traits=["externalisation"]))


def test_label_accepts_empty_disclosure_traits_for_a_specific_statement():
    specific = Label(**label_fields(disclosure_traits=[]))
    assert specific.disclosure_traits == []
    # The field may be omitted: a missing list is the same as none of the traits.
    fields = label_fields()
    del fields["disclosure_traits"]
    assert Label(**fields).disclosure_traits == []


def test_label_rejects_none_reference_with_disclosure_traits():
    with pytest.raises(ValidationError, match="must leave all other label fields empty"):
        Label(passage_id="d1:0-2", ai_reference="none", disclosure_traits=["boilerplate"], confidence="high")


def test_label_rejects_unknown_disclosure_trait():
    with pytest.raises(ValidationError, match="disclosure_traits"):
        Label(**label_fields(disclosure_traits=["contextual"]))


def test_label_rejects_disclosure_traits_that_are_not_a_list():
    with pytest.raises(ValidationError, match="disclosure_traits"):
        Label(**label_fields(disclosure_traits="hedging"))


def test_label_accepts_up_to_three_evidence_quotes():
    three = ["Demand for AI data centers is growing.", "We may not benefit from it.", "AI drives demand."]
    assert Label(**label_fields(evidence=three)).evidence == three


def test_label_rejects_none_reference_with_roles():
    with pytest.raises(ValidationError, match="must leave all other label fields empty"):
        Label(passage_id="d1:0-2", ai_reference="none", roles=["general"], confidence="high")


def test_label_rejects_none_reference_with_evidence():
    with pytest.raises(ValidationError, match="must leave all other label fields empty"):
        Label(passage_id="d1:0-2", ai_reference="none", evidence=["Our backup data center."], confidence="high")


def test_label_rejects_risk_role_without_risk_types():
    with pytest.raises(ValidationError, match="risk_types must be given if and only if"):
        Label(**label_fields(roles=["risk"]))


def test_label_rejects_risk_types_without_risk_role():
    with pytest.raises(ValidationError, match="risk_types must be given if and only if"):
        Label(**label_fields(roles=["market_driver"], risk_types=["market_demand"]))


def test_label_rejects_adoption_role_without_adoption_stage():
    with pytest.raises(ValidationError, match="adoption_stage must be given if and only if"):
        Label(**label_fields(roles=["adoption"]))


def test_label_rejects_adoption_stage_without_adoption_role():
    with pytest.raises(ValidationError, match="adoption_stage must be given if and only if"):
        Label(**label_fields(adoption_stage="deployed"))


def test_label_rejects_general_combined_with_another_role():
    with pytest.raises(ValidationError, match="'general' cannot be combined"):
        Label(**label_fields(roles=["general", "market_driver"]))


def test_label_rejects_about_ai_label_without_evidence():
    with pytest.raises(ValidationError, match="evidence are required"):
        Label(**label_fields(evidence=[]))


def test_label_rejects_evidence_that_is_not_a_list():
    with pytest.raises(ValidationError, match="evidence"):
        Label(**label_fields(evidence="Demand for AI data centers is growing."))


def test_label_rejects_more_than_three_evidence_quotes():
    with pytest.raises(ValidationError, match="1 to 3 non-empty quotes"):
        Label(**label_fields(evidence=["a", "b", "c", "d"]))


def test_label_rejects_empty_evidence_quote():
    with pytest.raises(ValidationError, match="1 to 3 non-empty quotes"):
        Label(**label_fields(evidence=["Demand for AI data centers is growing.", "  "]))


def test_label_rejects_about_ai_label_without_roles():
    with pytest.raises(ValidationError, match="at least one role is required"):
        Label(**label_fields(roles=[]))


def test_label_rejects_values_outside_the_taxonomy():
    with pytest.raises(ValidationError):
        Label(**label_fields(roles=["hype"]))
    with pytest.raises(ValidationError):
        Label(**label_fields(ai_reference="maybe"))


def test_taxonomy_definitions_and_schema_list_the_same_values():
    def allowed(field: str) -> set:
        return {v for v in _literal_values(Label.model_fields[field].annotation) if v is not None}

    assert allowed("ai_reference") == set(taxonomy.AI_REFERENCE)
    assert allowed("frame") == set(taxonomy.FRAMES)
    assert allowed("roles") == set(taxonomy.ROLES)
    assert allowed("risk_types") == set(taxonomy.RISK_TYPES)
    assert allowed("mit_subdomains") == set(taxonomy.MIT_SUBDOMAINS)
    assert allowed("adoption_stage") == set(taxonomy.ADOPTION_STAGES)
    assert allowed("ai_kinds") == set(taxonomy.AI_KINDS)
    assert allowed("substantiveness") == set(taxonomy.SUBSTANTIVENESS)
    assert allowed("disclosure_traits") == set(taxonomy.DISCLOSURE_TRAITS)


def _literal_values(annotation) -> list:
    """Flatten Literal[...] / Optional[Literal[...]] / list[Literal[...]] into its values."""
    args = get_args(annotation)
    if not args:
        return [None] if annotation is type(None) else [annotation]
    return [v for a in args for v in _literal_values(a)]


ALL_DEFINITIONS = (
    taxonomy.AI_REFERENCE,
    taxonomy.FRAMES,
    taxonomy.ROLES,
    taxonomy.RISK_TYPES,
    taxonomy.MIT_SUBDOMAINS,
    taxonomy.ADOPTION_STAGES,
    taxonomy.BUSINESS_FUNCTIONS,
    taxonomy.GOVERNANCE_RESPONSES,
    taxonomy.AI_KINDS,
    taxonomy.DISCLOSURE_TRAITS,
    taxonomy.SUBSTANTIVENESS,
)


def test_codebook_names_version_and_every_value():
    text = taxonomy.codebook()

    assert f"taxonomy v{taxonomy.TAXONOMY_VERSION}" in text
    assert "A value applies only if all its criteria hold." in text
    for values in ALL_DEFINITIONS:
        for value in values:
            assert f"- `{value}`:" in text
    assert "specificity" not in text


def test_every_value_has_a_definition_and_two_or_three_criteria():
    for values in ALL_DEFINITIONS:
        for value, (definition, criteria) in values.items():
            assert definition.endswith("."), value
            assert 2 <= len(criteria) <= 3, value


def test_codebook_renders_criteria_as_a_numbered_checklist():
    text = taxonomy.codebook()

    definition, criteria = taxonomy.ROLES["adoption"]
    rendered = f"- `adoption`: {definition}\n  Criteria (all required): " + "; ".join(
        f"({i}) {c}" for i, c in enumerate(criteria, 1)
    ) + "."
    assert rendered in text
    assert text.count("Criteria (all required): (1) ") == sum(len(v) for v in ALL_DEFINITIONS)


def test_codebook_puts_the_frame_step_before_the_roles():
    text = taxonomy.codebook()

    step = text.index("### Step 1: determine the frame (`frame`)")
    assert text.index("(`ai_reference`)") < step < text.index("(`roles`)")
    assert "frame-dependent" in text.split("(`roles`)")[1]  # the roles are read in the frame
    assert "presupposed use" not in text  # the v0.3 rule that made "AI usage" in a remit adoption is gone


# --------------------------------------------------------------------------
# classify.validate
# --------------------------------------------------------------------------

PASSAGES = [
    {"passage_id": "d1:0-2", "text": "Demand for AI data centers is growing.\n\nWe may not benefit from it."},
    {"passage_id": "d1:5-5", "text": "Our backup data center is in Austin."},
]


def line(**overrides) -> str:
    return json.dumps(label_fields(**overrides))


NONE_LINE = json.dumps({"passage_id": "d1:5-5", "ai_reference": "none", "confidence": "high"})


def test_validate_accepts_valid_labels_and_stamps_coder_and_version():
    labels, problems = classify.validate([line(), "", NONE_LINE], PASSAGES, coder="alice")

    assert problems == []
    assert [l["passage_id"] for l in labels] == ["d1:0-2", "d1:5-5"]
    assert all(l["coder"] == "alice" for l in labels)
    assert all(l["taxonomy_version"] == taxonomy.TAXONOMY_VERSION for l in labels)
    assert labels[0]["roles"] == ["market_driver"]


def test_validate_rejects_evidence_that_is_not_verbatim():
    labels, problems = classify.validate(
        [line(evidence=["AI data center demand is growing."]), NONE_LINE], PASSAGES, coder="alice"
    )

    assert [l["passage_id"] for l in labels] == ["d1:5-5"]
    assert problems == [
        "line 1: evidence[0] is not a verbatim quote from d1:0-2",
        "missing label for d1:0-2",
    ]


def test_validate_accepts_several_verbatim_quotes():
    quotes = ["Demand for AI data centers is growing.", "We may not benefit from it."]

    labels, problems = classify.validate([line(evidence=quotes), NONE_LINE], PASSAGES, coder="alice")

    assert problems == []
    assert labels[0]["evidence"] == quotes


def test_validate_checks_every_quote_and_names_the_bad_ones():
    quotes = ["Demand for AI data centers is growing.", "We will surely benefit.", "Not in the passage."]

    labels, problems = classify.validate([line(evidence=quotes), NONE_LINE], PASSAGES, coder="alice")

    assert [l["passage_id"] for l in labels] == ["d1:5-5"]
    assert problems[0] == "line 1: evidence[1, 2] is not a verbatim quote from d1:0-2"


def test_validate_rejects_evidence_given_as_a_string():
    _, problems = classify.validate(
        [line(evidence="Demand for AI data centers is growing."), NONE_LINE], PASSAGES, coder="alice"
    )

    assert problems[0].startswith("line 1: evidence")


def test_validate_rejects_empty_evidence_unless_none():
    none_with_evidence = json.dumps(
        {"passage_id": "d1:5-5", "ai_reference": "none", "evidence": ["Our backup data center is in Austin."],
         "confidence": "high"}
    )

    labels, problems = classify.validate([line(evidence=[]), none_with_evidence], PASSAGES, coder="alice")

    assert labels == []
    assert "evidence are required" in problems[0]
    assert "must leave all other label fields empty" in problems[1]


def test_validate_tolerates_whitespace_differences_in_evidence():
    evidence = ["Demand for AI   data centers\nis growing. We may\tnot benefit from it. ", " We may not benefit from it."]

    labels, problems = classify.validate([line(evidence=evidence), NONE_LINE], PASSAGES, coder="alice")

    assert problems == []
    assert len(labels) == 2


def test_validate_rejects_unknown_passage_id():
    labels, problems = classify.validate(
        [line(), NONE_LINE, line(passage_id="d9:1-2")], PASSAGES, coder="alice"
    )

    assert len(labels) == 2
    assert problems == ["line 3: unknown passage_id d9:1-2"]


def test_validate_rejects_duplicate_label_and_keeps_the_first():
    labels, problems = classify.validate(
        [line(), line(roles=["general"]), NONE_LINE], PASSAGES, coder="alice"
    )

    assert problems == ["line 2: duplicate label for d1:0-2"]
    assert [l["roles"] for l in labels] == [["market_driver"], []]


def test_validate_rejects_invalid_json():
    labels, problems = classify.validate([line(), "{not json", NONE_LINE], PASSAGES, coder="alice")

    assert len(labels) == 2
    assert len(problems) == 1
    assert problems[0].startswith("line 2: ")


def test_validate_rejects_label_that_breaks_the_schema():
    labels, problems = classify.validate([line(roles=["risk"]), NONE_LINE], PASSAGES, coder="alice")

    assert [l["passage_id"] for l in labels] == ["d1:5-5"]
    assert len(problems) == 2
    assert problems[0].startswith("line 1: ")
    assert problems[1] == "missing label for d1:0-2"


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"roles": ["risk"]}, "risk_types must be given if and only if"),
        ({"roles": ["hype"]}, "roles"),
    ],
    ids=["rule_violation", "unknown_value"],
)
def test_validate_schema_problem_states_the_reason(overrides, reason):
    _, problems = classify.validate([line(**overrides), NONE_LINE], PASSAGES, coder="alice")

    assert reason in problems[0]


def test_validate_reports_missing_passages():
    labels, problems = classify.validate([line()], PASSAGES, coder="alice")

    assert [l["passage_id"] for l in labels] == ["d1:0-2"]
    assert problems == ["missing label for d1:5-5"]


# --------------------------------------------------------------------------
# classify.adjudicate (three coders)
# --------------------------------------------------------------------------


def coded(pid: str, coder: str, **overrides) -> dict:
    """A schema-valid label as classify.validate would store it."""
    label = Label(**label_fields(passage_id=pid, **overrides))
    return {**label.model_dump(), "coder": coder, "taxonomy_version": taxonomy.TAXONOMY_VERSION}


def coded_none(pid: str, coder: str) -> dict:
    label = Label(passage_id=pid, ai_reference="none", confidence="high")
    return {**label.model_dump(), "coder": coder, "taxonomy_version": taxonomy.TAXONOMY_VERSION}


def by_coder(*labels: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for l in labels:
        out.setdefault(l["coder"], []).append(l)
    return out


P1, P2, P3, P4 = "d1:0-2", "d1:5-7", "d1:10-12", "d1:20-22"


def three_coders() -> dict[str, list[dict]]:
    risk = {"roles": ["market_driver", "risk"], "risk_types": ["market_demand"]}
    return by_coder(
        # P1: all three agree on everything.
        coded(P1, "a", **risk, entities=["Nvidia"]),
        coded(P1, "b", **risk, entities=["nvidia "]),
        coded(P1, "c", **risk),
        # P2: 2-1 on every single-valued field and on elements of the multi-valued fields.
        coded(P2, "a", roles=["adoption", "risk"], risk_types=["cybersecurity", "third_party"],
              adoption_stage="deployed", ai_kinds=["generative_llm"], disclosure_traits=["boilerplate", "hedging"]),
        coded(P2, "b", roles=["adoption", "risk"], risk_types=["cybersecurity"],
              adoption_stage="deployed", ai_kinds=["generative_llm"], disclosure_traits=["boilerplate"]),
        coded(P2, "c", roles=["adoption"], adoption_stage="piloting", disclosure_traits=["vagueness"]),
        # P3: three-way split on ai_kinds only.
        coded(P3, "a", ai_kinds=["generative_llm"]),
        coded(P3, "b", ai_kinds=["traditional_ml"]),
        coded(P3, "c", ai_kinds=["unspecified"]),
        # P4: "risk" loses the vote 1-2.
        coded(P4, "a", **risk),
        coded(P4, "b"),
        coded(P4, "c"),
    )


def adjudicated(labels_by_coder: dict[str, list[dict]]) -> tuple[dict[str, dict], dict]:
    final, agreement = classify.adjudicate(labels_by_coder)
    return {f["passage_id"]: f for f in final}, agreement


def test_adjudicate_unanimous_passage():
    final, _ = adjudicated(three_coders())
    p1 = final[P1]

    assert p1["ai_reference"] == "explicit"
    assert p1["roles"] == ["market_driver", "risk"]
    assert p1["risk_types"] == ["market_demand"]
    assert (p1["adoption_stage"], p1["ai_kinds"], p1["disclosure_traits"]) == (None, ["unspecified"], ["hedging"])
    assert p1["coders"] == ["a", "b", "c"]
    assert p1["taxonomy_version"] == taxonomy.TAXONOMY_VERSION
    assert p1["entities"] == ["Nvidia"]  # named by two of three coders, case-insensitively
    assert p1["evidence"] == ["Demand for AI data centers is growing."]
    assert p1["confidence"] == {"a": "high", "b": "high", "c": "high"}
    assert (p1["disputed"], p1["needs_review"]) == ([], False)


def test_adjudicate_flattens_and_deduplicates_the_coders_evidence():
    final, _ = adjudicated(
        by_coder(
            coded(P1, "a", evidence=["Demand for AI data centers is growing.", "We may not benefit from it."]),
            coded(P1, "b", evidence=["We may  not benefit\nfrom it."]),  # same quote, other whitespace
            coded(P1, "c", evidence=["AI drives demand."]),
            coded_none(P2, "a"), coded_none(P2, "b"), coded_none(P2, "c"),
        )
    )

    assert final[P1]["evidence"] == [
        "Demand for AI data centers is growing.", "We may not benefit from it.", "AI drives demand.",
    ]
    assert final[P2]["evidence"] == []


def test_adjudicate_majority_wins_on_single_valued_fields():
    final, _ = adjudicated(three_coders())
    p2 = final[P2]

    assert p2["ai_reference"] == "explicit"
    assert p2["adoption_stage"] == "deployed"
    assert p2["ai_kinds"] == ["generative_llm"]
    assert (p2["disputed"], p2["needs_review"]) == ([], False)


def test_adjudicate_majority_wins_on_frame():
    final, agreement = adjudicated(
        by_coder(
            coded(P1, "a", frame="governance", roles=["governance"]),
            coded(P1, "b", frame="governance", roles=["governance"]),
            coded(P1, "c", frame="business", roles=["adoption"], adoption_stage="deployed"),
            coded(P2, "a", frame="risk_factor"),
            coded(P2, "b", frame="market"),
            coded(P2, "c", frame="business"),
        )
    )

    assert final[P1]["frame"] == "governance"
    assert (final[P1]["disputed"], final[P1]["needs_review"]) == ([], False)
    assert final[P2]["frame"] is None
    assert (final[P2]["disputed"], final[P2]["needs_review"]) == (["frame"], True)
    assert agreement["unanimous_share"]["frame"] == 0.0


def test_adjudicate_majority_wins_per_value_on_multi_valued_fields():
    final, _ = adjudicated(three_coders())
    p2 = final[P2]

    assert p2["roles"] == ["adoption", "risk"]  # adoption 3 of 3, risk 2 of 3
    assert p2["risk_types"] == ["cybersecurity"]  # cybersecurity 2 of 3, third_party 1 of 3
    assert p2["needs_review"] is False


def test_adjudicate_majority_per_disclosure_trait():
    final, _ = adjudicated(three_coders())
    p2 = final[P2]

    # boilerplate 2 of 3, hedging 1 of 3, vagueness 1 of 3: each trait is voted on its own.
    assert p2["disclosure_traits"] == ["boilerplate"]
    assert p2["needs_review"] is False


def test_adjudicate_no_majority_on_any_trait_gives_an_empty_list_without_review():
    final, _ = adjudicated(
        by_coder(
            coded(P1, "a", disclosure_traits=["boilerplate"]),
            coded(P1, "b", disclosure_traits=["hedging"]),
            coded(P1, "c", disclosure_traits=[]),
        )
    )

    assert final[P1]["disclosure_traits"] == []
    assert (final[P1]["disputed"], final[P1]["needs_review"]) == ([], False)


def test_adjudicate_three_way_split_on_single_valued_field_needs_review():
    final, _ = adjudicated(three_coders())
    p3 = final[P3]

    assert p3["ai_kinds"] == []
    assert p3["disputed"] == ["ai_kinds"]
    assert p3["needs_review"] is True
    # The fields the coders agree on are still decided.
    assert (p3["ai_reference"], p3["roles"], p3["disclosure_traits"]) == ("explicit", ["market_driver"], ["hedging"])


def test_adjudicate_no_risk_types_when_risk_lost_the_vote():
    final, _ = adjudicated(three_coders())
    p4 = final[P4]

    assert p4["roles"] == ["market_driver"]
    assert p4["risk_types"] == []
    assert (p4["disputed"], p4["needs_review"]) == ([], False)


def test_adjudicate_split_on_ai_reference_clears_the_label():
    # Two coders, one says explicit and one says none: no value has more than half the votes.
    risk = {"roles": ["risk"], "risk_types": ["market_demand"]}
    final, _ = adjudicated(by_coder(coded(P1, "a", **risk), coded_none(P1, "c")))
    p1 = final[P1]

    # without an agreed ai_reference the voted label must not carry roles or risk types.
    assert p1["ai_reference"] is None
    assert (p1["roles"], p1["risk_types"], p1["disclosure_traits"]) == ([], [], [])
    assert (p1["frame"], p1["adoption_stage"], p1["ai_kinds"]) == (None, None, [])
    assert "ai_reference" in p1["disputed"]
    assert p1["needs_review"] is True


def test_adjudicate_majority_role_without_agreed_detail_needs_review():
    final, _ = adjudicated(
        by_coder(
            coded(P1, "a", roles=["risk"], risk_types=["cybersecurity"]),
            coded(P1, "b", roles=["risk"], risk_types=["workforce"]),
            coded(P1, "c", roles=["risk"], risk_types=["regulatory_legal"]),
            coded(P2, "a", roles=["adoption"], adoption_stage="deployed"),
            coded(P2, "b", roles=["adoption"], adoption_stage="piloting"),
            coded(P2, "c", roles=["adoption"], adoption_stage="planned"),
        )
    )

    assert (final[P1]["roles"], final[P1]["risk_types"]) == (["risk"], [])
    assert (final[P1]["disputed"], final[P1]["needs_review"]) == (["risk_types"], True)
    assert (final[P2]["roles"], final[P2]["adoption_stage"]) == (["adoption"], None)
    assert (final[P2]["disputed"], final[P2]["needs_review"]) == (["adoption_stage"], True)


def test_adjudicate_missing_coder_needs_review():
    final, agreement = adjudicated(by_coder(coded(P1, "a"), coded(P1, "b"), coded(P2, "a"), coded(P2, "b"), coded(P2, "c")))

    assert final[P1]["coders"] == ["a", "b"]
    assert final[P1]["roles"] == ["market_driver"]  # two of three coders is still a majority
    assert (final[P1]["disputed"], final[P1]["needs_review"]) == (["missing_coder"], True)
    assert final[P2]["needs_review"] is False
    assert agreement["needs_review"] == [P1]


def test_adjudicate_majority_none_against_one_explicit_needs_no_review():
    final, agreement = adjudicated(by_coder(coded_none(P1, "a"), coded_none(P1, "b"), coded(P1, "c")))
    p1 = final[P1]

    assert p1["ai_reference"] == "none"
    assert (p1["frame"], p1["roles"], p1["ai_kinds"], p1["disclosure_traits"]) == (None, [], [], [])
    assert p1["disputed"] == []
    assert p1["needs_review"] is False
    assert agreement["needs_review"] == []


def test_adjudicate_adoption_losing_the_vote_needs_no_review():
    final, _ = adjudicated(
        by_coder(
            coded(P1, "a"),
            coded(P1, "b"),
            coded(P1, "c", roles=["market_driver", "adoption"], adoption_stage="deployed"),
        )
    )
    p1 = final[P1]

    assert (p1["roles"], p1["adoption_stage"]) == (["market_driver"], None)
    assert p1["disputed"] == []
    assert p1["needs_review"] is False


def test_adjudicate_orders_passages_by_document_and_block():
    final, _ = classify.adjudicate(
        by_coder(coded("d2:3-4", "a"), coded("d1:10-12", "a"), coded("d1:2-4", "a"))
    )

    assert [f["passage_id"] for f in final] == ["d1:2-4", "d1:10-12", "d2:3-4"]


def test_adjudicate_agreement_report():
    _, agreement = adjudicated(three_coders())

    assert agreement["taxonomy_version"] == taxonomy.TAXONOMY_VERSION
    assert agreement["coders"] == ["a", "b", "c"]
    assert agreement["n_passages"] == 4
    assert agreement["unanimous_share"] == {
        "ai_reference": 1.0,  # P1 P2 P3 P4
        "frame": 1.0,  # P1 P2 P3 P4 (the fixture's default)
        "adoption_stage": 0.75,  # P1 P3 P4 (all empty)
        "ai_kinds": 0.5,  # P1 P4
        "substantiveness": 1.0,  # P1 P2 P3 P4 (the fixture's default)
        "roles": 0.5,  # P1 P3
        "risk_types": 0.5,  # P1 P3
        "mit_subdomains": 0.5,  # P1 P3 (the fixture's default `other` wherever risk is a role)
        "business_functions": 1.0,  # empty on P1 P3 P4; on P2 all three give adoption with the same function
        "governance_responses": 1.0,  # no coder gives the governance role
        "disclosure_traits": 0.75,  # P1 P3 P4
    }
    # 12 coder pairs; identical labels: three pairs on P1, b-c on P4.
    assert agreement["pairwise_identical_label_share"] == 0.333
    assert agreement["needs_review"] == [P3]


def test_adjudicate_single_coder_passes_labels_through():
    final, agreement = adjudicated(by_coder(coded(P1, "a", roles=["risk"], risk_types=["workforce"]), coded_none(P2, "a")))

    assert (final[P1]["roles"], final[P1]["risk_types"]) == (["risk"], ["workforce"])
    assert final[P2]["ai_reference"] == "none"
    assert not final[P1]["needs_review"] and not final[P2]["needs_review"]
    assert agreement["pairwise_identical_label_share"] is None
    assert agreement["needs_review"] == []


# --------------------------------------------------------------------------
# aggregate.summarise
# --------------------------------------------------------------------------

REPORT = {"doc_id": "d1", "company": "ACME URANIUM CORP", "form": "10-K", "fiscal_year": 2026, "n_words": 1000}


def passage(pid: str, section: str | None, mention: str = "direct") -> dict:
    return {"passage_id": pid, "doc_id": pid.split(":")[0], "section": section, "text": "...",
            "mention": mention, "matched": {"ai": ["artificial intelligence"]} if mention == "direct" else {"context": ["data center"]}}


def final_label(pid: str, ai_reference: str | None, frame=None, roles=(), risk_types=(), adoption_stage=None,
                ai_kinds=(), disclosure_traits=(), entities=(), needs_review=False, substantiveness=None,
                business_functions=(), governance_responses=(), mit_subdomains=()) -> dict:
    """A label in the shape classify.adjudicate writes to labels_final.jsonl."""
    return {
        "passage_id": pid, "ai_reference": ai_reference, "frame": frame, "roles": list(roles),
        "risk_types": list(risk_types), "adoption_stage": adoption_stage, "ai_kinds": list(ai_kinds),
        "business_functions": list(business_functions), "governance_responses": list(governance_responses),
        "mit_subdomains": list(mit_subdomains) or (["other"] if "risk" in roles or "incident" in roles else []),
        "disclosure_traits": list(disclosure_traits), "entities": list(entities), "needs_review": needs_review,
        "substantiveness": substantiveness or ("generic" if ai_reference == "explicit" else None),
    }


def test_summarise_counts_and_flags():
    passages = [
        passage("d1:0-2", "Item 1"),
        passage("d1:5-7", "Item 1A"),
        passage("d1:9-9", "Item 7"),
        passage("d1:12-14", None),
        passage("d1:20-22", "Item 7"),
        passage("d1:30-31", "Item 7"),
    ]
    labels = [
        final_label("d1:0-2", "explicit", frame="market", roles=["market_driver"], ai_kinds=["unspecified"],
                    disclosure_traits=["vagueness"], entities=["Nvidia"]),
        final_label("d1:5-7", "explicit", frame="risk_factor", roles=["market_driver", "risk"],
                    risk_types=["market_demand"], ai_kinds=["unspecified"],
                    disclosure_traits=["boilerplate", "hedging"], entities=["Microsoft", "Nvidia"],
                    needs_review=True),
        final_label("d1:9-9", "none"),  # keyword false positive
        final_label("d1:12-14", "explicit", frame="market", roles=["general"], ai_kinds=["generative_llm"]),  # no trait
        final_label("d1:20-22", None, needs_review=True),  # coders split on ai_reference
        # d1:30-31 has no label yet; the next label belongs to another report.
        final_label("d2:0-2", "explicit", frame="business", roles=["adoption"], adoption_stage="deployed",
                    ai_kinds=["generative_llm"], disclosure_traits=["safe_harbour"]),
    ]

    s = aggregate.summarise(REPORT, passages, labels)

    assert (s["doc_id"], s["company"], s["form"], s["fiscal_year"], s["n_words"]) == (
        "d1", "ACME URANIUM CORP", "10-K", 2026, 1000,
    )
    assert s["n_candidates"] == 6
    assert s["n_unlabelled"] == 1
    assert s["n_ai_passages"] == 3
    assert s["n_false_candidates"] == 1
    assert s["n_needs_review"] == 2
    assert s["ai_reference"] == {"explicit": 3, "none": 1, "disputed": 1}
    assert s["frames"] == {"market": 2, "risk_factor": 1}  # AI passages of this report only
    assert s["roles"] == {"market_driver": 2, "risk": 1, "general": 1}
    assert s["risk_types"] == {"market_demand": 1}
    assert s["adoption_stage"] == {}
    assert s["ai_kinds"] == {"unspecified": 2, "generative_llm": 1}
    assert s["disclosure_traits"] == {"vagueness": 1, "boilerplate": 1, "hedging": 1}
    assert s["sections"] == {"Item 1": 1, "Item 1A": 1, "unknown": 1}
    assert s["entities"] == ["Microsoft", "Nvidia"]
    assert s["mentions_ai"] is True
    assert s["ai_as_market_driver"] is True
    assert s["ai_as_risk"] is True
    assert s["ai_adoption"] is False


def test_summarise_trait_activation_rate_and_rate_per_trait():
    passages = [passage("d1:0-2", "Item 1"), passage("d1:5-7", "Item 1A"), passage("d1:9-9", "Item 7"),
                passage("d1:12-14", "Item 7")]
    labels = [
        final_label("d1:0-2", "explicit", roles=["market_driver"], ai_kinds=["unspecified"],
                    disclosure_traits=["vagueness"]),
        final_label("d1:5-7", "explicit", roles=["market_driver"], ai_kinds=["unspecified"],
                    disclosure_traits=["boilerplate", "hedging"]),
        final_label("d1:9-9", "explicit", roles=["general"], ai_kinds=["generative_llm"]),  # specific: no trait
        final_label("d1:12-14", "none", disclosure_traits=[]),  # not an AI passage: not in the denominator
    ]

    s = aggregate.summarise(REPORT, passages, labels)

    assert s["n_ai_passages"] == 3
    assert s["trait_activation_rate"] == 0.667  # two of three AI passages carry at least one trait
    assert s["trait_rates"] == {
        "boilerplate": 0.333, "hedging": 0.333, "externalisation": 0.0, "vagueness": 0.333, "safe_harbour": 0.0,
    }


def test_summarise_report_with_only_false_candidates_does_not_mention_ai():
    passages = [passage("d1:0-2", "Item 1"), passage("d1:5-7", "Item 7")]
    labels = [final_label("d1:0-2", "none"), final_label("d1:5-7", "none")]

    s = aggregate.summarise(REPORT, passages, labels)

    assert (s["n_candidates"], s["n_ai_passages"], s["n_false_candidates"]) == (2, 0, 2)
    assert s["frames"] == {} and s["roles"] == {} and s["sections"] == {} and s["entities"] == []
    assert (s["disclosure_traits"], s["trait_activation_rate"], s["trait_rates"]) == ({}, None, {})
    assert (s["mentions_ai"], s["ai_as_market_driver"], s["ai_adoption"], s["ai_as_risk"]) == (
        False, False, False, False,
    )


def test_summarise_report_without_candidates():
    s = aggregate.summarise(REPORT, [], [])

    assert (s["n_candidates"], s["n_unlabelled"], s["n_ai_passages"]) == (0, 0, 0)
    assert s["mentions_ai"] is False


def test_render_quotes_every_piece_of_evidence():
    passages = [
        {**passage("d1:0-2", "Item 1"), "section_title": "Business", "blocks": [0, 2], "text": "AI. Power."},
        {**passage("d1:5-5", "Item 7"), "section_title": None, "blocks": [5, 5], "text": "Backup site."},
    ]
    labels = [
        {**final_label("d1:0-2", "explicit", frame="risk_factor", roles=["market_driver", "risk"],
                       risk_types=["market_demand"], ai_kinds=["unspecified"],
                       disclosure_traits=["boilerplate", "hedging"]),
         "evidence": ["AI.", "Power."], "notes": ["a: two sentences"], "disputed": []},
        {**final_label("d1:5-5", "none"), "evidence": [], "notes": [], "disputed": []},
    ]

    text = aggregate.render(REPORT, passages, labels, aggregate.summarise(REPORT, passages, labels))

    assert "> AI.\n\n> Power.\n\n- Note (a: two sentences)\n" in text
    assert text.count("> ") == 2
    assert "- Frames: risk_factor (1)\n" in text
    assert "**AI reference: explicit | frame: risk_factor | roles: market_driver, risk" in text
    assert "- Disclosure traits: boilerplate (1), hedging (1)\n" in text
    assert "- Trait activation rate: 1.0 (boilerplate (1.0), hedging (1.0), externalisation (0.0), " \
           "vagueness (0.0), safe_harbour (0.0))\n" in text
    assert "| traits: boilerplate, hedging" in text


def test_render_without_ai_passages_shows_no_activation_rate():
    passages = [{**passage("d1:5-5", "Item 7"), "section_title": None, "blocks": [5, 5], "text": "Backup site."}]
    labels = [{**final_label("d1:5-5", "none"), "evidence": [], "notes": [], "disputed": []}]

    text = aggregate.render(REPORT, passages, labels, aggregate.summarise(REPORT, passages, labels))

    assert "- Disclosure traits: none\n- Trait activation rate: n/a\n" in text


# --------------------------------------------------------------------------
# cli: the stages chained through their files
# --------------------------------------------------------------------------


def read_jsonl(path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_cli_runs_all_stages_through_their_files(tmp_path, capsys):
    filings = tmp_path / "filings"
    filings.mkdir()
    write(filings, "download_a.htm", filing(token="aa11"))
    write(filings, "download_b.html", filing(token="bb22"))
    data = tmp_path / "work"

    def run(*args: str) -> None:
        cli.main(["--data", str(data), *args])

    run("run", str(filings), "--workers", "1")
    (doc_dir,) = list((data / "docs").iterdir())
    doc = json.loads((doc_dir / "document.json").read_text(encoding="utf-8"))
    assert doc_dir.name == doc["doc_id"]
    assert doc["source_files"] == ["download_a.htm", "download_b.html"]
    assert len(read_jsonl(doc_dir / "blocks.jsonl")) == doc["n_blocks"]
    assert [r["doc_id"] for r in read_jsonl(data / "index" / "files.jsonl")] == [doc["doc_id"]] * 2

    passages = read_jsonl(doc_dir / "passages.jsonl")
    assert [(p["section"], sorted(p["matched"])) for p in passages] == [
        ("Item 1", ["ai", "context"]),
        ("Item 7", ["context"]),
    ]

    assert [p["mention"] for p in passages] == ["direct", "implicit"]

    # The recall check of the run: the reference patterns find nothing outside the passages.
    assert doc["recall_check"] == {"blocks": 0, "by_pattern": {}}

    # Only the direct mention is a task; the context passage is handed on as a hint with its text.
    run("tasks")
    tasks = read_jsonl(data / "tasks.jsonl")
    hints = read_jsonl(data / "hints.jsonl")
    assert [t["passage_id"] for t in tasks] == [passages[0]["passage_id"]]
    assert [h["passage_id"] for h in hints] == [passages[1]["passage_id"]]
    assert hints[0]["text"] == passages[1]["text"]
    assert passages[1]["term_groups"] == {t: "industry" for t in passages[1]["matched"]["context"]} or all(
        g for g in passages[1]["term_groups"].values())
    assert (tasks[0]["company"], tasks[0]["form"], tasks[0]["fiscal_year"]) == ("ACME URANIUM CORP", "10-K", 2026)
    assert (tasks[0]["section"], tasks[0]["heading"]) == ("Item 1 Business", "Customers")
    assert (data / "codebook.md").read_text(encoding="utf-8") == taxonomy.codebook()

    coder_file = tmp_path / "alice.jsonl"
    about_ai = line(passage_id=passages[0]["passage_id"], evidence=["Demand for electricity from AI data centers is growing."])
    hint_label = json.dumps({"passage_id": passages[1]["passage_id"], "ai_reference": "none", "confidence": "high"})

    # A label for a context passage is not a task and is refused; an incomplete
    # file is refused as a whole unless --partial is given.
    coder_file.write_text(hint_label + "\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        run("accept", str(coder_file), "--coder", "alice")
    assert not (data / "labels" / "alice.jsonl").exists()

    coder_file.write_text(about_ai + "\n", encoding="utf-8")
    run("accept", str(coder_file), "--coder", "alice")
    accepted = read_jsonl(data / "labels" / "alice.jsonl")
    assert [(l["coder"], l["taxonomy_version"]) for l in accepted] == [("alice", taxonomy.TAXONOMY_VERSION)]

    run("adjudicate")
    final = read_jsonl(data / "labels_final.jsonl")
    assert [f["ai_reference"] for f in final] == ["explicit"]
    agreement = json.loads((data / "agreement.json").read_text(encoding="utf-8"))
    assert (agreement["coders"], agreement["n_passages"], agreement["needs_review"]) == (["alice"], 1, [])

    run("aggregate")
    (summary,) = read_jsonl(data / "report_summary.jsonl")
    assert (summary["n_candidates"], summary["n_context_passages"], summary["n_ai_passages"], summary["n_false_candidates"]) == (1, 1, 1, 0)
    assert summary["context_terms"] == {t: 1 for t in passages[1]["matched"]["context"]}
    assert summary["recall_check"] == {"blocks": 0, "by_pattern": {}}
    check = json.loads((data / "recall_check.json").read_text(encoding="utf-8"))
    assert (check["documents"], check["documents_checked"], check["blocks_outside_passages"]) == (1, 1, 0)
    assert (summary["mentions_ai"], summary["ai_as_market_driver"], summary["ai_as_risk"]) == (True, True, False)
    report = (data / "reports" / f"{doc['doc_id']}.md").read_text(encoding="utf-8")
    assert report.startswith("# ACME URANIUM CORP | 10-K | fiscal year 2026")
    assert "> Demand for electricity from AI data centers is growing." in report
    assert "# Context passages: implicit mentions, not classified" in report
    assert passages[1]["text"] in report
    capsys.readouterr()  # the stages print progress; keep it out of the test output


def test_substantiveness_has_five_ordered_levels_and_is_required_for_ai_passages():
    assert taxonomy.SUBSTANTIVENESS_LEVELS == {"boilerplate": 1, "generic": 2, "specific": 3, "detailed": 4, "quantified": 5}
    for level in taxonomy.SUBSTANTIVENESS:
        assert Label(**label_fields(substantiveness=level)).substantiveness == level
        assert f"`{level}`" in taxonomy.codebook()
    with pytest.raises(ValidationError, match="substantiveness is required"):
        Label(**label_fields(substantiveness=None))
    with pytest.raises(ValidationError):
        Label(**label_fields(substantiveness="moderate"))
    with pytest.raises(ValidationError, match="must leave all other label fields empty"):
        Label(passage_id="d1:0-2", ai_reference="none", confidence="high", substantiveness="generic")


def test_adjudicate_takes_the_majority_substantiveness_and_flags_a_three_way_split():
    final, _ = adjudicated(by_coder(
        coded(P1, "a", substantiveness="specific"), coded(P1, "b", substantiveness="specific"), coded(P1, "c", substantiveness="detailed"),
        coded(P2, "a", substantiveness="boilerplate"), coded(P2, "b", substantiveness="specific"), coded(P2, "c", substantiveness="quantified"),
    ))
    p1, p2 = final[P1], final[P2]
    assert p1["substantiveness"] == "specific" and "substantiveness" not in p1["disputed"]
    assert p2["substantiveness"] is None and "substantiveness" in p2["disputed"]


def test_a_quote_that_differs_only_in_quotation_marks_or_dashes_is_stored_as_the_passage_has_it():
    text = "We use generative artificial intelligence (\u201cAI\u201d) tools \u2013 and machine learning (\u201cML\u201d) \u2013 in our operations. It\u2019s new."
    for quote in (
        "generative artificial intelligence (\u2018\u2019AI\u2019\u2019) tools",  # as gemini-2.5-flash returned it
        "generative artificial intelligence (\u2013AI\u2013) tools",
        'generative artificial intelligence ("AI") tools - and machine learning',
    ):
        found = classify._locate(quote, classify._squash(text))
        assert found is not None and found in text and found.startswith("generative artificial intelligence (\u201cAI\u201d) tools")
    assert classify._locate("It's new.", text) == "It\u2019s new."
    assert classify._locate("We use generative artificial intelligence", text) == "We use generative artificial intelligence"
    # any other difference is not a quote
    assert classify._locate("generative AI (\u201cAI\u201d) tools", text) is None
    assert classify._locate("generative artificial intelligence (AI) tools", text) is None
    assert classify._locate("generative artificial intelligence tools", text) is None
    assert classify._locate("  ", text) is None


def test_validate_stores_the_passage_wording_for_a_quote_with_other_quotation_marks():
    passage = {"passage_id": "d1:0-2", "text": "Demand for \u201cAI\u201d data centers is growing."}
    line = json.dumps(label_fields(evidence=["Demand for \u2018\u2019AI\u2019\u2019 data centers is growing."]))
    accepted, problems = classify.validate([line], [passage], "a")
    assert problems == [] and accepted[0]["evidence"] == ["Demand for \u201cAI\u201d data centers is growing."]

    wrong = json.dumps(label_fields(evidence=["Demand for AI data centres is growing."]))
    accepted, problems = classify.validate([wrong], [passage], "a")
    assert accepted == [] and "not a verbatim quote" in problems[0]


# --------------------------------------------------------------------------
# taxonomy v0.6: business functions, governance responses, national security
# --------------------------------------------------------------------------


def test_business_functions_are_given_if_and_only_if_adoption_is_a_role():
    adoption = dict(roles=["adoption"], adoption_stage="deployed")
    label = Label(**label_fields(**adoption, business_functions=["customer_service", "finance"]))
    assert label.business_functions == ["customer_service", "finance"]
    with pytest.raises(ValidationError, match="business_functions must be given if and only if"):
        Label(**label_fields(**adoption, business_functions=[]))
    with pytest.raises(ValidationError, match="business_functions must be given if and only if"):
        Label(**label_fields(roles=["market_driver"], business_functions=["finance"]))
    with pytest.raises(ValidationError):
        Label(**label_fields(**adoption, business_functions=["logistics"]))  # not a value


def test_not_stated_is_the_only_business_function_when_none_is_named():
    adoption = dict(roles=["adoption"], adoption_stage="unclear")
    assert Label(**label_fields(**adoption, business_functions=["not_stated"])).business_functions == ["not_stated"]
    # A named function next to the placeholder: the function is stated, the placeholder goes.
    assert Label(**label_fields(**adoption, business_functions=["not_stated", "operations"])).business_functions == ["operations"]


def test_governance_responses_are_given_if_and_only_if_governance_is_a_role():
    label = Label(**label_fields(frame="governance", roles=["governance"],
                                 governance_responses=["oversight_structure", "policies_processes"]))
    assert label.governance_responses == ["oversight_structure", "policies_processes"]
    with pytest.raises(ValidationError, match="governance_responses must be given if and only if"):
        Label(**label_fields(frame="governance", roles=["governance"], governance_responses=[]))
    with pytest.raises(ValidationError, match="governance_responses must be given if and only if"):
        Label(**label_fields(roles=["market_driver"], governance_responses=["technical_controls"]))


def test_the_six_groups_of_governance_responses_and_the_thirteen_functions_are_in_the_codebook():
    assert list(taxonomy.GOVERNANCE_RESPONSES) == [
        "oversight_structure", "policies_processes", "technical_controls", "third_party_controls",
        "workforce_measures", "transparency_accountability", "other",
    ]
    assert len(taxonomy.BUSINESS_FUNCTIONS) == 13 and "not_stated" in taxonomy.BUSINESS_FUNCTIONS
    text = taxonomy.codebook()
    assert "(`business_functions`)" in text and "(`governance_responses`)" in text
    assert text.index("(`adoption_stage`)") < text.index("(`business_functions`)") < text.index("(`ai_kinds`)")
    for value in [*taxonomy.BUSINESS_FUNCTIONS, *taxonomy.GOVERNANCE_RESPONSES]:
        assert f"- `{value}`: " in text


def test_a_passage_not_about_ai_leaves_the_new_fields_empty():
    none = Label(passage_id="d1:0-2", ai_reference="none", confidence="high")
    assert (none.business_functions, none.governance_responses) == ([], [])
    for field in ("business_functions", "governance_responses"):
        with pytest.raises(ValidationError, match="must leave all other label fields empty"):
            Label(passage_id="d1:0-2", ai_reference="none", confidence="high", **{field: ["other"]})


def test_national_security_is_a_risk_type():
    label = Label(**label_fields(roles=["risk"], risk_types=["national_security", "regulatory_legal"]))
    assert label.risk_types == ["national_security", "regulatory_legal"]
    assert list(taxonomy.RISK_TYPES)[-2:] == ["national_security", "other"]
    assert "export controls" in taxonomy.codebook().split("- `national_security`: ")[1].split("- `other`")[0]


def test_adjudicate_votes_on_the_new_fields_and_clears_them_with_their_role():
    adoption = dict(roles=["market_driver", "adoption"], adoption_stage="deployed")
    final, _ = adjudicated(by_coder(
        # P1: two of three name finance; operations has one vote only.
        coded(P1, "a", **adoption, business_functions=["finance", "operations"]),
        coded(P1, "b", **adoption, business_functions=["finance"]),
        coded(P1, "c", **adoption, business_functions=["not_stated"]),
        # P2: adoption loses the vote, so its functions go with it.
        coded(P2, "a", **adoption, business_functions=["finance"]),
        coded(P2, "b"),
        coded(P2, "c"),
        # P3: governance wins, but no response has a majority.
        coded(P3, "a", roles=["governance"], governance_responses=["oversight_structure"]),
        coded(P3, "b", roles=["governance"], governance_responses=["technical_controls"]),
        coded(P3, "c"),
    ))
    assert final[P1]["business_functions"] == ["finance"] and not final[P1]["needs_review"]
    assert (final[P2]["roles"], final[P2]["business_functions"]) == (["market_driver"], [])
    assert final[P3]["governance_responses"] == [] and "governance_responses" in final[P3]["disputed"]


def test_summarise_counts_the_new_fields_and_the_context_passages():
    passages = [
        passage("d1:0-2", "Item 1"),
        {**passage("d1:5-7", "Item 1A", mention="implicit"), "matched": {"context": ["data center", "nvidia"]},
         "term_groups": {"data center": "compute_infrastructure", "nvidia": "products_vendors"}},
        {**passage("d1:9-9", "Item 7", mention="implicit"), "matched": {"context": ["data center", "truckload"]},
         "term_groups": {"data center": "compute_infrastructure", "truckload": "industry"}},
    ]
    labels = [
        final_label("d1:0-2", "explicit", frame="business", roles=["adoption", "governance"],
                    adoption_stage="deployed", ai_kinds=["generative_llm"],
                    business_functions=["customer_service", "finance"], governance_responses=["policies_processes"]),
    ]

    s = aggregate.summarise({**REPORT, "recall_check": {"blocks": 2, "by_pattern": {"autonomous": 2}}}, passages, labels)

    # Context passages are never labelled and never counted as AI passages.
    assert (s["n_candidates"], s["n_context_passages"], s["n_ai_passages"], s["n_unlabelled"]) == (1, 2, 1, 0)
    assert s["context_terms"] == {"data center": 2, "nvidia": 1, "truckload": 1}
    assert s["context_groups"] == {"compute_infrastructure": 2, "products_vendors": 1, "industry": 1}
    assert s["context_sections"] == {"Item 1A": 1, "Item 7": 1}
    assert s["business_functions"] == {"customer_service": 1, "finance": 1}
    assert s["governance_responses"] == {"policies_processes": 1}
    assert s["recall_check"] == {"blocks": 2, "by_pattern": {"autonomous": 2}}
    assert aggregate.summarise(REPORT, passages, labels)["recall_check"] is None  # document from before the check

    rendered = aggregate.render(
        REPORT,
        [{**p, "section_title": None, "blocks": [0, 2], "text": "T"} for p in passages],
        [{**l, "evidence": [], "notes": [], "disputed": []} for l in labels],
        s,
    )
    assert "- Direct AI mentions (classified): 1, of which about AI: 1" in rendered
    assert "- Context passages (not classified): 2; groups: compute_infrastructure (2), products_vendors (1), industry (1)\n" in rendered
    assert "- Business functions: customer_service (1), finance (1)\n" in rendered
    assert "| functions: customer_service, finance | responses: policies_processes" in rendered
    assert "# Context passages: implicit mentions, not classified" in rendered
    assert rendered.count("**Terms: ") == 2


def test_ai_reference_has_no_implicit_value():
    assert list(taxonomy.AI_REFERENCE) == ["explicit", "none"]
    with pytest.raises(ValidationError):
        Label(**label_fields(ai_reference="implicit"))
    text = taxonomy.codebook()
    assert "`implicit`" not in text
    assert "analytics, data science, automation, algorithm" in text.split("- `explicit`: ")[1].split("- `none`")[0]


def test_ai_kinds_are_a_list_coded_only_when_named_and_unspecified_stands_alone():
    assert list(taxonomy.AI_KINDS) == [
        "traditional_ml", "generative_llm", "computer_vision", "nlp", "recommendation", "agentic", "other",
        "unspecified",
    ]
    label = Label(**label_fields(ai_kinds=["generative_llm", "nlp", "agentic"]))
    assert label.ai_kinds == ["generative_llm", "nlp", "agentic"]
    with pytest.raises(ValidationError, match="ai_kinds and evidence are required"):
        Label(**label_fields(ai_kinds=[]))
    # A named kind next to `unspecified`: the kind is specified, `unspecified` goes.
    assert Label(**label_fields(ai_kinds=["unspecified", "traditional_ml"])).ai_kinds == ["traditional_ml"]
    assert Label(**label_fields(ai_kinds=["unspecified"])).ai_kinds == ["unspecified"]
    with pytest.raises(ValidationError):
        Label(**label_fields(ai_kinds=["generative"]))  # the v0.7 value is gone
    none = Label(passage_id="d1:0-2", ai_reference="none", confidence="high")
    assert none.ai_kinds == []
    text = taxonomy.codebook()
    assert "do not estimate a kind from the context" in text
    assert "`unspecified` only alone" in text and "is dropped on acceptance" in text


def test_adjudicate_votes_per_kind_of_ai():
    final, _ = adjudicated(by_coder(
        coded(P1, "a", ai_kinds=["generative_llm", "agentic"]),
        coded(P1, "b", ai_kinds=["generative_llm"]),
        coded(P1, "c", ai_kinds=["unspecified"]),
    ))
    assert final[P1]["ai_kinds"] == ["generative_llm"] and not final[P1]["needs_review"]


def test_mit_subdomains_are_the_24_of_the_repository_plus_other_and_go_with_risk_or_incident():
    assert len(taxonomy.MIT_SUBDOMAINS) == 25 and list(taxonomy.MIT_SUBDOMAINS)[-1] == "other"
    assert list(taxonomy.MIT_SUBDOMAIN_NUMBERS) == list(taxonomy.MIT_SUBDOMAINS)[:-1]
    assert list(taxonomy.MIT_SUBDOMAIN_NUMBERS.values()) == [
        "1.1", "1.2", "1.3", "2.1", "2.2", "3.1", "3.2", "4.1", "4.2", "4.3", "5.1", "5.2",
        "6.1", "6.2", "6.3", "6.4", "6.5", "6.6", "7.1", "7.2", "7.3", "7.4", "7.5", "7.6",
    ]
    assert taxonomy.MIT_SUBDOMAINS["multi_agent_risks"][0].startswith("7.6 Multi-agent risks.")
    label = Label(**label_fields(roles=["risk"], risk_types=["cybersecurity"], mit_subdomains=["ai_system_security_vulnerabilities_attacks", "fraud_scams_targeted_manipulation"]))
    assert label.mit_subdomains == ["ai_system_security_vulnerabilities_attacks", "fraud_scams_targeted_manipulation"]
    incident = Label(**label_fields(roles=["incident"], mit_subdomains=["compromise_of_privacy"]))
    assert incident.mit_subdomains == ["compromise_of_privacy"] and incident.risk_types == []
    with pytest.raises(ValidationError, match="mit_subdomains must be given if and only if"):
        Label(**label_fields(roles=["risk"], risk_types=["cybersecurity"], mit_subdomains=[]))
    with pytest.raises(ValidationError, match="mit_subdomains must be given if and only if"):
        Label(**label_fields(roles=["adoption"], adoption_stage="deployed", mit_subdomains=["inequality_decline_employment_quality"]))
    with pytest.raises(ValidationError):
        Label(**label_fields(roles=["risk"], risk_types=["other"], mit_subdomains=["8.1"]))
    assert Label(passage_id="d1:0-2", ai_reference="none", confidence="high").mit_subdomains == []
    text = taxonomy.codebook()
    assert "(`mit_subdomains`)" in text and "- `multi_agent_risks`: 7.6 Multi-agent risks." in text and "Typical, not binding" in text
    assert text.index("(`risk_types`)") < text.index("(`mit_subdomains`)") < text.index("(`adoption_stage`)")
    assert set(taxonomy.RISK_TYPE_SUBDOMAINS) == set(taxonomy.RISK_TYPES)
    assert all(v in taxonomy.MIT_SUBDOMAINS for vs in taxonomy.RISK_TYPE_SUBDOMAINS.values() for v in vs)
    # The firm's competition and its compliance are not MIT's 6.4 and 6.5; the guidance does not point there.
    assert "ai_race_unsafe_deployment" not in taxonomy.RISK_TYPE_SUBDOMAINS["strategic_competitive"]
    assert "regulation_lagging_behind_ai" not in taxonomy.RISK_TYPE_SUBDOMAINS["regulatory_legal"]
    assert "is not this harm" in taxonomy.MIT_SUBDOMAINS["ai_race_unsafe_deployment"][1][1]
    assert "is not this harm" in taxonomy.MIT_SUBDOMAINS["regulation_lagging_behind_ai"][1][1]


def test_adjudicate_votes_per_subdomain_and_clears_them_without_risk_or_incident():
    risk = dict(roles=["risk"], risk_types=["cybersecurity"])
    final, _ = adjudicated(by_coder(
        coded(P1, "a", **risk, mit_subdomains=["ai_system_security_vulnerabilities_attacks", "fraud_scams_targeted_manipulation"]),
        coded(P1, "b", **risk, mit_subdomains=["ai_system_security_vulnerabilities_attacks"]),
        coded(P1, "c", **risk, mit_subdomains=["other"]),
        # P2: risk loses the vote, so the subdomains go with it.
        coded(P2, "a", **risk, mit_subdomains=["ai_system_security_vulnerabilities_attacks"]),
        coded(P2, "b"),
        coded(P2, "c"),
        # P3: risk wins, but no subdomain has a majority.
        coded(P3, "a", **risk, mit_subdomains=["ai_system_security_vulnerabilities_attacks"]),
        coded(P3, "b", **risk, mit_subdomains=["cyberattacks_weapons_mass_harm"]),
        coded(P3, "c", **risk, mit_subdomains=["fraud_scams_targeted_manipulation"]),
    ))
    assert final[P1]["mit_subdomains"] == ["ai_system_security_vulnerabilities_attacks"] and not final[P1]["needs_review"]
    assert (final[P2]["roles"], final[P2]["mit_subdomains"]) == (["market_driver"], [])
    assert final[P3]["mit_subdomains"] == [] and "mit_subdomains" in final[P3]["disputed"]


def test_summarise_counts_the_subdomains():
    passages = [passage("d1:0-2", "Item 1A"), passage("d1:5-7", "Item 1A")]
    labels = [
        final_label("d1:0-2", "explicit", frame="risk_factor", roles=["risk"], risk_types=["cybersecurity"],
                    ai_kinds=["unspecified"], mit_subdomains=["ai_system_security_vulnerabilities_attacks", "fraud_scams_targeted_manipulation"]),
        final_label("d1:5-7", "explicit", frame="risk_factor", roles=["risk"], risk_types=["workforce"],
                    ai_kinds=["unspecified"], mit_subdomains=["inequality_decline_employment_quality"]),
    ]
    s = aggregate.summarise(REPORT, passages, labels)
    assert s["mit_subdomains"] == {"ai_system_security_vulnerabilities_attacks": 1, "fraud_scams_targeted_manipulation": 1, "inequality_decline_employment_quality": 1}
    rendered = aggregate.render(REPORT, [{**p, "section_title": None, "blocks": [0, 2], "text": "T"} for p in passages],
                                [{**l, "evidence": [], "notes": [], "disputed": []} for l in labels], s)
    assert "- MIT subdomains: ai_system_security_vulnerabilities_attacks (1), fraud_scams_targeted_manipulation (1), inequality_decline_employment_quality (1)\n" in rendered and "| mit: ai_system_security_vulnerabilities_attacks, fraud_scams_targeted_manipulation" in rendered

