"""Stage 2: blocks -> candidate passages.

Cheap lexical recall step. Only passages found here are sent to the (expensive)
classifier, so a report with no hit costs no model call at all. Precision is the
classifier's job: it can label a candidate as not about AI.

The vocabulary comes from the glossaries (see glossary.py): the core AI list
plus the glossary of the company's industry.
"""

from __future__ import annotations

from .glossary import Matcher, load

# Every passage is one of two kinds of mention:
#   "direct"    at least one ai-tier term: a candidate AI statement, goes to the
#               classifier, which confirms it (`explicit`) or rejects it (`none`);
#   "implicit"  context-tier terms only: context around AI (data centres,
#               industry lingo, euphemisms), not an AI statement. Kept, counted per
#               term and group, shown in the report; never sent to the classifier.
MENTIONS = ("direct", "implicit")


def _extend(blocks: list[dict], i: int, step: int, context: int) -> int:
    """Index of the outermost block a window around hit `i` takes in direction `step`.

    Takes up to `context` real blocks within the hit's section. Page furniture
    (page numbers, "Table of Contents") does not count and is stepped over; a
    heading after the hit starts the next topic and ends the window, while a
    heading before it may be taken as its title.
    """
    section, end, taken = blocks[i]["section"], i, 0
    k = i + step
    while taken < context and 0 <= k < len(blocks) and blocks[k]["section"] == section:
        kind = blocks[k]["kind"]
        if step > 0 and kind == "heading":
            break
        if kind != "furniture":
            end, taken = k, taken + 1
        k += step
    return end


def passages(
    doc: dict,
    blocks: list[dict],
    context: int = 1,
    matcher: Matcher | None = None,
) -> list[dict]:
    """Group hit blocks with `context` neighbours on each side into passages.

    Windows never cross a section boundary; overlapping or touching windows merge.
    Page furniture never hits and is left out of the passage text. Each passage
    carries `mention`: "direct" or "implicit" (see MENTIONS).
    """
    matcher = matcher or load(doc.get("isic_class"))
    hits = {
        b["i"]: terms
        for b in blocks
        if b["kind"] != "furniture" and (terms := matcher.find_detailed(b["text"]))
    }
    windows: list[list[int]] = []
    for i in sorted(hits):
        section = blocks[i]["section"]
        start, end = _extend(blocks, i, -1, context), _extend(blocks, i, 1, context)
        if windows and start <= windows[-1][1] + 1 and blocks[windows[-1][1]]["section"] == section:
            windows[-1][1] = max(windows[-1][1], end)
        else:
            windows.append([start, end])

    out = []
    for start, end in windows:
        hit_blocks = [i for i in range(start, end + 1) if i in hits]
        matched: dict[str, list[str]] = {}
        wordings: dict[str, list[str]] = {}  # canonical term -> wordings found
        for i in hit_blocks:
            for tier, terms in hits[i].items():
                matched[tier] = sorted(set(matched.get(tier, [])) | set(terms))
                for term, found in terms.items():
                    wordings[term] = sorted(set(wordings.get(term, [])) | set(found))
        first = blocks[hit_blocks[0]]
        out.append(
            {
                "passage_id": f"{doc['doc_id']}:{start}-{end}",
                "doc_id": doc["doc_id"],
                "section": first["section"],
                "section_title": (doc["sections"].get(first["section"]) or {}).get("title"),
                "heading": first["heading"],
                "blocks": [start, end],
                "hit_blocks": hit_blocks,
                "glossaries": matcher.sources,
                "mention": "direct" if "ai" in matched else "implicit",
                "matched": matched,
                "matched_text": wordings,
                "term_groups": {term: matcher.groups.get(term, "industry") for term in wordings},
                "text": "\n\n".join(
                    blocks[i]["text"]
                    for i in range(start, end + 1)
                    if blocks[i]["kind"] != "furniture"
                ),
            }
        )
    return out
