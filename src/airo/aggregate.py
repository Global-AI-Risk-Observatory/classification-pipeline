"""Stage 4: passage labels -> one summary row per report, plus a readable view."""

from __future__ import annotations

from collections import Counter

from .taxonomy import DISCLOSURE_TRAITS


def summarise(doc: dict, passages: list[dict], labels: list[dict]) -> dict:
    """Roll the final labels of one document up to report level.

    `passages` are all candidates of the document; only direct mentions carry
    labels, implicit mentions are counted as hints.
    """
    label_by_id = {l["passage_id"]: l for l in labels}
    hints = [p for p in passages if p["mention"] == "implicit"]
    passages = [p for p in passages if p["mention"] == "direct"]
    mine = [(p, label_by_id[p["passage_id"]]) for p in passages if p["passage_id"] in label_by_id]
    about_ai = [(p, l) for p, l in mine if l["ai_reference"] in ("explicit", "implicit")]

    def count(field: str) -> dict:
        c = Counter()
        for _, l in about_ai:
            value = l[field]
            c.update(value if isinstance(value, list) else [value] if value else [])
        return dict(c.most_common())

    roles = count("roles")
    traits = count("disclosure_traits")
    n_ai = len(about_ai)
    return {
        "doc_id": doc["doc_id"],
        "company": doc["company"],
        "form": doc["form"],
        "fiscal_year": doc["fiscal_year"],
        "n_words": doc["n_words"],
        "n_candidates": len(passages),
        "n_hints": len(hints),
        "n_unlabelled": len(passages) - len(mine),
        "n_ai_passages": n_ai,
        "n_false_candidates": sum(l["ai_reference"] == "none" for _, l in mine),
        "n_needs_review": sum(l["needs_review"] for _, l in mine),
        "ai_reference": dict(Counter(l["ai_reference"] or "disputed" for _, l in mine)),
        "frames": count("frame"),
        "roles": roles,
        "risk_types": count("risk_types"),
        "adoption_stage": count("adoption_stage"),
        "ai_kind": count("ai_kind"),
        "substantiveness": count("substantiveness"),
        "disclosure_traits": traits,
        # Analogue of PRISON's activation rate: share of AI passages with at least one trait, and per trait.
        "trait_activation_rate": round(sum(bool(l["disclosure_traits"]) for _, l in about_ai) / n_ai, 3)
        if n_ai
        else None,
        "trait_rates": {t: round(traits.get(t, 0) / n_ai, 3) for t in DISCLOSURE_TRAITS} if n_ai else {},
        "sections": dict(Counter(p["section"] or "unknown" for p, _ in about_ai).most_common()),
        "entities": sorted({e for _, l in about_ai for e in l["entities"]}),
        "hint_sections": dict(Counter(p["section"] or "unknown" for p in hints).most_common()),
        "mentions_ai": bool(about_ai),
        "ai_as_market_driver": "market_driver" in roles,
        "ai_adoption": "adoption" in roles,
        "ai_as_risk": "risk" in roles,
    }


def render(doc: dict, passages: list[dict], labels: list[dict], summary: dict) -> str:
    """Markdown view of one report: summary, every direct mention with its labels,
    then the implicit mentions as hints with their text."""
    label_by_id = {l["passage_id"]: l for l in labels}
    hints = [p for p in passages if p["mention"] == "implicit"]
    passages = [p for p in passages if p["mention"] == "direct"]

    def fmt(d: dict) -> str:
        return ", ".join(f"{k} ({v})" for k, v in d.items()) or "none"

    activation = summary["trait_activation_rate"]
    activation_line = "n/a" if activation is None else f"{activation} ({fmt(summary['trait_rates'])})"
    lines = [
        f"# {doc['company']} | {doc['form']} | fiscal year {doc['fiscal_year']}",
        "",
        f"- Report length: {doc['n_words']:,} words",
        f"- Direct AI mentions (classified): {summary['n_candidates']}, of which about AI: {summary['n_ai_passages']}, "
        f"false candidates: {summary['n_false_candidates']}, flagged for review: {summary['n_needs_review']}",
        f"- Implicit mentions (hints, not classified): {summary['n_hints']}",
        f"- Frames: {fmt(summary['frames'])}",
        f"- Roles: {fmt(summary['roles'])}",
        f"- Risk types: {fmt(summary['risk_types'])}",
        f"- Adoption stage: {fmt(summary['adoption_stage'])}",
        f"- Kind of AI: {fmt(summary['ai_kind'])}",
        f"- Substantiveness: {fmt(summary['substantiveness'])}",
        f"- Disclosure traits: {fmt(summary['disclosure_traits'])}",
        f"- Trait activation rate: {activation_line}",
        f"- Sections: {fmt(summary['sections'])}",
        f"- Named entities: {', '.join(summary['entities']) or 'none'}",
        "",
    ]
    for p in passages:
        l = label_by_id.get(p["passage_id"])
        where = " ".join(x for x in (p["section"], p["section_title"]) if x) or "unknown section"
        lines += [f"## {where} (blocks {p['blocks'][0]}-{p['blocks'][1]})", ""]
        if l is None:
            lines += ["**Not labelled.**", ""]
        else:
            tags = [f"AI reference: {l['ai_reference'] or 'disputed'}"]
            if l["frame"]:
                tags.append(f"frame: {l['frame']}")
            if l["roles"]:
                tags.append("roles: " + ", ".join(l["roles"]))
            if l["risk_types"]:
                tags.append("risk: " + ", ".join(l["risk_types"]))
            if l["adoption_stage"]:
                tags.append(f"adoption: {l['adoption_stage']}")
            if l["ai_kind"]:
                tags.append(f"kind: {l['ai_kind']}")
            if l["substantiveness"]:
                tags.append(f"substantiveness: {l['substantiveness']}")
            if l["disclosure_traits"]:
                tags.append("traits: " + ", ".join(l["disclosure_traits"]))
            if l["needs_review"]:
                tags.append("NEEDS REVIEW: " + ", ".join(l["disputed"]))
            lines += ["**" + " | ".join(tags) + "**", ""]
            for quote in l["evidence"]:  # one blockquote per quote
                lines += [f"> {quote}", ""]
            lines += [f"- Note ({n})" for n in l["notes"]] + ([""] if l["notes"] else [])
        lines += ["<details><summary>Passage</summary>", "", p["text"], "", "</details>", ""]
    if hints:
        lines += ["# Hints: implicit mentions, not classified", ""]
        for p in hints:
            where = " ".join(x for x in (p["section"], p["section_title"]) if x) or "unknown section"
            terms = ", ".join(
                f"{t} ({', '.join(p.get('matched_text', {}).get(t, []))})" if p.get("matched_text", {}).get(t) else t
                for t in p["matched"].get("context", [])
            )
            lines += [f"## {where} (blocks {p['blocks'][0]}-{p['blocks'][1]})", "", f"**Terms: {terms}**", "", p["text"], ""]
    return "\n".join(lines)
