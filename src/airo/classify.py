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
_SINGLE = ("ai_reference", "adoption_stage", "substantiveness")
_MULTI = ("roles", "risk_types", "mit_subdomains", "ai_kinds", "business_functions", "governance_responses", "disclosure_traits")


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
                "matched_terms": p["matched"],
                "text": p["text"],
            }
        )
    return out


def _squash(text: str) -> str:
    return _WS.sub(" ", text).strip()


# Which filing of a company keeps the task when several carry the same passage: the form that has
# Item sections and is the primary report goes first. An ARS often repeats the 10-K under another filing id.
_FORM_ORDER = ("10-K", "20-F", "40-F", "10-KT", "N-CSR", "10-K/A", "20-F/A", "ARS")
_UNKNOWN = "not provided by the data provider"


def release_year(doc: dict) -> str | None:
    """The year the filing appeared (release time, else filing date), or None. Many ARS have no fiscal year."""
    for field in ("released", "filing_date"):
        day = str(doc.get(field) or "")
        if day[:4].isdigit():
            return day[:4]
    return None


def primary_filings(rows: list[dict]) -> set[int]:
    """Positions of the main report per company and release year; `rows` have company_id, release_year, form, chunks, document_id.

    The first form in `_FORM_ORDER` wins, then the filing with more chunks, then the lower id. A row
    without a known company or release year cannot be compared and counts as its own main report.
    """
    rank = {form: i for i, form in enumerate(_FORM_ORDER)}
    groups: dict[tuple, list[int]] = {}
    out = set()
    for i, r in enumerate(rows):
        company = r.get("company_id")
        if company and company != _UNKNOWN and r.get("release_year"):
            groups.setdefault((company, r["release_year"]), []).append(i)
        else:
            out.add(i)
    for members in groups.values():
        out.add(min(members, key=lambda i: (rank.get(rows[i].get("form"), len(rank)), -(rows[i].get("chunks") or 0), str(rows[i].get("document_id")))))
    return out


_NEAR_TOKENS = re.compile(r"[a-z0-9]+")
_NEAR_MIN_WORDS = 8
_NEAR_MAX_GROUP = 400  # pairs grow with the square; a larger group is reported as not checked


def duplicate_check(rows: list[dict], threshold: float = 0.9) -> dict:
    """How far chunks repeat within a company and release year; `rows` have chunk_id, company_id, release_year, text, copied.

    `repeats` counts texts that are the same ignoring case and punctuation, over all chunks and over the
    tasks left after `collapse_copies`; `near_pairs` counts pairs of those tasks whose word sets overlap by at least `threshold`.
    """
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        if r.get("company_id") and r["company_id"] != _UNKNOWN and r.get("release_year"):
            groups.setdefault((r["company_id"], r["release_year"]), []).append(r)

    def repeats(items: list[dict]) -> int:
        return len(items) - len({" ".join(_NEAR_TOKENS.findall(i["text"].lower())) for i in items})

    near = before = after = unchecked = 0
    involved = set()
    for items in groups.values():
        left = [r for r in items if not r.get("copied")]
        before += repeats(items)
        after += repeats(left)
        if len(left) > _NEAR_MAX_GROUP:
            unchecked += 1
            continue
        words = [(r["chunk_id"], _words(r["text"])) for r in left]
        for (a, x), (b, y) in combinations(words, 2):
            if _near(x, y, threshold):
                near += 1
                involved |= {a, b}
    tasks = sum(not r.get("copied") for r in rows)
    return {
        "chunks": len(rows),
        "copies": len(rows) - tasks,
        "tasks": tasks,
        "repeats_before": before,
        "repeats_after": after,
        "near_threshold": threshold,
        "near_pairs": near,
        "tasks_in_near_pairs": len(involved),
        "near_share_of_tasks": round(len(involved) / tasks, 4) if tasks else None,
        "groups_not_checked": unchecked,
    }


def collapse_copies(entries: list[tuple[dict, dict]]) -> tuple[list[dict], list[dict]]:
    """One task per text within a company and filing year.

    `entries` are (task, its document). Texts count as the same if they differ at most in whitespace
    and in which quotation marks, apostrophes or dashes they have, so that the evidence of a label
    can be found again in every copy (see `_locate`). A document without a known company or filing
    date keeps all its tasks. Returns (tasks to label, in the given order; copies, one row
    `{"passage_id", "copy_of"}` per passage that takes the label of another).
    """
    rank = {form: i for i, form in enumerate(_FORM_ORDER)}
    groups: dict[tuple, list[int]] = {}
    for i, (task, doc) in enumerate(entries):
        company, year = doc.get("cik"), release_year(doc)
        if company and company != _UNKNOWN and year:
            key = (company, year, _MARKS.sub('"', _squash(task["text"])))
            groups.setdefault(key, []).append(i)
    copy_of: dict[int, int] = {}
    for members in groups.values():
        keep = min(members, key=lambda i: (rank.get(entries[i][0]["form"], len(rank)), i))
        copy_of.update({i: keep for i in members if i != keep})
    tasks_ = [task for i, (task, _) in enumerate(entries) if i not in copy_of]
    copies = [{"passage_id": entries[i][0]["passage_id"], "copy_of": entries[k][0]["passage_id"]} for i, k in sorted(copy_of.items())]
    return tasks_, copies


def _words(text: str) -> set[str]:
    return set(_NEAR_TOKENS.findall(text.lower()))


def _near(x: set[str], y: set[str], threshold: float) -> bool:
    return len(x) >= _NEAR_MIN_WORDS and len(y) >= _NEAR_MIN_WORDS and len(x & y) / len(x | y) >= threshold


def collapse_near(entries: list[tuple[dict, dict]], threshold: float = 0.9) -> tuple[list[dict], list[dict]]:
    """One task per group of near copies within a company and release year; the others take its label in `adjudicate`.

    `entries` are (task, its document), the tasks left after `collapse_copies`. Two tasks are near if their word
    sets overlap by at least `threshold` (the measure of `duplicate_check`); near pairs are joined into groups and
    each group keeps one task, the first form in `_FORM_ORDER`, then the earlier one. A group of more than
    `_NEAR_MAX_GROUP` tasks of one company and year is not checked. Returns (tasks to label, in the given order;
    copies, one row `{"passage_id", "copy_of", "match": "near"}` per task that takes the label of another).
    """
    rank = {form: i for i, form in enumerate(_FORM_ORDER)}
    groups: dict[tuple, list[int]] = {}
    for i, (task, doc) in enumerate(entries):
        company, year = doc.get("cik"), release_year(doc)
        if company and company != _UNKNOWN and year:
            groups.setdefault((company, year), []).append(i)
    parent: dict[int, int] = {}

    def find(i: int) -> int:
        while parent.setdefault(i, i) != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for members in groups.values():
        if len(members) > _NEAR_MAX_GROUP:
            continue
        words = [(i, _words(entries[i][0]["text"])) for i in members]
        for (a, x), (b, y) in combinations(words, 2):
            if _near(x, y, threshold):
                parent[find(a)] = find(b)
    components: dict[int, list[int]] = {}
    for i in parent:
        components.setdefault(find(i), []).append(i)
    copy_of: dict[int, int] = {}
    for members in components.values():
        keep = min(members, key=lambda i: (rank.get(entries[i][0]["form"], len(rank)), i))
        copy_of.update({i: keep for i in members if i != keep})
    tasks_ = [task for i, (task, _) in enumerate(entries) if i not in copy_of]
    copies = [{"passage_id": entries[i][0]["passage_id"], "copy_of": entries[k][0]["passage_id"], "match": "near"}
              for i, k in sorted(copy_of.items())]
    return tasks_, copies


def copy_labels(final: list[dict], copies: list[dict], text_by_id: dict[str, str]) -> tuple[list[dict], int]:
    """`final` plus one label per copy whose original has one, marked `copied_from` (and `copy_match` "near" for a near copy).

    A copy's evidence is stored in its own passage's characters. A near copy with a quote of its original's evidence
    that is not in its own text keeps the quote as the original has it and is flagged `needs_review`, with
    `near_copy_evidence` in `disputed`. A copy of a copy takes the label once its original has one.
    Returns (labels, copies labelled).
    """
    by_id = {l["passage_id"]: l for l in final}
    out = list(final)
    n = 0
    pending = list(copies)
    while pending:
        left = []
        for c in pending:
            original = by_id.get(c["copy_of"])
            if original is None:
                left.append(c)
                continue
            text = _squash(text_by_id[c["passage_id"]])
            found = [_locate(q, text) for q in original["evidence"]]
            label = {k: v for k, v in original.items() if k not in ("copied_from", "copy_match")}
            label.update(passage_id=c["passage_id"], evidence=[f or q for f, q in zip(found, original["evidence"])],
                         copied_from=c["copy_of"])
            if c.get("match") == "near":
                label["copy_match"] = "near"
                if None in found:
                    label["disputed"] = sorted({*label.get("disputed", []), "near_copy_evidence"})
                    label["needs_review"] = True
            out.append(label)
            by_id[c["passage_id"]] = label
            n += 1
        if len(left) == len(pending):
            break
        pending = left
    return out, n


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
                roles=[], risk_types=[], mit_subdomains=[], business_functions=[], governance_responses=[],
                ai_kinds=[], disclosure_traits=[], adoption_stage=None, substantiveness=None,
            )
        else:
            if not out["roles"]:
                disputed.append("roles")
            if "risk" not in out["roles"]:
                out["risk_types"] = []
            elif not out["risk_types"]:
                disputed.append("risk_types")
            if "risk" not in out["roles"] and "incident" not in out["roles"]:
                out["mit_subdomains"] = []
            elif not out["mit_subdomains"]:
                disputed.append("mit_subdomains")
            if not out["ai_kinds"]:
                disputed.append("ai_kinds")
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
