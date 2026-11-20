"""How many EU annual reports that are not in English also exist in English.

Reads the provider's listing of the filings of companies in the 27 EU member states with the types
10-K and 10-K-ESEF, released from --first to --last, without a language filter, and keeps one line of
metadata per filing (no report is downloaded). A report is one company, fiscal year and language; a
company that files the same year as 10-K and as 10-K-ESEF in one language counts once. A report that
is not in English "also exists in English" if the same company has a filing in English for the same
fiscal year. Where the provider gives no fiscal year, the release year stands in for it.

It runs as a Cloud Batch job with the bucket mounted, never on a workstation:

    python english_counterparts.py --out /mnt/disks/out/analysis/languages

Output in --out:

    listing/<year>.jsonl          one line per filing: id, company id, LEI, country, language, type,
                                  fiscal year, release date
    english_counterparts.json     the counts per language and per fiscal year
    english_counterparts.md       the same as tables

A release year whose listing file exists is not requested again.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
from collections import Counter, defaultdict
from pathlib import Path

from airo.fetch import API, api_key, http_get

EU_COUNTRIES = "AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE".split()
TYPES = "10-K,10-K-ESEF"
NO_LANGUAGE = "not provided by the data provider"


def get(url: str, headers: dict) -> dict:
    for attempt in range(8):
        try:
            return json.loads(http_get(url, headers))
        except Exception as e:  # http_get has already retried rate limits and server errors
            print(f"retry {attempt + 1} after {type(e).__name__} {getattr(e, 'code', '')}", flush=True)
            time.sleep(30 * (attempt + 1))
    raise SystemExit(f"no answer from the provider for {url.split('?')[0]}")


def list_year(year: int, headers: dict) -> list[dict]:
    params = {
        "countries": ",".join(EU_COUNTRIES), "types": TYPES, "view": "full", "ordering": "release_datetime",
        "page_size": 100, "release_datetime_from": f"{year}-01-01", "release_datetime_to": f"{year}-12-31",
    }
    url = f"{API}/filings/?{urllib.parse.urlencode(params)}"
    rows, expected = [], None
    while url:
        page = get(url, headers)
        expected = page.get("count") if expected is None else expected
        for f in page["results"]:
            company, lang = f.get("company") or {}, f.get("language") or {}
            rows.append({
                "filing_id": f.get("id"), "company_id": company.get("id"), "lei": company.get("lei"),
                "company": company.get("name"), "country": company.get("country_code"),
                "language": lang.get("code") or NO_LANGUAGE, "language_name": lang.get("name"),
                "type": (f.get("filing_type") or {}).get("code"), "fiscal_year": f.get("fiscal_year"),
                "released": f.get("release_datetime"),
            })
        print(f"{year}: {len(rows)} of {expected}", flush=True)
        url = page.get("next")
    if expected is not None and len(rows) != expected:
        raise SystemExit(f"{year}: listed {len(rows)}, the provider counts {expected}")
    return rows


def counterparts(rows: list[dict]) -> dict:
    """Reports (company, fiscal year, language) and, for those not in English, whether English exists."""
    languages_of = defaultdict(set)  # (company, year) -> languages
    names = {}
    no_company = 0
    for r in rows:
        company = r["company_id"] or r["lei"]
        if company is None:
            no_company += 1
            continue
        year = r["fiscal_year"] or (r["released"] or "")[:4]
        languages_of[(company, str(year))].add(r["language"])
        if r.get("language_name"):
            names[r["language"]] = r["language_name"]
    by_language = defaultdict(lambda: Counter())
    by_year = defaultdict(lambda: Counter())
    companies = defaultdict(lambda: defaultdict(set))
    for (company, year), langs in languages_of.items():
        for lang in langs:
            if lang == "en":
                by_year[year]["english"] += 1
                continue
            has = "en" in langs
            for c in (by_language[lang], by_year[year]):
                c["reports"] += 1
                c["with_english"] += has
            companies[lang]["all"].add(company)
            if has:
                companies[lang]["with_english"].add(company)
    return {
        "unit": "one company, fiscal year and language",
        "filings": len(rows), "filings_without_company": no_company, "names": names,
        "by_language": {l: {**dict(c), "companies": len(companies[l]["all"]),
                            "companies_with_english_in_some_year": len(companies[l]["with_english"])}
                        for l, c in by_language.items()},
        "by_fiscal_year": {y: dict(c) for y, c in sorted(by_year.items())},
    }


def tables(res: dict) -> str:
    lines = ["# EU annual reports not in English: how many also exist in English", "",
             f"{res['filings']} filings (types {TYPES}, 27 member states). A report is {res['unit']}; it also exists in "
             "English if the same company has an English filing for the same fiscal year.", "",
             "| Language | Reports | Also in English | Share | Companies | Companies with English in some year |", "|---|---|---|---|---|---|"]
    total = Counter()
    for lang, c in sorted(res["by_language"].items(), key=lambda x: -x[1]["reports"]):
        name = res["names"].get(lang)
        n, e = c["reports"], c.get("with_english", 0)
        total["reports"] += n
        total["with_english"] += e
        lines.append(f"| {name + ' (' + lang + ')' if name else lang} | {n} | {e} | {e / n:.0%} | {c['companies']} | {c['companies_with_english_in_some_year']} |")
    n, e = total["reports"], total["with_english"]
    lines.append(f"| All languages other than English | {n} | {e} | {e / n:.0%} | | |" if n else "| none | | | | | |")
    lines += ["", "| Fiscal year | Reports not in English | Also in English | Share | Reports in English |", "|---|---|---|---|---|"]
    for y, c in res["by_fiscal_year"].items():
        n, e = c.get("reports", 0), c.get("with_english", 0)
        lines.append(f"| {y} | {n} | {e} | {(f'{e / n:.0%}' if n else '')} | {c.get('english', 0)} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--first", type=int, default=2020)
    ap.add_argument("--last", type=int, default=2026)
    args = ap.parse_args()
    listing = args.out / "listing"
    listing.mkdir(parents=True, exist_ok=True)
    headers = {"x-api-key": api_key(), "Accept": "application/json"}
    rows = []
    for year in range(args.first, args.last + 1):
        file = listing / f"{year}.jsonl"
        if file.exists():
            got = [json.loads(l) for l in file.read_text(encoding="utf-8").splitlines() if l.strip()]
            print(f"{year}: {len(got)} filings read from {file}", flush=True)
        else:
            got = list_year(year, headers)
            file.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in got), encoding="utf-8")
        rows += got
    res = counterparts(rows)
    (args.out / "english_counterparts.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    (args.out / "english_counterparts.md").write_text(tables(res), encoding="utf-8")
    print("done", flush=True)


if __name__ == "__main__":
    main()
