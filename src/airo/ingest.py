"""Stage 1: filing (Markdown from the data provider, or HTML / inline XBRL) -> one document record + ordered text blocks.

A document is identified by the hash of its normalised text, not of its bytes:
the same filing downloaded twice differs in raw bytes (e.g. Cloudflare rewrites
e-mail addresses with a per-request token) but must be processed only once.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Iterator

import lxml.html

_WS = re.compile(r"[\s ﻿​]+")
_HIDDEN = re.compile(r"display\s*:\s*none", re.I)
# "Item 1A. Risk Factors" as a title-only block: the item number, then nothing
# or a delimiter and the title. "Item 7 of this report ..." and "Item 405 of
# Regulation S-K ..." are running sentences, not headings.
_ITEM = re.compile(r"^Item\s+(\d{1,2}[A-C]?(?:\(T\))?)\s*(?:[.:|–—-]\s*(.*))?$", re.I)
# A table-of-contents row matches _ITEM too, but ends in a page-number cell.
_TOC_PAGE = re.compile(r"\| \d+$")
# Page furniture: a block that is only a page number ("12", "F-7", "Page 12",
# "iv") or the "Table of Contents" link printed on every page.
_FURNITURE = re.compile(r"^(?:(?:Page\s+)?(?:[A-Z]-)?(?:\d{1,4}|[ivx]{1,5})|Table of Contents)$", re.I)
_HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_TEXT_TAGS = _HEADINGS | {"p", "li"}
_BLOCK_TAGS = _TEXT_TAGS | {"div", "table", "tr", "ul", "ol"}
_EMPHASIS = ("b", "strong", "i", "em")
_MAX_HEADING_CHARS = 300

# Markdown as the data provider renders a filing: one paragraph per line, blank
# lines between them, tables as pipe tables, headings as fully bold paragraphs.
_MD_RULE = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?$")
_MD_HASH = re.compile(r"^#{1,6}\s+")
_MD_BULLET = re.compile(r"^(?:[•·▪◦‣-]|\d{1,3}[.)])\s+")
_MD_BOLD = re.compile(r"^(\*\*\*?|__)(?=\S).+(?<=\S)\1$")
_MD_MARKS = re.compile(r"\*{1,3}|_{2,3}")
# Cover-page lines of an SEC annual report; a Markdown filing carries no XBRL facts.
_MD_FORM = re.compile(r"^FORM\s+(\d{1,2}-[A-Z]{1,2}(?:/A)?)$", re.I)
_MD_PERIOD = re.compile(r"^For the fiscal year ended\s+([A-Za-z]+)\s+(\d{1,2})\s*,\s*(\d{4})\b", re.I)
_MD_COVER_BLOCKS = 60

# Inline XBRL "document and entity information" facts -> document fields.
_DEI = {
    "company": "dei:EntityRegistrantName",
    "cik": "dei:EntityCentralIndexKey",
    "form": "dei:DocumentType",
    "period_end": "dei:DocumentPeriodEndDate",
    "fiscal_year": "dei:DocumentFiscalYearFocus",
    "ticker": "dei:TradingSymbol",
    "exchange": "dei:SecurityExchangeName",
    "filer_category": "dei:EntityFilerCategory",
}


def _norm(text: str) -> str:
    return _WS.sub(" ", text).strip()


def _metadata(root) -> dict:
    meta = {}
    for field, name in _DEI.items():
        hits = root.xpath("//*[@name=$n]", n=name)
        meta[field] = _norm(hits[0].text_content()) if hits else None
    if meta["period_end"]:
        for fmt in ("%B %d, %Y", "%Y-%m-%d"):
            try:
                meta["period_end"] = datetime.strptime(meta["period_end"], fmt).date().isoformat()
                break
            except ValueError:
                pass
    if meta["fiscal_year"] and meta["fiscal_year"].isdigit():
        meta["fiscal_year"] = int(meta["fiscal_year"])
    return meta


def _strip_invisible(root) -> None:
    drop = [
        el
        for el in root.iter()
        if isinstance(el.tag, str)
        and (el.tag in ("script", "style", "ix:header") or _HIDDEN.search(el.get("style") or ""))
    ]
    for el in drop:
        if el.getparent() is not None:
            el.drop_tree()
    for br in root.iter("br"):
        br.tail = " " + (br.tail or "")


def _is_emphasis_only(el, text: str) -> bool:
    """True for a short paragraph that is entirely bold/italic (a sub-heading)."""
    if len(text) > _MAX_HEADING_CHARS:
        return False
    emphasised = _norm(" ".join(e.text_content() for e in el.iter(*_EMPHASIS)))
    return bool(emphasised) and len(emphasised) >= len(text.replace(" ", "")) * 0.95


def _own_text(el) -> str:
    """Text of `el` without its block-level descendants."""
    parts = [el.text or ""]
    for child in el:
        if isinstance(child.tag, str):
            parts.append(" " if child.tag in _BLOCK_TAGS else _own_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


def _raw_blocks(body) -> Iterator[tuple[str, str, int | None]]:
    """Yield (kind, text, level) in document order. kind: heading | text | row | furniture.

    `level` is 1-6 for an <h1>-<h6> heading and None for every other block.
    """
    for el in body.iter():
        tag = el.tag
        if not isinstance(tag, str):
            continue
        if tag == "tr":
            if next(el.iterdescendants("table"), None) is not None:
                continue  # layout wrapper: its inner rows and paragraphs are emitted
            cells = [_norm(c.text_content()) for c in el if c.tag in ("td", "th")]
            text, kind = " | ".join(c for c in cells if c), "row"
        elif tag in _TEXT_TAGS or tag == "div":
            row = next(el.iterancestors("tr"), None)
            if row is not None and next(row.iterdescendants("table"), None) is None:
                continue  # already covered by its table row
            nested = tag in ("div", "li") and any(
                isinstance(d.tag, str) and d.tag in _BLOCK_TAGS for d in el.iterdescendants()
            )
            if nested and tag == "div":
                continue  # container; children are emitted
            if nested:  # list item: its children are emitted, only its own text is left
                text, kind = _norm(_own_text(el)), "text"
            else:
                text = _norm(el.text_content())
                kind = "heading" if tag in _HEADINGS or _is_emphasis_only(el, text) else "text"
        else:
            continue
        level = int(tag[1]) if tag in _HEADINGS else None
        if _FURNITURE.match(text):
            kind = "furniture"  # kept so the text hash is stable; retrieve skips it
        if text:
            yield kind, text, level if kind == "heading" else None


def _md_blocks(text: str) -> Iterator[tuple[str, str, int | None]]:
    """Yield (kind, text, level) per paragraph or table row of a Markdown filing, in document order.

    `level` is the number of `#` of a Markdown heading and None for every other block,
    a bold sub-heading included.
    """
    for line in text.splitlines():
        line = line.strip()
        if not line or _MD_RULE.match(line):
            continue  # blank line, or the rule under a table's header row
        level = None
        if line.startswith("|"):
            cells = [_norm(_MD_MARKS.sub("", c)) for c in line.strip("|").split("|")]
            text_, kind = " | ".join(c for c in cells if c), "row"
        elif _MD_HASH.match(line):
            text_, kind = _norm(_MD_MARKS.sub("", _MD_HASH.sub("", line))), "heading"
            level = len(line) - len(line.lstrip("#"))
        else:
            body = _MD_BULLET.sub("", line)
            text_ = _norm(_MD_MARKS.sub("", body))
            # A short paragraph that is bold from end to end is a sub-heading.
            kind = "heading" if body == line and _MD_BOLD.match(line) and len(text_) <= _MAX_HEADING_CHARS else "text"
        if _FURNITURE.match(text_):
            kind = "furniture"
        if text_:
            yield kind, text_, level if kind == "heading" else None


def _md_metadata(blocks: list[dict]) -> dict:
    """Form, fiscal period, ticker and exchange from the cover page; everything else comes from the manifest."""
    meta = dict.fromkeys(_DEI)
    for b in blocks[:_MD_COVER_BLOCKS]:
        form, period = _MD_FORM.match(b["text"]), _MD_PERIOD.match(b["text"])
        if form and not meta["form"]:
            meta["form"] = form.group(1).upper()
        if period and not meta["period_end"]:
            try:
                day = datetime.strptime(" ".join(period.groups()), "%B %d %Y").date()
            except ValueError:
                continue
            # The fiscal year is taken to be the year the period ends in.
            meta["period_end"], meta["fiscal_year"] = day.isoformat(), day.year
    # "Title of each class | Trading Symbol(s) | Name of each exchange ...": the first security listed.
    rows = [b["text"].split(" | ") for b in blocks[:_MD_COVER_BLOCKS] if b["kind"] == "row"]
    for header, first in zip(rows, rows[1:]):
        symbol = [i for i, c in enumerate(header) if "trading symbol" in c.lower()]
        exchange = [i for i, c in enumerate(header) if "exchange" in c.lower()]
        if symbol and exchange and len(first) == len(header):
            if first[symbol[0]].lower() not in ("none", "n/a"):
                meta["ticker"], meta["exchange"] = first[symbol[0]], first[exchange[0]]
            break
    return meta


def cover_metadata(text: str) -> dict:
    """What the cover page of a Markdown filing states: form, fiscal period, ticker, exchange (None where absent)."""
    return _md_metadata(_assemble(_md_blocks(text))[0])


SECTION_MODES = ("items", "items_or_headings")
# A chapter level must open at least this many headings, so that a title heading printed once
# at the top of a report does not become the only section of the whole report.
_MIN_CHAPTERS = 3
_MAX_SECTION_CHARS = 120


def chapter_level(levels: list[int]) -> int | None:
    """The heading level that divides a filing into chapters: the shallowest one used at least `_MIN_CHAPTERS` times."""
    counts = {lv: levels.count(lv) for lv in set(levels)}
    return min((lv for lv, n in counts.items() if n >= _MIN_CHAPTERS), default=None)


def _chapters(blocks: list[dict], levels: list[int | None]) -> dict:
    """Make each chapter heading (see `chapter_level`) open a section; for a filing without SEC Items."""
    level = chapter_level([lv for lv in levels if lv is not None])
    sections: dict[str, dict] = {}
    section = None
    for b, lv in zip(blocks, levels):
        if level is not None and lv == level:
            section = b["text"][:_MAX_SECTION_CHARS]
            sections.setdefault(section, {"title": None, "n_words": 0})
        b["section"] = section
        if section:
            sections[section]["n_words"] += len(b["text"].split())
    return sections


def _assemble(raw: Iterator[tuple[str, str, int | None]], sections_mode: str = "items") -> tuple[list[dict], dict]:
    """Number the blocks and attach the section and the nearest heading to each.

    The section is the SEC Item a block stands under. In `sections_mode` "items_or_headings",
    a filing without any SEC Item is divided by its chapter headings instead (`_chapters`).
    """
    if sections_mode not in SECTION_MODES:
        raise ValueError(f"sections_mode must be one of {SECTION_MODES}, not {sections_mode!r}")
    blocks, sections, levels = [], {}, []
    section = heading = None
    for kind, text, level in raw:
        item = _ITEM.match(text) if len(text) <= _MAX_HEADING_CHARS else None
        if item and kind == "row" and _TOC_PAGE.search(text):
            item = None  # contents entry; the real heading further down opens the section
        if item:
            section = f"Item {item.group(1).upper()}"
            title = (item.group(2) or "").strip(" |.") or None
            sections[section] = {"title": title, "n_words": 0}
            heading, kind = None, "heading"
        elif kind == "heading":
            heading = text
        if section:
            sections[section]["n_words"] += len(text.split())
        blocks.append(
            {"i": len(blocks), "kind": kind, "section": section, "heading": heading, "text": text}
        )
        levels.append(level if kind == "heading" else None)
    if sections_mode == "items_or_headings" and not sections:
        sections = _chapters(blocks, levels)
    return blocks, sections


def _document(path: Path, meta: dict, blocks: list[dict], sections: dict, body_words: int) -> dict:
    full_text = "\n".join(b["text"] for b in blocks)
    n_words = len(full_text.replace(" | ", " ").split())  # cell separators are not words
    return {
        "doc_id": hashlib.sha256(full_text.encode("utf-8")).hexdigest()[:16],
        "source_files": [Path(path).name],
        **meta,
        "n_blocks": len(blocks),
        "n_words": n_words,
        # Share of the visible body text that ended up in blocks; a low value
        # means the block walker missed markup this filer uses.
        "text_coverage": round(n_words / body_words, 3) if body_words else 0.0,
        "sections": sections,
    }


def parse_markdown(path: Path, sections_mode: str = "items") -> tuple[dict, list[dict]]:
    """Parse one Markdown filing into (document record, blocks); `sections_mode` as in `_assemble`."""
    text = Path(path).read_text(encoding="utf-8")
    blocks, sections = _assemble(_md_blocks(text), sections_mode)
    body_words = len(_MD_MARKS.sub("", "\n".join(l for l in text.splitlines() if not _MD_RULE.match(l.strip()))).replace("|", " ").split())
    return _document(path, _md_metadata(blocks), blocks, sections, body_words), blocks


def parse(path: Path, sections_mode: str = "items") -> tuple[dict, list[dict]]:
    """Parse one filing into (document record, blocks). `.md` is read as Markdown, anything else as HTML.

    `sections_mode` is the filing's region's `sections` (see airo.regions); the default is the US behavior.
    """
    if Path(path).suffix.lower() == ".md":
        return parse_markdown(path, sections_mode)
    root = lxml.html.fromstring(Path(path).read_bytes())
    meta = _metadata(root)
    _strip_invisible(root)
    body = root.find(".//body")
    if body is None:
        body = root

    blocks, sections = _assemble(_raw_blocks(body), sections_mode)
    # text_content() glues "<td>a</td><td>b</td>" into one word; blocks and cells end a word.
    for el in body.iter(*_BLOCK_TAGS, "td", "th"):
        el.text, el.tail = " " + (el.text or ""), " " + (el.tail or "")
    body_words = len(_norm(body.text_content()).split())
    return _document(path, meta, blocks, sections, body_words), blocks


def ingest(paths: list[Path]) -> tuple[list[dict], dict[str, list[dict]]]:
    """Parse many filings, collapsing files with identical text into one document."""
    docs: dict[str, dict] = {}
    blocks: dict[str, list[dict]] = {}
    for path in sorted(paths):
        doc, doc_blocks = parse(path)
        if doc["doc_id"] in docs:
            docs[doc["doc_id"]]["source_files"].append(Path(path).name)
        else:
            docs[doc["doc_id"]] = doc
            blocks[doc["doc_id"]] = doc_blocks
    return list(docs.values()), blocks
