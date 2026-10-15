"""Jev coder: tasks.jsonl -> labels/jev.jsonl (+ labels/jev.raw.jsonl with Jev's raw answers).

Questions are asked in stages, so a passage only pays for the questions that apply:
  1. ai_reference                     (stop here if `none`)
  2. frame, roles, ai_kinds, traits, substantiveness
  3. follow-ups for the roles found:  risk -> risk_types + mit_subdomains; incident -> mit_subdomains;
                                      adoption -> adoption_stage + business_functions;
                                      governance -> governance_responses
Identical text in the same section and heading is asked once. Key: TYPESAFE_API_KEY.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path  
from typing import Callable

from dotenv import load_dotenv

from ..taxonomy import (
    ADOPTION_STAGES, AI_KINDS, AI_REFERENCE, BUSINESS_FUNCTIONS, DISCLOSURE_TRAITS, FRAMES,
    GOVERNANCE_RESPONSES, MIT_SUBDOMAINS, RISK_TYPES, ROLES, SUBSTANTIVENESS, TAXONOMY_VERSION, Definition,
)

load_dotenv(Path(__file__).resolve().parents[3] / ".env.local")

DEFAULT_MODEL = "jev-1.13.0"
DEFAULT_BASE_URL = "https://api.typesafe.ai"
THRESHOLD = 0.5  # default Noul threshold; tune per question against labelled passages
ASK_FLOOR = 0.3  # follow-up questions are asked when a role's p >= this, so thresholds can be tuned later
_RETRY_STATUS = {429, 500, 502, 503, 504, 529}
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_WS = re.compile(r"\s+")
_SCORE_FIELDS = {"role": "roles", "risk": "risk_types", "mit": "mit_subdomains", "func": "business_functions",
                 "gov": "governance_responses", "kind": "ai_kinds", "trait": "disclosure_traits"}

BORDER = 0.1  # an answer within this distance of its threshold counts as borderline
CONF_FIELDS = ("role", "risk", "mit", "func", "gov", "kind")

Post = Callable[[dict], dict]  # request body -> response body


# --- questions ---------------------------------------------------------------

def _describe(d: Definition) -> str:
    definition, criteria = d
    return definition + " Criteria (all required): " + "; ".join(f"({i}) {c}" for i, c in enumerate(criteria, 1)) + "."


def _choice(instructions: str, values: dict[str, Definition]) -> dict:
    return {"type": "choice", "instructions": instructions, "criteria": {k: _describe(v) for k, v in values.items()}}


def _noul(instructions: str, d: Definition) -> dict:
    return {"type": "noul", "instructions": instructions + " " + _describe(d)}


def _score(instructions: str, values: dict[str, Definition]) -> dict:
    return {"type": "score", "instructions": instructions,
            "criteria": [f"{k}: {_describe(v)}" for k, v in values.items()]}


_ABOUT = "Judge the AI-related statements of the passage only, from the passage alone."
# Values not asked as questions: derived in `to_label` when no other value of the field passes.
_DERIVED = {"role": {"general"}, "risk": {"other"}, "mit": {"other"}, "func": {"other", "not_stated"},
            "gov": {"other"}, "kind": {"other", "unspecified"}}


def _nouls(prefix: str, values: dict[str, Definition], question: str) -> dict[str, dict]:
    return {f"{prefix}:{k}": _noul(question.format(k=k), d) for k, d in values.items() if k not in _DERIVED.get(prefix, ())}


def question_groups() -> dict[str, dict[str, dict]]:
    """The questions, grouped by the stage that asks them."""
    return {
        "gate": {"ai_reference": _choice(
            "Does the passage treat AI? Judge it from the passage alone; the matched terms are listed above the "
            "passage.", AI_REFERENCE)},
        "base": {
            "frame": _choice(
                "In which frame is the AI statement made? Decide it from the report section, the heading and the "
                "function of the sentence. Order of tests: a sentence stating a possible harm is risk_factor; "
                "otherwise one describing an oversight remit is governance; otherwise one about demand, prices, "
                "supply or investment is market; otherwise business.", FRAMES),
            "substantiveness": _score(
                "How substantive is the AI statement? " + _ABOUT + " Give the highest level whose criteria the "
                "AI-related statements meet. Particulars that are not about AI (the company's revenue, the date of "
                "the report) do not count.", SUBSTANTIVENESS),
            **_nouls("role", ROLES, "Does AI play the role '{k}' for the company in this passage?"),
            **_nouls("kind", AI_KINDS, "Does the passage name this kind of AI ('{k}') for the AI the statement is "
                                       "about? Only if a term for it is in the passage."),
            **_nouls("trait", DISCLOSURE_TRAITS, "Does the AI statement show the disclosure trait '{k}'?"),
        },
        "risk": _nouls("risk", RISK_TYPES, "Does the passage attribute a '{k}' risk to AI?"),
        "mit": _nouls("mit", MIT_SUBDOMAINS, "Does the passage state this harm from AI (MIT AI Risk Repository "
                                             "subdomain '{k}'), as a risk to the company or an event that occurred?"),
        "adoption": {
            "adoption_stage": _choice(
                "How far is the company's own use of AI? If several stages are stated, take the most advanced.",
                ADOPTION_STAGES),
            **_nouls("func", BUSINESS_FUNCTIONS, "Does the passage state the company's own AI use in this business "
                                                 "function ('{k}')? Do not infer it from the industry."),
        },
        "governance": _nouls("gov", GOVERNANCE_RESPONSES, "Does the passage name this response of the company to "
                                                          "AI ('{k}')?"),
    }


def questions() -> dict[str, dict]:
    """Every question that may be asked, flat (used for the cache key)."""
    return {k: q for group in question_groups().values() for k, q in group.items()}


def state(task: dict) -> str:
    """What Jev reads: the passage with the context a human coder gets."""
    matched = task.get("matched_terms") or {}
    terms = ", ".join(t for ts in matched.values() for t in ts) or "(none)"
    head = [f"Company: {task.get('company') or 'unknown'}", f"Form: {task.get('form') or 'unknown'}",
            f"Fiscal year: {task.get('fiscal_year') or 'unknown'}", f"Section: {task.get('section') or 'unknown'}",
            f"Heading: {task.get('heading') or 'none'}", f"Matched terms: {terms}"]
    return "\n".join(head) + "\n\nPassage:\n" + task["text"]


# --- transport ---------------------------------------------------------------

def http_post(api_key: str | None = None, base_url: str | None = None, timeout: float = 60,
              max_retries: int = 6) -> Post:
    """A `Post` that calls the TypeSafe API, retrying 429/529/5xx with exponential backoff."""
    key = api_key or os.environ.get("TYPESAFE_API_KEY")
    if not key:
        raise RuntimeError("set TYPESAFE_API_KEY (or pass api_key)")
    url = (base_url or os.environ.get("TYPESAFE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/") + "/v1/systemone"

    def post(body: dict) -> dict:
        data = json.dumps(body).encode("utf-8")
        for attempt in range(max_retries + 1):
            req = urllib.request.Request(url, data=data, method="POST", headers={
                "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:500]
                if e.code not in _RETRY_STATUS or attempt == max_retries:
                    raise RuntimeError(f"TypeSafe API {e.code}: {detail}") from None
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt == max_retries:
                    raise RuntimeError(f"TypeSafe API unreachable: {e}") from None
            time.sleep(min(60, 2 ** attempt) * (0.5 + random.random()))  # jittered backoff
        raise AssertionError("unreachable")

    return post


def ask(task: dict, post: Post, model: str, groups: dict[str, dict[str, dict]], batch: int | None = None) -> dict:
    """Jev's answers for one task, asked stage by stage (see the module docstring)."""
    answers, usage, served = {}, {"input_tokens": 0, "output_tokens": 0}, None

    def send(qs: dict[str, dict]) -> None:
        nonlocal served
        ids = list(qs)
        size = batch or len(ids) or 1
        for i in range(0, len(ids), size):
            part = {k: qs[k] for k in ids[i:i + size]}
            resp = post({"model": model, "state": state(task), "questions": part})
            missing = set(part) - set(resp.get("answers", {}))
            if missing:
                raise RuntimeError(f"answers missing for {sorted(missing)}")
            answers.update(resp["answers"])
            for k in usage:
                usage[k] += (resp.get("usage") or {}).get(k, 0)
            served = resp.get("model", served)

    send(groups["gate"])
    if answers["ai_reference"]["choice"] == "none":
        return {"answers": answers, "usage": usage, "model": served, "gated": True}
    send(groups["base"])
    likely = lambda role: answers.get(f"role:{role}", {}).get("noul", 0) >= ASK_FLOOR  # noqa: E731
    follow: dict[str, dict] = {}
    if likely("risk"):
        follow |= groups["risk"] | groups["mit"]
    elif likely("incident"):
        follow |= groups["mit"]
    if likely("adoption"):
        follow |= groups["adoption"]
    if likely("governance"):
        follow |= groups["governance"]
    if follow:
        send(follow)
    return {"answers": answers, "usage": usage, "model": served, "gated": False}


# --- answers -> label --------------------------------------------------------

def _evidence(task: dict, limit: int = 3) -> list[str]:
    """Up to `limit` sentences of the passage that contain a matched wording, verbatim."""
    words = {w for found in (task.get("matched_text") or {}).values() for w in found}
    if not words:  # fall back to the canonical terms
        words = {t for terms in (task.get("matched_terms") or {}).values() for t in terms}
    paragraphs = (_WS.sub(" ", p).strip() for p in task["text"].split("\n\n"))
    sentences = [s for p in paragraphs if p for s in _SENTENCE.split(p) if s.strip()]
    hits = [s for s in sentences if any(w.lower() in s.lower() for w in words)]
    return (hits or sentences[:1])[:limit]


def _level(answer: dict, values: dict) -> str:
    names = list(values)
    return names[max(0, min(len(names) - 1, round(answer["score"])))]

#Might need to be updated
def _confidence(a: dict, thresholds: dict[str, float]) -> float:
    """Average probability Jev gave to the answers in this output
    (chosen option for choices/score; p for a yes, 1-p for a no)."""
    probs = []
    for key, ans in a.items():
        if "noul" in ans:
            t = thresholds.get(key, THRESHOLD)
            probs.append(ans["noul"] if ans["noul"] >= t else 1 - ans["noul"])
        elif ans.get("probabilities"):
            probs.append(max(ans["probabilities"].values()))
    return round(sum(probs) / len(probs), 3)

def scores(answers: dict) -> dict:
    """All of Jev's numbers for one passage, grouped by label field and rounded to 3 decimals."""
    out: dict = {}
    for key in ("ai_reference", "frame", "adoption_stage"):
        if key in answers:
            out[key] = {k: round(v, 3) for k, v in answers[key]["probabilities"].items()}
    if "substantiveness" in answers:
        sub = answers["substantiveness"]
        names = list(SUBSTANTIVENESS)
        out["substantiveness"] = {
            "score": round(sub["score"], 3),
            "confidence": round(sub.get("confidence", 0), 3),
            "levels": {names[int(i)]: round(p, 3) for i, p in (sub.get("probabilities") or {}).items()},
        }
    for key, ans in answers.items():
        prefix, _, value = key.partition(":")
        if prefix in _SCORE_FIELDS:
            out.setdefault(_SCORE_FIELDS[prefix], {})[value] = round(ans["noul"], 3)
    return out

def to_label(task: dict, answers: dict, thresholds: dict[str, float] | None = None) -> dict:
    """Assemble one schema-valid label from Jev's answers."""
    th = thresholds or {}
    a = answers
    notes: list[str] = []
    passed = lambda k: k in a and a[k]["noul"] >= th.get(k, THRESHOLD)  # noqa: E731
    values = lambda prefix: [k.split(":", 1)[1] for k in a if k.startswith(prefix + ":") and passed(k)]  # noqa: E731
    asked = lambda prefix: any(k.startswith(prefix + ":") for k in a)  # noqa: E731

    label: dict = {"passage_id": task["passage_id"], "ai_reference": a["ai_reference"]["choice"], "note": ""}
    if label["ai_reference"] == "none":
        label["confidence"] = _confidence(a, th)  
        label["scores"] = scores(a)
        return label

    roles = values("role")
    # A role whose follow-up questions were not asked (threshold set below ASK_FLOOR) cannot be completed.
    for role, needs in (("risk", "risk"), ("adoption", "func"), ("governance", "gov")):
        if role in roles and not asked(needs):
            roles.remove(role)
            notes.append(f"jev: role {role} dropped, its follow-up questions were not asked")
    if "incident" in roles and not asked("mit"):
        roles.remove("incident")
        notes.append("jev: role incident dropped, its follow-up questions were not asked")
    roles = roles or ["general"]

    risk_types: list[str] = []
    if "risk" in roles:
        risk_types = values("risk") or ["other"]
        if risk_types == ["other"]:
            notes.append("jev: risk role without a risk type above threshold")
    mit: list[str] = []
    if "risk" in roles or "incident" in roles:
        mit = values("mit") or ["other"]
        if mit == ["other"]:
            notes.append("jev: no MIT subdomain above threshold")
    functions: list[str] = []
    stage = None
    if "adoption" in roles:
        stage = a["adoption_stage"]["choice"]
        functions = values("func") or ["not_stated"]
    responses: list[str] = []
    if "governance" in roles:
        responses = values("gov") or ["other"]
        if responses == ["other"]:
            notes.append("jev: governance role without a named response above threshold")
    frame = a["frame"]["choice"]
    traits = values("trait")
    if frame == "market":
        traits = [t for t in traits if t != "externalisation"]

    label.update(
        frame=frame,
        roles=roles,
        risk_types=risk_types,
        mit_subdomains=mit,
        adoption_stage=stage,
        business_functions=functions,
        governance_responses=responses,
        ai_kinds=values("kind") or ["unspecified"],
        disclosure_traits=traits,
        substantiveness=_level(a["substantiveness"], SUBSTANTIVENESS),
        entities=[],
        evidence=_evidence(task),
        confidence=_confidence(a, th),
        note=" ".join(notes),
        scores=scores(a)
    )
    return label


# --- run ---------------------------------------------------------------------

def _questions_hash(qs: dict[str, dict]) -> str:
    return hashlib.sha256(json.dumps(qs, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def dedup_key(task: dict, model: str, qhash: str) -> str:
    """Same model, questions, section, heading, matched terms and text -> same key. Company and year left out."""
    text = _WS.sub(" ", task["text"]).strip()
    ident = [model, qhash, task.get("section") or "", task.get("heading") or "",
             sorted(t for ts in (task.get("matched_terms") or {}).values() for t in ts), text]
    return hashlib.sha256(json.dumps(ident).encode("utf-8")).hexdigest()


def duplication(tasks: list[dict], model: str | None = None) -> dict:
    """How many API calls deduplication saves on these tasks, without calling the API."""
    model = model or os.environ.get("TYPESAFE_MODEL") or DEFAULT_MODEL
    qh = _questions_hash(questions())
    unique = len({dedup_key(t, model, qh) for t in tasks})
    return {"tasks": len(tasks), "unique": unique, "duplicates": len(tasks) - unique,
            "share_saved": round(1 - unique / len(tasks), 3) if tasks else 0.0}


def _read_jsonl_tolerant(path: Path) -> list[dict]:
    rows = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a truncated last line from a killed run
    return rows


def as_task(row: dict) -> dict:
    """Accept a task row or a chunk row (chunk_id, chunk_text, company_name, ...)."""
    if "chunk_id" not in row:
        return row
    return {
        "passage_id": row["chunk_id"],
        "text": row["chunk_text"],
        "company": row.get("company_name"),
        "form": row.get("form"),
        "fiscal_year": row.get("report_year"),
        "section": " ".join(row.get("report_sections") or []) or None,
        "heading": row.get("heading"),
        "matched_terms": {"ai": row.get("matched_keywords") or []},
    }


def run(
    tasks: list[dict],
    out: Path,
    post: Post | None = None,
    model: str | None = None,
    workers: int = 8,
    batch: int | None = None,
    thresholds: dict[str, float] | None = None,
    log=print,
) -> dict:
    """Label every task not yet in `out` (resumable), reusing answers for identical text."""
    model = model or os.environ.get("TYPESAFE_MODEL") or DEFAULT_MODEL
    out = Path(out)
    raw_path = out.with_name(out.stem + ".raw.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    done = {r["passage_id"] for r in _read_jsonl_tolerant(out) if "passage_id" in r}
    todo = [t for t in tasks if t["passage_id"] not in done]
    groups = question_groups()
    qh = _questions_hash(questions())
    cache = {r["key"]: r for r in _read_jsonl_tolerant(raw_path) if "key" in r}

    by_key: dict[str, list[dict]] = {}
    for t in todo:
        by_key.setdefault(dedup_key(t, model, qh), []).append(t)
    to_ask = [k for k in by_key if k not in cache]
    log(f"jev: {len(tasks)} task(s), {len(done)} already labelled, {len(todo)} to label "
        f"({len(by_key)} unique, {len(by_key) - len(to_ask)} answered before, {len(to_ask)} to ask; "
        f"taxonomy v{TAXONOMY_VERSION}, {model})")
    stats = {"labelled": 0, "failed": 0, "api_calls": 0, "reused": 0, "screened_out": 0, "input_tokens": 0,
             "tokens_saved": 0}

    if to_ask:  # a fully cached run needs no API key
        post = post or http_post()

    def one(key: str):
        try:
            return key, ask(by_key[key][0], post, model, groups, batch), None
        except Exception as e:  # noqa: BLE001 - one failed request must not stop the run
            return key, None, f"{type(e).__name__}: {e}"

    with open(out, "a", encoding="utf-8") as fl, open(raw_path, "a", encoding="utf-8") as fr:
        def emit(key: str, row: dict, fresh: bool) -> None:
            for i, task in enumerate(by_key[key]):
                fl.write(json.dumps(to_label(task, row["answers"], thresholds), ensure_ascii=False) + "\n")
                stats["labelled"] += 1
                if i or not fresh:
                    stats["reused"] += 1
                    stats["tokens_saved"] += (row.get("usage") or {}).get("input_tokens", 0)
            fl.flush()

        for key in by_key:
            if key in cache:
                emit(key, cache[key], fresh=False)
        with ThreadPoolExecutor(max(1, workers)) as pool:
            for n, (key, res, err) in enumerate(pool.map(one, to_ask), 1):
                ids = [t["passage_id"] for t in by_key[key]]
                if err:
                    stats["failed"] += len(ids)
                    log(f"{n}/{len(to_ask)}  failed  {ids[0]}" + (f" (+{len(ids) - 1} identical)" if len(ids) > 1 else "")
                        + f": {err}")
                    for pid in ids:
                        fl.write(json.dumps({"passage_id": pid, "error": err}) + "\n")
                    fl.flush()
                    continue
                row = {"key": key, "passage_ids": ids, "model": res["model"], "usage": res["usage"],
                       "taxonomy_version": TAXONOMY_VERSION, "questions_hash": qh, "answers": res["answers"]}
                fr.write(json.dumps(row) + "\n")
                fr.flush()
                stats["api_calls"] += 1
                stats["screened_out"] += res.get("gated", False)
                stats["input_tokens"] += res["usage"]["input_tokens"]
                emit(key, row, fresh=True)
    cost, saved = stats["input_tokens"] * 0.042 / 1e6, stats["tokens_saved"] * 0.042 / 1e6
    log(f"jev: {stats['labelled']} labelled ({stats['reused']} reused from identical text, "
        f"{stats['screened_out']} unique text(s) stopped after ai_reference = none), {stats['failed']} failed; "
        f"{stats['api_calls']} API call(s), {stats['input_tokens']:,} input tokens (~${cost:.4f}); "
        f"saved ~{stats['tokens_saved']:,} tokens (~${saved:.4f}) at $0.042/M")
    return stats

def route(rows: list[dict], labels_path: Path, out: Path, below: float = 0.88, log=print) -> dict:
    """Copy the input rows (chunks.jsonl rows as they are) whose Jev confidence is below `below`,
    that Jev failed on, or that have no Jev label."""
    labels = {r["passage_id"]: r for r in _read_jsonl_tolerant(Path(labels_path)) if "passage_id" in r}
    reasons = {"low confidence": 0, "Jev failed": 0, "no Jev label": 0}
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        for row in rows:
            label = labels.get(row.get("chunk_id") or row.get("passage_id"))
            if label is None:
                reason = "no Jev label"
            elif "error" in label:
                reason = "Jev failed"
            elif label.get("confidence", 1.0) < below:
                reason = "low confidence"
            else:
                continue
            reasons[reason] += 1
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    n = sum(reasons.values())
    log(f"route: {n} of {len(rows)} chunk(s) to Gemini ({100 * n / max(len(rows), 1):.0f}%) -> {out}  {reasons}")
    return {"routed": n, "chunks": len(rows), "reasons": reasons}

def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m airo.coders.jev", description="Label tasks or chunks with TypeSafe Jev.")
    ap.add_argument("tasks", type=Path, help="tasks.jsonl (from `airo tasks`) or chunks.jsonl")
    ap.add_argument("--out", type=Path, default=Path("labels/jev.jsonl"))
    ap.add_argument("--model")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--batch", type=int, help="questions per request (default: each stage in one request)")
    ap.add_argument("--thresholds", type=Path, help="JSON {question_id: threshold}, e.g. {\"role:risk\": 0.6}")
    ap.add_argument("--limit", type=int, help="label only the first N tasks (for a trial run)")
    ap.add_argument("--dedup-stats", action="store_true", help="only report duplicate text (no API calls)")
    ap.add_argument("--route", type=Path, help="write the chunks to send to Gemini to this file")
    ap.add_argument("--route-only", action="store_true", help="only write the --route file from existing labels (no Jev calls)")
    ap.add_argument("--route-below", type=float, default=0.88, help="route chunks with confidence below this (default 0.88)")
    a = ap.parse_args(argv)
    tasks = [as_task(json.loads(l)) for l in a.tasks.read_text(encoding="utf-8").splitlines() if l.strip()]
    if a.dedup_stats:
        d = duplication(tasks, a.model)
        print(f"{d['tasks']} task(s), {d['unique']} unique text(s): {d['duplicates']} duplicate(s), "
              f"{d['share_saved']:.1%} of API calls saved by deduplication")
        return 0
    th = json.loads(a.thresholds.read_text(encoding="utf-8")) if a.thresholds else None
    if a.route_only:
        if not a.route:
            ap.error("--route-only needs --route FILE")
        route(tasks, a.out, a.route, a.route_below)
        return 0
    stats = run(tasks, a.out, model=a.model, workers=a.workers, batch=a.batch, thresholds=th)
    if a.route:
        route(tasks, a.out, a.route, a.route_below)
    return 1 if stats["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())