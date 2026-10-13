"""Stage 3: candidate passages -> labels.

The stage is defined by its two files, not by who does the coding:
  tasks.jsonl  (passage + document context)  ->  labels/<coder>.jsonl  (one Label per passage)
A coder can be a human, an agent, or a batch job against a model API. Every
returned label is validated against the schema before it is accepted, and
several coders on the same tasks are reconciled by majority vote.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from itertools import combinations

from pydantic import ValidationError

from .taxonomy import TAXONOMY_VERSION, Label

_WS = re.compile(r"\s+")
_SINGLE = ("ai_reference", "frame", "adoption_stage", "ai_kind", "substantiveness")
_MULTI = ("roles", "risk_types", "business_functions", "governance_responses", "disclosure_traits")


def tasks(docs: list[dict], passages: list[dict]) -> list[dict]:
    by_id = {d["doc_id"]: d for d in docs}
    out = []
    for p in passages:
        d = by_id[p["doc_id"]]
        out.append(
            {
                "passage_id": p["passage_id"],
                "company": d["company"],
                "form": d["form"],
                "fiscal_year": d["fiscal_year"],
                "section": " ".join(x for x in (p["section"], p["section_title"]) if x) or None,
                "heading": p["heading"],
                "mention": p["mention"],
                "matched_terms": p["matched"],
                "text": p["text"],
            }
        )
    return out


def _squash(text: str) -> str:
    return _WS.sub(" ", text).strip()


# Quotation marks, apostrophes and dashes in all their typographic forms. A model
# asked for JSON tends to return other ones than the passage has.
_MARKS = re.compile("[\"'`\u00b4\u2018-\u201f\u2010-\u2015\u2212-]+")


def _locate(quote: str, text: str) -> str | None:
    """The stretch of `text` that `quote` cites, or None if it cites none.

    `text` is a squashed passage. A quote is found if it is in the passage as it
    stands, or if it differs from a stretch of the passage only in which
    quotation marks, apostrophes or dashes stand where the passage has some
    (`("AI")` for the passage's curly-quoted one). The stretch is returned in the
    passage's own characters; any other difference is not a quote.
    """
    quote = _squash(quote)
    if not quote or quote in text:
        return quote or None
    plain, starts, ends = [], [], []  # `text` with every run of marks as one mark, and where each character came from
    pos = 0
    for m in _MARKS.finditer(text):
        for i in range(pos, m.start()):
            plain.append(text[i]); starts.append(i); ends.append(i + 1)
        plain.append('"'); starts.append(m.start()); ends.append(m.end())
        pos = m.end()
    for i in range(pos, len(text)):
        plain.append(text[i]); starts.append(i); ends.append(i + 1)
    wanted = _MARKS.sub('"', quote)
    at = "".join(plain).find(wanted)
    return text[starts[at] : ends[at + len(wanted) - 1]] if at >= 0 else None


def _reason(e: Exception) -> str:
    """Why a line was rejected. For a schema violation: the field and the rule that failed."""
    if not isinstance(e, ValidationError):
        return str(e)
    # loc is empty for the cross-field rules of Label, whose message names the fields itself.
    return "; ".join(
        ".".join(map(str, err["loc"])) + ": " + err["msg"] if err["loc"] else err["msg"] for err in e.errors()
    )


def validate(raw_lines: list[str], passages: list[dict], coder: str) -> tuple[list[dict], list[str]]:
    """Check a coder's JSONL against the schema and the task list.

    Returns (accepted labels, problems). A label is rejected if it is not valid
    JSON, breaks the schema, names an unknown passage, or quotes evidence that
    is not in the passage (every quote in the list is checked). Missing and
    duplicate passages are reported too.

    A quote that differs from the passage only in its quotation marks,
    apostrophes or dashes is accepted and stored as the passage has it (see
    `_locate`), so stored evidence is always a verbatim stretch of the passage.
    """
    text_by_id = {p["passage_id"]: _squash(p["text"]) for p in passages}
    accepted: dict[str, dict] = {}
    problems = []
    for n, line in enumerate(raw_lines, 1):
        if not line.strip():
            continue
        try:
            label = Label.model_validate(json.loads(line))
        except (json.JSONDecodeError, ValidationError) as e:
            problems.append(f"line {n}: {_reason(e)}")
            continue
        pid = label.passage_id
        if pid not in text_by_id:
            problems.append(f"line {n}: unknown passage_id {pid}")
        elif pid in accepted:
            problems.append(f"line {n}: duplicate label for {pid}")
        elif bad := [i for i, q in enumerate(label.evidence) if _locate(q, text_by_id[pid]) is None]:
            problems.append(f"line {n}: evidence[{', '.join(map(str, bad))}] is not a verbatim quote from {pid}")
        else:
            # A quote found as it stands is kept as the coder wrote it; one found by its wording is replaced by the passage's.
            evidence = [q if _squash(q) in text_by_id[pid] else _locate(q, text_by_id[pid]) for q in label.evidence]
            accepted[pid] = {**label.model_dump(), "evidence": evidence, "coder": coder, "taxonomy_version": TAXONOMY_VERSION}
    problems += [f"missing label for {pid}" for pid in text_by_id if pid not in accepted]
    return list(accepted.values()), problems


def _vote(values: list, n_coders: int) -> tuple:
    """(majority value, True), or (None, False) if no value has more than half the votes.

    The flag tells "no majority" apart from a majority for None (an empty field).
    """
    value, count = Counter(values).most_common(1)[0]
    return (value, True) if count > n_coders / 2 else (None, False)


def adjudicate(labels_by_coder: dict[str, list[dict]]) -> tuple[list[dict], dict]:
    """Reconcile several coders' labels per passage by majority vote.

    Returns (final labels, agreement report). A passage is flagged
    `needs_review` when a field has no majority or a coder's label is missing.
    Agreement is the share of passages on which all coders gave the same value.
    """
    coders = sorted(labels_by_coder)
    n = len(coders)
    by_passage: dict[str, dict[str, dict]] = {}
    for coder in coders:
        for label in labels_by_coder[coder]:
            by_passage.setdefault(label["passage_id"], {})[coder] = label

    final = []
    unanimous = Counter()
    pair_agree = Counter()
    for pid in sorted(by_passage, key=lambda x: (x.split(":")[0], int(x.split(":")[1].split("-")[0]))):
        got = by_passage[pid]
        votes = list(got.values())
        disputed = [] if len(votes) == n else ["missing_coder"]
        out = {"passage_id": pid, "taxonomy_version": TAXONOMY_VERSION, "coders": sorted(got)}

        for field in _SINGLE:
            values = [v[field] for v in votes]
            out[field], decided = _vote(values, n)
            if len(set(values)) == 1:
                unanimous[field] += 1
            elif not decided:
                disputed.append(field)
        for field in _MULTI:
            sets = [frozenset(v[field]) for v in votes]
            counts = Counter(x for s in sets for x in s)
            out[field] = sorted(x for x, c in counts.items() if c > n / 2)
            if len(set(sets)) == 1:
                unanimous[field] += 1
        if out["ai_reference"] is None:
            disputed.append("ai_reference")
        for a, b in combinations(votes, 2):
            pair_agree["pairs"] += 1
            pair_agree["identical"] += all(a[f] == b[f] for f in _SINGLE) and all(
                set(a[f]) == set(b[f]) for f in _MULTI
            )

        # Keep the voted label internally consistent with the schema's rules.
        if out["ai_reference"] in (None, "none"):
            out.update(
                frame=None, roles=[], risk_types=[], business_functions=[], governance_responses=[],
                disclosure_traits=[], adoption_stage=None, ai_kind=None, substantiveness=None,
            )
        else:
            if not out["roles"]:
                disputed.append("roles")
            if "risk" not in out["roles"]:
                out["risk_types"] = []
            elif not out["risk_types"]:
                disputed.append("risk_types")
            if "adoption" not in out["roles"]:
                out["adoption_stage"] = None
                out["business_functions"] = []
            else:
                if out["adoption_stage"] is None:
                    disputed.append("adoption_stage")
                if not out["business_functions"]:
                    disputed.append("business_functions")
            if "governance" not in out["roles"]:
                out["governance_responses"] = []
            elif not out["governance_responses"]:
                disputed.append("governance_responses")

        names = Counter()
        spelling = {}
        for v in votes:
            for e in {x.strip() for x in v["entities"] if x.strip()}:
                names[e.casefold()] += 1
                spelling.setdefault(e.casefold(), e)
        out["entities"] = sorted(spelling[k] for k, c in names.items() if c > n / 2)
        # Every coder's quotes, flattened; the same quote is kept once (whitespace aside, first spelling wins).
        quotes = {}
        for v in votes:
            for q in v["evidence"]:
                quotes.setdefault(_squash(q), q)
        out["evidence"] = list(quotes.values())
        out["confidence"] = {c: got[c]["confidence"] for c in sorted(got)}
        out["notes"] = [f"{c}: {got[c]['note']}" for c in sorted(got) if got[c]["note"]]
        out["disputed"] = sorted(set(disputed))
        out["needs_review"] = bool(disputed)
        final.append(out)

    total = len(final)
    agreement = {
        "taxonomy_version": TAXONOMY_VERSION,
        "coders": coders,
        "n_passages": total,
        "unanimous_share": {f: round(unanimous[f] / total, 3) for f in _SINGLE + _MULTI} if total else {},
        "pairwise_identical_label_share": round(pair_agree["identical"] / pair_agree["pairs"], 3)
        if pair_agree["pairs"]
        else None,
        "needs_review": [f["passage_id"] for f in final if f["needs_review"]],
    }
    return final, agreement
