"""EU annual reports per language and release year, counted from the data provider's listing.

For every release year from --first to --last the script reads the provider's listing of the filings of
companies in the 27 EU member states with the types 10-K and 10-K-ESEF (the provider's two types for
annual reports), without a language filter, and counts the language the provider records for each
filing. No report is downloaded; only the listing is read (100 filings per request).

It runs as a Cloud Batch job with the bucket mounted, never on a workstation:

    python count_languages.py --out /mnt/disks/out/analysis/languages

Output in --out:

    languages_by_year.json   {"years": {year: {"listed": n, "provider_count": n, "languages": {code: n}}},
                              "names": {code: language name}, "types": {year: {type: {code: n}}}}
    languages_by_year.md     the same as a table, languages ordered by their total
    progress.log             one line per request page

A year that is already in languages_by_year.json is not requested again, so an interrupted job can be
started a second time. "provider_count" is the total the provider reports for the year's listing; it
equals "listed" when every page was read.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
from collections import Counter
from pathlib import Path

from airo.fetch import API, api_key, http_get

# The 27 member states, as in airo.regions; listed here so the script also runs on an image without that module.
EU_COUNTRIES = "AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE".split()
TYPES = "10-K,10-K-ESEF"
NO_LANGUAGE = "not provided by the data provider"


def get(url: str, headers: dict, log) -> dict:
    """One page; a failed request is repeated with a growing pause (the provider answers 503 at times)."""
    for attempt in range(8):
        try:
            return json.loads(http_get(url, headers))
        except Exception as e:  # http_get has already retried rate limits and server errors
            log(f"retry {attempt + 1} after {type(e).__name__} {getattr(e, 'code', '')}")
            time.sleep(30 * (attempt + 1))
    raise SystemExit(f"no answer from the provider for {url.split('?')[0]}")


def count_year(year: int, headers: dict, log) -> dict:
    params = {
        "countries": ",".join(EU_COUNTRIES), "types": TYPES, "view": "full", "ordering": "release_datetime",
        "page_size": 100, "release_datetime_from": f"{year}-01-01", "release_datetime_to": f"{year}-12-31",
    }
    url = f"{API}/filings/?{urllib.parse.urlencode(params)}"
    languages, by_type, names = Counter(), {}, {}
    listed, provider_count, pages = 0, None, 0
    while url:
        page = get(url, headers, log)
        if provider_count is None:
            provider_count = page.get("count")
        for f in page["results"]:
            lang = f.get("language") or {}
            code = lang.get("code") or NO_LANGUAGE
            if lang.get("name"):
                names[code] = lang["name"]
            ftype = (f.get("filing_type") or {}).get("code") or "type not given"
            languages[code] += 1
            by_type.setdefault(ftype, Counter())[code] += 1
            listed += 1
        pages += 1
        log(f"{year} page {pages}: {listed} of {provider_count}")
        url = page.get("next")
    return {"listed": listed, "provider_count": provider_count, "languages": dict(languages),
            "types": {t: dict(c) for t, c in by_type.items()}, "names": names}


def table(result: dict) -> str:
    years = sorted(result["years"])
    total = Counter()
    for y in years:
        total.update(result["years"][y]["languages"])
    lines = ["# EU annual reports per language and release year", "",
             f"Filings of companies in the 27 EU member states, provider types {TYPES}, as listed by the data provider.", "",
             "| Language | " + " | ".join(years) + " | Total |", "|---|" + "---|" * (len(years) + 1)]
    for code, n in total.most_common():
        name = result["names"].get(code)
        label = f"{name} ({code})" if name else code
        lines.append(f"| {label} | " + " | ".join(str(result["years"][y]["languages"].get(code, 0)) for y in years) + f" | {n} |")
    lines.append("| All | " + " | ".join(str(result["years"][y]["listed"]) for y in years) + f" | {sum(total.values())} |")
    lines.append("| Provider's count | " + " | ".join(str(result["years"][y]["provider_count"]) for y in years) + " | |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--first", type=int, default=2020)
    ap.add_argument("--last", type=int, default=2026)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    result_file = args.out / "languages_by_year.json"
    result = json.loads(result_file.read_text(encoding="utf-8")) if result_file.exists() else {"years": {}, "names": {}, "types": {}}
    progress = open(args.out / "progress.log", "a", encoding="utf-8")

    def log(s: str) -> None:
        print(s, flush=True)
        progress.write(s + "\n")
        progress.flush()

    headers = {"x-api-key": api_key(), "Accept": "application/json"}
    for year in range(args.first, args.last + 1):
        if str(year) in result["years"]:
            log(f"{year}: already counted")
            continue
        got = count_year(year, headers, log)
        result["names"].update(got.pop("names"))
        result["types"][str(year)] = got.pop("types")
        result["years"][str(year)] = got
        result_file.write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
        (args.out / "languages_by_year.md").write_text(table(result), encoding="utf-8")
        log(f"{year}: {got['listed']} filings listed, provider's count {got['provider_count']}")
    log("done")


if __name__ == "__main__":
    main()
