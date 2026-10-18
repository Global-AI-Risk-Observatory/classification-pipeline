"""Human validation of a classification run: sample, rater sheets, agreement.

The protocol is section 3 of docs/research-plan.md: the unit is one passage labelled with the
current codebook; a stratified sample, a share of it rated by two people; Cohen's kappa per
field, human against human and human against the model; disagreements read, not only counted.

Steps, each a sub-command:

    sample     draw the passages from a run in the bucket, assign them to raters, write one
               sheet per rater without the model's labels            -> work/<name>/, bucket
    sheets     create one Google Sheet per rater from those files      -> work/<name>/sheets.json
    collect    read the raters' sheets back, check the values against the taxonomy, write one
               coder file per rater (the format `python -m airo accept` reads) -> work/<name>/labels/
    agreement  kappa and accuracy per field                            -> results/<name>/

    python human_validation.py sample --run gs://<bucket>/<run> --out gs://<bucket>/<run>/human_validation
    python human_validation.py sheets --project <gcp project>
    python human_validation.py collect --project <gcp project>
    python human_validation.py agreement

Strata (the role that decides a passage's stratum is the first of governance, adoption, risk
in its roles; `none` is `ai_reference` none; the rest are offering, market_driver, general):

    risk 90, adoption 70, governance 40, other_roles 50, none 40 (20 of them with the model's
    confidence low or medium).

Within a stratum the draw is systematic over the passages sorted by ISIC section and form, so
sections and forms are represented in proportion; at most one passage per filing. Passages over
--max-words are left out so that a rater's share is one session's work; the share left out is
reported in the sample's summary. The double-rated passages rotate through every pair of raters.

Google Sheets are written with the user's own Google credentials (`gcloud auth login
--enable-gdrive-access`); the Sheets and Drive APIs must be enabled in --project. Passage text
stays in work/ (git-ignored) and in the bucket; results/ holds counts and agreement figures only.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "src"))
from airo import taxonomy as tx  # noqa: E402

STRATA = {"risk": 90, "adoption": 70, "governance": 40, "other_roles": 50, "none": 40}
NONE_LOW_CONFIDENCE = 20  # of the `none` stratum: passages the model labelled with confidence low or medium

# Fields the raters fill, in sheet order. Every cell has a drop-down: a single-value field is one
# column, a list field is one column per value slot (`roles 1`, `roles 2`, ...), as many slots as
# cover at least 94 % of the model's non-empty labels of that field on us-2025h1_V3.
SINGLE = {
    "ai_reference": list(tx.AI_REFERENCE),
    "frame": list(tx.FRAMES),
    "adoption_stage": list(tx.ADOPTION_STAGES),
    "substantiveness": list(tx.SUBSTANTIVENESS),
    "confidence": ["low", "medium", "high"],
}
MULTI = {
    "roles": list(tx.ROLES),
    "risk_types": list(tx.RISK_TYPES),
    "mit_subdomains": list(tx.MIT_SUBDOMAINS),
    "business_functions": list(tx.BUSINESS_FUNCTIONS),
    "governance_responses": list(tx.GOVERNANCE_RESPONSES),
    "disclosure_traits": list(tx.DISCLOSURE_TRAITS),
}
SLOTS = {"roles": 3, "risk_types": 4, "mit_subdomains": 4, "business_functions": 3, "governance_responses": 3,
         "disclosure_traits": 3}
FIELDS = ["ai_reference", "frame", "roles", "risk_types", "mit_subdomains", "adoption_stage",
          "business_functions", "governance_responses", "substantiveness", "disclosure_traits",
          "confidence", "note"]
CONTEXT = ["n", "passage_id", "company", "form", "isic_division", "section", "heading", "passage"]


def sheet_columns() -> list[tuple[str, str, int]]:
    """(column header, field, slot) for every rating column; slot 0 for a single-value field."""
    cols = []
    for f in FIELDS:
        if f in SLOTS:
            cols += [(f"{f} {i}", f, i) for i in range(1, SLOTS[f] + 1)]
        else:
            cols.append((f, f, 0))
    return cols


RATING_COLUMNS = sheet_columns()
DEFINITIONS = {
    "ai_reference": tx.AI_REFERENCE, "frame": tx.FRAMES, "roles": tx.ROLES, "risk_types": tx.RISK_TYPES,
    "mit_subdomains": tx.MIT_SUBDOMAINS, "adoption_stage": tx.ADOPTION_STAGES,
    "business_functions": tx.BUSINESS_FUNCTIONS, "governance_responses": tx.GOVERNANCE_RESPONSES,
    "substantiveness": tx.SUBSTANTIVENESS, "disclosure_traits": tx.DISCLOSURE_TRAITS,
}

# ISIC Rev. 4 sections by division.
ISIC_SECTIONS = [("01", "03", "A"), ("05", "09", "B"), ("10", "33", "C"), ("35", "35", "D"), ("36", "39", "E"),
                 ("41", "43", "F"), ("45", "47", "G"), ("49", "53", "H"), ("55", "56", "I"), ("58", "63", "J"),
                 ("64", "66", "K"), ("68", "68", "L"), ("69", "75", "M"), ("77", "82", "N"), ("84", "84", "O"),
                 ("85", "85", "P"), ("86", "88", "Q"), ("90", "93", "R"), ("94", "96", "S"), ("97", "98", "T"),
                 ("99", "99", "U")]


def isic_section(division) -> str:
    d = str(division or "").zfill(2)[:2]
    for lo, hi, s in ISIC_SECTIONS:
        if lo <= d <= hi:
            return s
    return "?"


# --------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------


def read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def gcs_lines(url: str):
    proc = subprocess.Popen(["gcloud", "storage", "cat", url], stdout=subprocess.PIPE)
    for line in proc.stdout:
        if line.strip():
            yield json.loads(line)
    proc.wait()


def gcs_cat(url: str) -> str:
    return subprocess.run(["gcloud", "storage", "cat", url], capture_output=True, check=True).stdout.decode("utf-8")


def gcs_copy(paths: list[Path], out: str) -> None:
    subprocess.run(["gcloud", "storage", "cp", *[str(p) for p in paths], out.rstrip("/") + "/"], check=True,
                   capture_output=True)


# --------------------------------------------------------------------------
# sample
# --------------------------------------------------------------------------


def stratum(label: dict) -> str:
    if label.get("ai_reference") == "none":
        return "none"
    roles = set(label.get("roles") or [])
    for s in ("governance", "adoption", "risk"):
        if s in roles:
            return s
    return "other_roles"


def systematic(rows: list[dict], n: int, rng: random.Random) -> list[dict]:
    """n rows from a list sorted by section and form: every len/n-th row from a random start."""
    if n >= len(rows):
        return list(rows)
    step = len(rows) / n
    start = rng.random() * step
    return [rows[int(start + i * step)] for i in range(n)]


def sample(args) -> None:
    rng = random.Random(args.seed)
    docs = {d["document_id"]: d for d in json.loads(gcs_cat(f"{args.run}/documents_manifest.json"))["documents"]}
    labels = {r["chunk_id"]: r for r in gcs_lines(f"{args.run}/results/classified_chunks.jsonl")}
    pool = defaultdict(list)
    left_out = Counter()
    for c in gcs_lines(f"{args.run}/chunks.jsonl"):
        lab = labels.get(c["chunk_id"])
        if lab is None:
            continue
        s = stratum(lab)
        if c["chunk_word_len"] > args.max_words:
            left_out[s] += 1
            continue
        d = docs.get(c["document_id"], {})
        conf = lab.get("confidence")
        conf = conf.get("gemini") if isinstance(conf, dict) else conf
        pool[s].append({
            "passage_id": c["chunk_id"], "document_id": c["document_id"], "company": c.get("company_name"),
            "form": d.get("form"), "isic_division": d.get("isic_division"), "isic_section": isic_section(d.get("isic_division")),
            "section": "; ".join(c.get("report_sections") or []), "heading": c.get("heading") or "",
            "words": c["chunk_word_len"], "passage": c["chunk_text"], "stratum": s, "model_confidence": conf,
            "model": {f: lab.get(f) for f in FIELDS if f not in ("confidence", "note")},
        })

    chosen = []
    used_docs = set()

    def draw(rows: list[dict], n: int) -> None:
        rows = [r for r in rows if r["document_id"] not in used_docs]
        rng.shuffle(rows)
        # one passage per filing, then sorted so the systematic draw spreads over sections and forms
        seen, unique = set(), []
        for r in rows:
            if r["document_id"] not in seen:
                seen.add(r["document_id"])
                unique.append(r)
        unique.sort(key=lambda r: (r["isic_section"], r["form"] or ""))
        for r in systematic(unique, n, rng):
            chosen.append(r)
            used_docs.add(r["document_id"])

    for s, n in STRATA.items():
        rows = pool[s]
        if s == "none":
            low = [r for r in rows if r["model_confidence"] in ("low", "medium")]
            draw(low, min(NONE_LOW_CONFIDENCE, len(low)))
            n -= min(NONE_LOW_CONFIDENCE, len(low))
            rows = [r for r in rows if r["model_confidence"] not in ("low", "medium")]
        draw(rows, n)
    rng.shuffle(chosen)

    # Raters: every double-rated passage goes to one pair of raters; pairs rotate so that each pair
    # shares some passages. Single-rated passages go to the rater with the fewest so far.
    raters = list(range(1, args.raters + 1))
    pairs = list(combinations(raters, 2))
    rng.shuffle(pairs)
    load = Counter()
    for i, r in enumerate(chosen):
        if i < args.double:
            r["raters"] = list(pairs[i % len(pairs)])
        else:
            r["raters"] = [min(raters, key=lambda k: (load[k], rng.random()))]
        for k in r["raters"]:
            load[k] += 1

    work = args.work
    write_jsonl(work / "sample.jsonl", chosen)
    write_jsonl(work / "assignment.jsonl", ({"passage_id": r["passage_id"], "raters": r["raters"]} for r in chosen))
    for k in raters:
        mine = [r for r in chosen if k in r["raters"]]
        rng.shuffle(mine)
        with open(work / f"rater_{k}.csv", "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(CONTEXT + [c[0] for c in RATING_COLUMNS])
            for i, r in enumerate(mine, 1):
                w.writerow([i, r["passage_id"], r["company"], r["form"], r["isic_division"], r["section"], r["heading"],
                            r["passage"]] + [""] * len(RATING_COLUMNS))
    summary = {
        "run": args.run, "out": args.out, "passages": len(chosen), "double_rated": args.double, "raters": args.raters,
        "per_rater": {str(k): load[k] for k in raters}, "max_words": args.max_words,
        "strata": {s: sum(1 for r in chosen if r["stratum"] == s) for s in STRATA},
        "left_out_over_max_words": {s: left_out[s] for s in STRATA},
        "pool_within_max_words": {s: len(pool[s]) for s in STRATA},
        "sections": dict(Counter(r["isic_section"] for r in chosen)),
        "forms": dict(Counter(r["form"] for r in chosen)),
    }
    (work / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    args.results.mkdir(parents=True, exist_ok=True)
    (args.results / "sample_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    if args.out:
        gcs_copy([work / "sample.jsonl", work / "assignment.jsonl", work / "summary.json",
                  *[work / f"rater_{k}.csv" for k in raters]], args.out)
    print(f"sample: {len(chosen)} passages, {args.double} double-rated, per rater {dict(load)} -> {work}"
          + (f" and {args.out}" if args.out else ""))
    print("strata:", summary["strata"], "| left out over", args.max_words, "words:", dict(left_out))


# --------------------------------------------------------------------------
# Google Sheets
# --------------------------------------------------------------------------


def token() -> str:
    return subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, check=True).stdout.decode().strip()


def api(method: str, url: str, project: str, body=None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token()}", "Content-Type": "application/json", "x-goog-user-project": project})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read()
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        if method == "DELETE" and e.code == 404:
            return {}
        raise SystemExit(f"{method} {url}: {e.code} {e.read().decode()[:800]}")


def column_letter(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, rem = divmod(i - 1, 26)
        s = chr(65 + rem) + s
    return s


def values_rows() -> list[list[str]]:
    rows = [["field", "value", "definition"]]
    for f, defs in DEFINITIONS.items():
        for v, (definition, _criteria) in defs.items():
            rows.append([f, v, definition])
    rows.append(["confidence", "low / medium / high", "How sure you are of this passage's labels."])
    return rows


def sheets(args) -> None:
    summary = json.loads((args.work / "summary.json").read_text(encoding="utf-8"))
    codebook = gcs_cat(f"{summary['run']}/results/codebook.md").splitlines()
    sheets_api = "https://sheets.googleapis.com/v4/spreadsheets"
    previous = args.work / "sheets.json"
    if previous.exists():
        if not args.replace:
            raise SystemExit(f"{previous} exists; --replace deletes those spreadsheets and creates new ones")
        for k, meta in json.loads(previous.read_text(encoding="utf-8")).items():
            api("DELETE", f"https://www.googleapis.com/drive/v3/files/{meta['spreadsheetId']}", args.project)
            print(f"sheets: rater {k}: previous spreadsheet deleted")
    out = {}
    for k in range(1, summary["raters"] + 1):
        with open(args.work / f"rater_{k}.csv", encoding="utf-8", newline="") as fh:
            rows = list(csv.reader(fh))
        title = f"{args.title}, rater {k}"
        created = api("POST", sheets_api, args.project, {
            "properties": {"title": title},
            "sheets": [
                {"properties": {"title": "Rating", "gridProperties": {"frozenRowCount": 1, "frozenColumnCount": 2}}},
                {"properties": {"title": "Values"}},
                {"properties": {"title": "Codebook"}},
            ],
        })
        sid = created["spreadsheetId"]
        rating_id = created["sheets"][0]["properties"]["sheetId"]
        api("PUT", f"{sheets_api}/{sid}/values/Rating!A1?valueInputOption=RAW", args.project, {"values": rows})
        api("PUT", f"{sheets_api}/{sid}/values/Values!A1?valueInputOption=RAW", args.project, {"values": values_rows()})
        api("PUT", f"{sheets_api}/{sid}/values/Codebook!A1?valueInputOption=RAW", args.project,
            {"values": [[line] for line in codebook]})
        header = rows[0]
        n = len(rows)
        requests = []
        for name, f, _slot in RATING_COLUMNS:
            if f == "note":
                continue
            allowed = SINGLE[f] if f in SINGLE else MULTI[f]
            col = header.index(name)
            requests.append({"setDataValidation": {
                "range": {"sheetId": rating_id, "startRowIndex": 1, "endRowIndex": n, "startColumnIndex": col, "endColumnIndex": col + 1},
                "rule": {"condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": v} for v in allowed]},
                         "showCustomUi": True, "strict": True}}})
        passage_col = header.index("passage")
        requests.append({"repeatCell": {
            "range": {"sheetId": rating_id, "startColumnIndex": passage_col, "endColumnIndex": passage_col + 1},
            "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP", "verticalAlignment": "TOP"}}, "fields": "userEnteredFormat(wrapStrategy,verticalAlignment)"}})
        requests.append({"updateDimensionProperties": {
            "range": {"sheetId": rating_id, "dimension": "COLUMNS", "startIndex": passage_col, "endIndex": passage_col + 1},
            "properties": {"pixelSize": 620}, "fields": "pixelSize"}})
        for name, _f, _slot in RATING_COLUMNS:
            col = header.index(name)
            requests.append({"updateDimensionProperties": {
                "range": {"sheetId": rating_id, "dimension": "COLUMNS", "startIndex": col, "endIndex": col + 1},
                "properties": {"pixelSize": 170}, "fields": "pixelSize"}})
        requests.append({"repeatCell": {
            "range": {"sheetId": rating_id, "startRowIndex": 0, "endRowIndex": 1},
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}}, "fields": "userEnteredFormat.textFormat.bold"}})
        api("POST", f"{sheets_api}/{sid}:batchUpdate", args.project, {"requests": requests})
        out[str(k)] = {"spreadsheetId": sid, "url": created["spreadsheetUrl"], "passages": n - 1}
        print(f"sheets: rater {k}: {n - 1} passages -> {created['spreadsheetUrl']}")
    (args.work / "sheets.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    if summary.get("out"):
        gcs_copy([args.work / "sheets.json"], summary["out"])


# --------------------------------------------------------------------------
# collect
# --------------------------------------------------------------------------


def parse_multi(field: str, rec: dict) -> tuple[list[str], list[str]]:
    """The values of a list field from its slot columns; unknown values are reported, not kept."""
    values, bad = [], []
    for i in range(1, SLOTS[field] + 1):
        v = rec.get(f"{field} {i}", "").strip()
        if not v:
            continue
        if v in MULTI[field]:
            if v not in values:
                values.append(v)
        else:
            bad.append(v)
    return values, bad


def collect(args) -> None:
    sheets_meta = json.loads((args.work / "sheets.json").read_text(encoding="utf-8"))
    problems = []
    for k, meta in sheets_meta.items():
        got = api("GET", f"https://sheets.googleapis.com/v4/spreadsheets/{meta['spreadsheetId']}/values/Rating", args.project)
        rows = got.get("values") or []
        header = rows[0]
        labels = []
        for row in rows[1:]:
            row = row + [""] * (len(header) - len(row))
            rec = dict(zip(header, row))
            if not rec.get("ai_reference"):
                continue  # not rated
            label = {"passage_id": rec["passage_id"], "ai_reference": rec["ai_reference"], "note": rec.get("note", "")}
            for f in ("frame", "adoption_stage", "substantiveness"):
                v = rec.get(f, "").strip()
                if v and v not in SINGLE[f]:
                    problems.append(f"rater {k} {rec['passage_id']} {f}: unknown value {v!r}")
                    v = ""
                label[f] = v or None
            for f in MULTI:
                values, bad = parse_multi(f, rec)
                if bad:
                    problems.append(f"rater {k} {rec['passage_id']} {f}: unknown value(s) {bad}")
                label[f] = values
            label["confidence"] = rec.get("confidence", "").strip() or "high"
            label["ai_kinds"] = []
            label["entities"] = []
            label["evidence"] = []
            labels.append(label)
        write_jsonl(args.work / "labels" / f"human_{k}.jsonl", labels)
        print(f"collect: rater {k}: {len(labels)} of {meta['passages']} passages rated -> labels/human_{k}.jsonl")
    if problems:
        (args.work / "labels" / "problems.txt").write_text("\n".join(problems) + "\n", encoding="utf-8")
        print(f"collect: {len(problems)} value problems -> labels/problems.txt")
    summary = json.loads((args.work / "summary.json").read_text(encoding="utf-8"))
    if summary.get("out"):
        gcs_copy(sorted((args.work / "labels").glob("human_*.jsonl")), summary["out"].rstrip("/") + "/labels")


# --------------------------------------------------------------------------
# agreement
# --------------------------------------------------------------------------


def kappa(pairs: list[tuple[str, str]]) -> float | None:
    """Cohen's kappa for a list of (rating a, rating b); None with fewer than two pairs."""
    if len(pairs) < 2:
        return None
    n = len(pairs)
    po = sum(a == b for a, b in pairs) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(ca[v] * cb[v] for v in set(ca) | set(cb)) / (n * n)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def single_value(label: dict, f: str) -> str:
    return str(label.get(f) or "")


def field_pairs(a: dict, b: dict, f: str) -> dict[str, tuple[str, str]]:
    """Per comparison unit (the field, or field:value for list fields) the two ratings."""
    if f in SINGLE:
        return {f: (single_value(a, f), single_value(b, f))}
    out = {f + " (exact set)": (",".join(sorted(a.get(f) or [])), ",".join(sorted(b.get(f) or [])))}
    for v in MULTI[f]:
        out[f"{f}:{v}"] = (str(v in (a.get(f) or [])), str(v in (b.get(f) or [])))
    return out


def agreement(args) -> None:
    sample_rows = {r["passage_id"]: r for r in read_jsonl(args.work / "sample.jsonl")}
    humans = {}
    for p in sorted((args.work / "labels").glob("human_*.jsonl")):
        k = p.stem.split("_", 1)[1]
        humans[k] = {l["passage_id"]: l for l in read_jsonl(p)}
    fields = [f for f in FIELDS if f not in ("confidence", "note")]

    hh, hm = defaultdict(list), defaultdict(list)
    n_hh = n_hm = 0
    by_stratum = defaultdict(lambda: defaultdict(list))
    for pid, r in sample_rows.items():
        rated = [humans[k][pid] for k in humans if pid in humans[k]]
        model = r["model"]
        for a, b in combinations(rated, 2):
            n_hh += 1
            for f in fields:
                for unit, pair in field_pairs(a, b, f).items():
                    hh[unit].append(pair)
        for h in rated:
            n_hm += 1
            for f in fields:
                for unit, pair in field_pairs(h, model, f).items():
                    hm[unit].append(pair)
                    by_stratum[r["stratum"]][unit].append(pair)

    def fmt(x):
        return "n/a" if x is None else f"{x:.2f}"

    run = json.loads((args.work / "summary.json").read_text(encoding="utf-8"))["run"]
    lines = [f"# Human validation of `{run}`", "",
             f"{len(sample_rows)} passages; {sum(len(v) for v in humans.values())} ratings by {len(humans)} raters; "
             f"{n_hh} human-human pairs; {n_hm} human-model pairs. Cohen's kappa and share of identical ratings.", "",
             "| Field | Human-human kappa | Human-human agree | Human-model kappa | Human-model agree |", "|---|---|---|---|---|"]
    out = {}
    for f in fields:
        units = [f] if f in SINGLE else [f + " (exact set)"] + [f"{f}:{v}" for v in MULTI[f]]
        for unit in units:
            a, b = hh.get(unit, []), hm.get(unit, [])
            # a value nobody used in either rating set is left out of the table
            if unit not in (f, f + " (exact set)") and all(x == "False" and y == "False" for x, y in a + b):
                continue
            row = {"hh_kappa": kappa(a), "hh_agree": (sum(x == y for x, y in a) / len(a)) if a else None,
                   "hm_kappa": kappa(b), "hm_agree": (sum(x == y for x, y in b) / len(b)) if b else None}
            out[unit] = row
            lines.append(f"| {unit} | {fmt(row['hh_kappa'])} | {fmt(row['hh_agree'])} | {fmt(row['hm_kappa'])} | {fmt(row['hm_agree'])} |")
    lines += ["", "## Human-model agreement by stratum", "", "| Stratum | " + " | ".join(f for f in fields if f in SINGLE) + " |",
              "|---|" + "---|" * len([f for f in fields if f in SINGLE])]
    for s in STRATA:
        cells = []
        for f in fields:
            if f in SINGLE:
                p = by_stratum[s].get(f, [])
                cells.append(fmt(sum(x == y for x, y in p) / len(p)) if p else "n/a")
        lines.append(f"| {s} | " + " | ".join(cells) + " |")
    args.results.mkdir(parents=True, exist_ok=True)
    (args.results / "agreement.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (args.results / "agreement.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"agreement: {len(out)} units -> {args.results / 'agreement.md'}")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["sample", "sheets", "collect", "agreement"])
    ap.add_argument("--name", default="us-2025h1_V3", help="folder name under work/ and results/")
    ap.add_argument("--run", help="sample: the run in the bucket, gs://<bucket>/<run>")
    ap.add_argument("--out", help="sample: bucket folder for the sample and the sheets (optional)")
    ap.add_argument("--raters", type=int, default=7)
    ap.add_argument("--double", type=int, default=60, help="passages rated by two raters")
    ap.add_argument("--max-words", type=int, default=400)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--project", help="sheets, collect: Google Cloud project with the Sheets and Drive APIs enabled")
    ap.add_argument("--title", default="AIRO human validation", help="sheets: title prefix of the spreadsheets")
    ap.add_argument("--replace", action="store_true", help="sheets: delete the spreadsheets in sheets.json first")
    args = ap.parse_args()
    args.work = HERE / "work" / args.name
    args.results = HERE / "results" / args.name
    args.work.mkdir(parents=True, exist_ok=True)
    if args.step == "sample" and not args.run:
        ap.error("sample needs --run")
    if args.step in ("sheets", "collect") and not args.project:
        ap.error(f"{args.step} needs --project")
    {"sample": sample, "sheets": sheets, "collect": collect, "agreement": agreement}[args.step](args)


if __name__ == "__main__":
    main()
