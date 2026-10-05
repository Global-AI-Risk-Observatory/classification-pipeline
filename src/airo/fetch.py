"""Stage 0: copy filings of US companies from the data provider into the raw bucket.

    python -m airo fetch gs://airo-filings-raw --types 10-K --since 2025-01-01 --limit 100

Asks the FinancialReports API (financialfilings.com) for filings of US companies
and stores each filing's Markdown rendering, and nothing else, as

    <out>/markdown/<filing id>.md      the filing
    <out>/manifest/<filing id>.json    its metadata, in the format `run --manifest` reads
    <out>/companies/us.jsonl           the provider's US companies (CIK, ticker, exchange), fetched once

`<out>` is a Cloud Storage location (`gs://bucket[/prefix]`) or a directory, e.g.
the mounted bucket of a Batch job. Nothing is kept on the machine that runs it.

A filing is stored once. Its name is the provider's filing id, so the same filing
has the same name whoever fetches it; the names already in `<out>` are read
before anything is requested, and those filings are skipped without an API
request. Objects are only ever created, never overwritten, so two people
fetching the same filing at the same time still leave one copy.

Metadata costs no request per filing. The filing's own (fiscal year, period,
source filing id) comes with the listing that is read anyway (`view=full`, 100
filings per request); the company's comes from the company list, which is read
from the provider once (100 companies per request) and then from `<out>`. Where
the provider has no value, the filing's cover page is used, and where that has
none either, the manifest says so (`MISSING`) instead of leaving the field out.

The API key is personal (the provider counts requests per key) and is read from
the environment variable `FR_API_KEY`, or from `.env.local` in the current
directory, which git ignores. It is sent to the API only and never stored.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Iterator

from . import ingest

API = "https://api.financialreports.eu"
SOURCE = "financialfilings.com"
COUNTRY = "US"
KEY_VAR = "FR_API_KEY"
# Written into a manifest field that neither the provider nor the filing's cover page fills.
MISSING = "not provided by the data provider"
COMPANIES = "companies/us.jsonl"
_PAGE_SIZE = 100
_RETRY_STATUS = {429, 500, 502, 503, 504}


def api_key(env_file: Path = Path(".env.local")) -> str:
    """The key from the environment, else from `env_file` (lines of NAME=value)."""
    key = os.environ.get(KEY_VAR, "").strip()
    if not key and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, sep, value = line.partition("=")
            if sep and name.strip() == KEY_VAR:
                key = value.strip().strip("\"'")
    if not key:
        raise SystemExit(f"{KEY_VAR} is not set: export it or put {KEY_VAR}=<your key> in {env_file}")
    return key


def http_get(url: str, headers: dict | None = None, retries: int = 4, backoff: float = 2.0) -> bytes:
    """GET `url`; a rate-limit or server error is retried with a growing pause."""
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code not in _RETRY_STATUS or attempt == retries:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries:
                raise
        time.sleep(backoff * 2**attempt)
    raise AssertionError("unreachable")


class DirStore:
    """Files under a directory, e.g. a bucket mounted into a Batch job."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def names(self, prefix: str) -> set[str]:
        """The file names directly under `prefix`."""
        d = self.root / prefix
        return {p.name for p in d.iterdir() if not p.name.startswith(".")} if d.is_dir() else set()

    def read(self, name: str) -> bytes | None:
        """The content of `name`, or None if there is no such file."""
        path = self.root / name
        return path.read_bytes() if path.is_file() else None

    def create(self, name: str, data: bytes) -> bool:
        """Write `data` as `name` unless it exists. Returns whether it was written."""
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp.write_bytes(data)
        try:
            os.link(tmp, path)  # fails if `path` exists; never replaces it
            return True
        except FileExistsError:
            return False
        finally:
            tmp.unlink()

    def __str__(self) -> str:
        return str(self.root)


class GcsStore:
    """Objects under gs://bucket[/prefix], through the google-cloud-storage package."""

    def __init__(self, url: str, client=None):
        bucket, _, prefix = url.removeprefix("gs://").partition("/")
        if client is None:
            try:
                from google.cloud import storage
            except ImportError as e:
                raise SystemExit(
                    "a gs:// location needs the google-cloud-storage package: pip install google-cloud-storage"
                ) from e
            client = storage.Client()
        self.url = url.rstrip("/")
        self.bucket = client.bucket(bucket)
        self.prefix = prefix.strip("/") + "/" if prefix.strip("/") else ""

    def names(self, prefix: str) -> set[str]:
        full = f"{self.prefix}{prefix.strip('/')}/"
        return {b.name[len(full):] for b in self.bucket.list_blobs(prefix=full) if "/" not in b.name[len(full):]}

    def read(self, name: str) -> bytes | None:
        from google.api_core.exceptions import NotFound

        try:
            return self.bucket.blob(self.prefix + name).download_as_bytes()
        except NotFound:
            return None

    def create(self, name: str, data: bytes) -> bool:
        from google.api_core.exceptions import PreconditionFailed

        try:
            # Generation 0 = "only if there is no such object": the bucket refuses a second copy.
            self.bucket.blob(self.prefix + name).upload_from_string(data, if_generation_match=0)
            return True
        except PreconditionFailed:
            return False

    def __str__(self) -> str:
        return self.url


def store(out: str | Path) -> DirStore | GcsStore:
    return GcsStore(out) if str(out).startswith("gs://") else DirStore(Path(out))


def listing(
    key: str,
    types: str,
    form: str | None = None,
    since: str | None = None,
    until: str | None = None,
    get: Callable = http_get,
) -> Iterator[dict]:
    """Every filing of a US company with one of the provider's `types`, oldest release first.

    `form` narrows to the form the filing was submitted as (e.g. the provider's
    type 10-K covers the SEC forms 10-K, 10-K/A, 20-F and ARS).
    """
    # view=full adds fiscal year, period and source filing id to every row at no extra request.
    params = {
        "countries": COUNTRY, "types": types, "view": "full",
        "ordering": "release_datetime", "page_size": _PAGE_SIZE,
    }
    if form:
        params["source_filing_type"] = form
    if since:
        params["release_datetime_from"] = since
    if until:
        params["release_datetime_to"] = until
    url = f"{API}/filings/?{urllib.parse.urlencode(params)}"
    while url:
        page = json.loads(get(url, {"x-api-key": key, "Accept": "application/json"}))
        yield from page["results"]
        url = page.get("next")


def _company_row(c: dict) -> dict:
    """The fields of a company (list or detail, view=full) that go into manifests."""
    exchanges = [e.get("name") for e in c.get("listed_stock_exchange") or [] if e.get("name")]
    # local_company_id lists the company's ids at several sources: "CIK0000040545,EODHD_LSE_GEC".
    ids = [i.strip() for i in (c.get("local_company_id") or "").split(",")]
    cik = next((i[3:] for i in ids if i.upper().startswith("CIK") and i[3:].isdigit()), None)
    return {
        "id": c["id"],
        "cik": cik,
        "ticker": c.get("ticker") or None,
        "exchange": ", ".join(exchanges) or c.get("main_stock_exchange") or None,
    }


class Companies:
    """CIK, ticker and exchange per company id, at one request per 100 companies, once.

    The list of the provider's US companies is kept in `target` as `companies/us.jsonl`.
    Whoever fetches first reads it from the API; everyone after reads it from
    `target`. A company that joined the provider later is asked for on its own
    and kept as `companies/<id>.json`.
    """

    def __init__(self, target, key: str, get: Callable = http_get, log=print):
        self.target, self.key, self.get, self.log = target, key, get, log
        raw = target.read(COMPANIES)
        if raw is None:
            log(f"company list not in {target} yet: reading it from the provider, once")
            rows, url = [], f"{API}/companies/?{urllib.parse.urlencode({'countries': COUNTRY, 'view': 'full', 'page_size': _PAGE_SIZE})}"
            while url:
                page = json.loads(get(url, self._headers()))
                rows += [_company_row(c) for c in page["results"]]
                url = page.get("next")
            target.create(COMPANIES, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode("utf-8"))
            raw = target.read(COMPANIES)  # the list that is there now, ours or someone else's
        self.rows = {r["id"]: r for r in map(json.loads, raw.decode("utf-8").splitlines())}
        log(f"{len(self.rows)} US companies in {target}/{COMPANIES}")

    def _headers(self) -> dict:
        return {"x-api-key": self.key, "Accept": "application/json"}

    def __getitem__(self, company_id: int | None) -> dict:
        if company_id is None:
            return {}
        if company_id not in self.rows:
            name = f"companies/{company_id}.json"
            raw = self.target.read(name)
            if raw is None:
                try:
                    raw = json.dumps(_company_row(json.loads(self.get(f"{API}/companies/{company_id}/", self._headers())))).encode()
                    self.target.create(name, raw)
                except Exception as e:  # the filing is still stored; its manifest says what is missing
                    self.log(f"company {company_id}: {e}")
                    raw = b"{}"
            self.rows[company_id] = json.loads(raw)
        return self.rows[company_id]


def manifest_row(filing: dict, file: str, company_meta: dict | None = None, cover: dict | None = None) -> dict:
    """The metadata of one filing; `run` copies it into the document record.

    A Markdown filing carries no XBRL facts, so its metadata comes from here.
    Each field takes the provider's value (`filing` is a row of the listing,
    `company_meta` the company's row of the company list), else what the
    filing's `cover` page states, else `MISSING`.
    """
    company, company_meta, cover = filing.get("company") or {}, company_meta or {}, cover or {}
    isic = company.get("sub_industry_code") or None
    described = {
        "company": company.get("name"),
        "lei": company.get("lei"),
        "cik": company_meta.get("cik"),
        "ticker": company_meta.get("ticker") or cover.get("ticker"),
        "exchange": company_meta.get("exchange") or cover.get("exchange"),
        "form": filing.get("source_filing_type") or cover.get("form"),
        "fiscal_year": filing.get("fiscal_year") or cover.get("fiscal_year"),
        "fiscal_period": filing.get("fiscal_period"),
        "period_end": filing.get("period_ending_date") or cover.get("period_end"),
        "filing_date": filing.get("filing_date"),
        "source_filing_id": filing.get("source_filing_id"),
        "released": filing.get("release_datetime"),
    }
    return {
        "file": file,
        "isic_class": isic,
        "isic_division": isic[:2] if isic else None,
        "country": company.get("country_code"),
        "source": SOURCE,
        "filing_id": filing["id"],
        "filing_type": (filing.get("filing_type") or {}).get("code"),
        **{k: v if v not in (None, "") else MISSING for k, v in described.items()},
    }


def fetch(
    out: str | Path | DirStore | GcsStore,
    key: str,
    types: str,
    form: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int | None = None,
    get: Callable = http_get,
    log=print,
) -> dict:
    """Store up to `limit` filings that `out` does not hold yet. Returns the counters (done, present, failed)."""
    target = out if isinstance(out, (DirStore, GcsStore)) else store(out)
    present = target.names("markdown")
    log(f"{len(present)} filing(s) already in {target}")
    companies = None
    counts = {"done": 0, "present": 0, "failed": 0}
    for filing in listing(key, types, form, since, until, get):
        if limit is not None and counts["done"] >= limit:
            break
        company = filing.get("company") or {}
        name = f"{filing['id']}.md"
        if name in present:
            counts["present"] += 1
            continue
        try:
            if company.get("country_code") != COUNTRY:
                raise ValueError(f"not a US company ({company.get('country_code')})")
            markdown = get(f"{API}/filings/{filing['id']}/markdown/", {"x-api-key": key})
            if not markdown.strip():
                raise ValueError("empty Markdown")
        except Exception as e:  # one bad filing must not stop the rest
            counts["failed"] += 1
            log(f"failed  {filing['id']}  {company.get('name')}: {e}")
            continue
        if companies is None:  # only once there is a filing to store
            companies = Companies(target, key, get, log)
        row = manifest_row(filing, name, companies[company.get("id")], ingest.cover_metadata(markdown.decode("utf-8", "replace")))
        missing = sorted(k for k, v in row.items() if v == MISSING)
        # The manifest first: a filing whose Markdown is in the bucket always has its metadata.
        target.create(f"manifest/{filing['id']}.json", json.dumps(row, ensure_ascii=False).encode("utf-8"))
        if target.create(f"markdown/{name}", markdown):
            counts["done"] += 1
            note = f"  (no {', '.join(missing)})" if missing else ""
            log(f"{counts['done']}  {name}  {company.get('name')}  {(filing.get('release_datetime') or '')[:10]}{note}")
        else:  # someone else stored it since the names were read
            counts["present"] += 1
        present.add(name)
    log(f"stored {counts['done']}, already present {counts['present']}, failed {counts['failed']} -> {target}")
    return counts
