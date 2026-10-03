"""Stage 1: filing (HTML / inline XBRL) -> one document record + ordered text blocks.

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


def _raw_blocks(body) -> Iterator[tuple[str, str]]:
    """Yield (kind, text) in document order. kind: heading | text | row | furniture."""
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
        if _FURNITURE.match(text):
            kind = "furniture"  # kept so the text hash is stable; retrieve skips it
        if text:
            yield kind, text


def parse(path: Path) -> tuple[dict, list[dict]]:
    """Parse one filing into (document record, blocks)."""
    root = lxml.html.fromstring(Path(path).read_bytes())
    meta = _metadata(root)
    _strip_invisible(root)
    body = root.find(".//body")
    if body is None:
        body = root

    blocks, sections = [], {}
    section = heading = None
    for kind, text in _raw_blocks(body):
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

    full_text = "\n".join(b["text"] for b in blocks)
    n_words = len(full_text.replace(" | ", " ").split())  # cell separators are not words
    # text_content() glues "<td>a</td><td>b</td>" into one word; blocks and cells end a word.
    for el in body.iter(*_BLOCK_TAGS, "td", "th"):
        el.text, el.tail = " " + (el.text or ""), " " + (el.tail or "")
    body_words = len(_norm(body.text_content()).split())
    doc = {
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
    return doc, blocks


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
