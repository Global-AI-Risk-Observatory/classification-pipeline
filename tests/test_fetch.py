"""Tests for the download stage (airo.fetch).

The provider's API is replaced by a fake `get` and Cloud Storage by a fake
client; nothing goes over the network.
"""

from __future__ import annotations

import json
import urllib.parse

import pytest

from airo import cli, fetch
from test_pipeline import read_jsonl

MARKDOWN = """**FORM 10-K**

For the fiscal year ended December 31 , 2024

**Item 1. Business**

We mine uranium in Texas and Wyoming. We use machine learning to plan our drilling.

**Item 1A. Risk Factors**

• Our artificial intelligence models may produce inaccurate results.

| Mine | Output |
| --- | --- |
| Rosita | 100 |
"""


def api_filing(id: int, country: str = "US", form: str | None = "10-K", **fields) -> dict:
    """A row of the filing listing (view=full). Company ids are 100 + filing id."""
    return {
        "id": id,
        "release_datetime": "2025-02-14T21:05:00+00:00",
        "filing_date": "2025-02-14",
        "fiscal_year": 2024,
        "fiscal_period": "FY",
        "period_ending_date": "2024-12-31",
        "source_filing_id": f"0000000000-25-{id:06d}",
        "company": {
            "id": 100 + id, "name": f"Acme {id}", "lei": f"LEI{id}",
            "sub_industry_code": "0721", "country_code": country,
        },
        "filing_type": {"code": "10-K"},
        "source_filing_type": form,
        **fields,
    }


def api_company(id: int, ticker: str | None = "ACME", cik: str = "CIK0000012345", exchanges: tuple = ("Nasdaq",)) -> dict:
    """A row of the company listing (view=full)."""
    return {
        "id": id, "name": f"Acme {id - 100}", "ticker": ticker, "local_company_id": cik,
        "main_stock_exchange": "", "listed_stock_exchange": [{"id": 49, "name": n} for n in exchanges],
    }


class FakeApi:
    """Serves the filing and company listings in pages of `page_size`, the Markdown of each filing and
    single companies; records every request. By default every filing's company is in the company list."""

    def __init__(self, filings: list[dict], markdown: dict | None = None, page_size: int = 2, companies: list[dict] | None = None):
        self.filings, self.markdown, self.page_size = filings, markdown or {}, page_size
        self.companies = [api_company(f["company"]["id"]) for f in filings] if companies is None else companies
        self.late: dict[int, dict] = {}  # companies not in the list, served only one by one
        self.requests: list[tuple[str, dict]] = []

    def __call__(self, url: str, headers: dict | None = None) -> bytes:
        self.requests.append((url, headers or {}))
        path = urllib.parse.urlparse(url).path
        if path.endswith("/markdown/"):
            body = self.markdown.get(int(path.split("/")[-3]), MARKDOWN.encode())
            if isinstance(body, Exception):
                raise body
            return body
        if path.startswith("/companies/") and path != "/companies/":
            id = int(path.split("/")[-2])
            if id not in self.late:
                raise OSError("HTTP Error 404")
            return json.dumps(self.late[id]).encode()
        rows = self.companies if path == "/companies/" else self.filings
        page = int(urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("page", ["1"])[0])
        more = page * self.page_size < len(rows)
        rows = rows[(page - 1) * self.page_size : page * self.page_size]
        return json.dumps({"results": rows, "next": f"{url.split('&page=')[0]}&page={page + 1}" if more else None}).encode()

    def downloads(self) -> list[int]:
        return [int(u.split("/")[-3]) for u, _ in self.requests if u.endswith("/markdown/")]

    def paths(self, prefix: str) -> list[str]:
        return [urllib.parse.urlparse(u).path for u, _ in self.requests if urllib.parse.urlparse(u).path.startswith(prefix)]


class PreconditionFailed(Exception):
    pass


class NotFound(Exception):
    pass


class FakeBlob:
    def __init__(self, objects: dict, name: str):
        self.objects, self.name = objects, name

    def upload_from_string(self, data, if_generation_match=None):
        assert if_generation_match == 0, "objects must only ever be created"
        if self.name in self.objects:
            raise PreconditionFailed(self.name)
        self.objects[self.name] = data

    def download_as_bytes(self) -> bytes:
        if self.name not in self.objects:
            raise NotFound(self.name)
        return self.objects[self.name]


class FakeGcs:
    """A bucket as a dict of object name -> bytes, with the two calls GcsStore makes."""

    def __init__(self, objects: dict | None = None):
        self.objects = objects if objects is not None else {}

    def bucket(self, name: str):
        self.bucket_name = name
        return self

    def blob(self, name: str) -> FakeBlob:
        return FakeBlob(self.objects, name)

    def list_blobs(self, prefix: str):
        return [FakeBlob(self.objects, n) for n in sorted(self.objects) if n.startswith(prefix)]


@pytest.fixture
def gcs(monkeypatch):
    import sys
    import types

    exceptions = types.ModuleType("google.api_core.exceptions")
    exceptions.PreconditionFailed = PreconditionFailed
    exceptions.NotFound = NotFound
    for name in ("google", "google.api_core"):
        monkeypatch.setitem(sys.modules, name, sys.modules.get(name) or types.ModuleType(name))
    monkeypatch.setitem(sys.modules, "google.api_core.exceptions", exceptions)
    return FakeGcs()


def run(out, api, **kwargs):
    return fetch.fetch(out, "secret-key", kwargs.pop("types", "10-K"), get=api, log=lambda *_: None, **kwargs)


def test_listing_asks_for_us_companies_and_the_given_types_only(tmp_path):
    api = FakeApi([api_filing(1)])
    run(tmp_path, api, types="10-K,10-Q", form="10-K", since="2025-01-01", until="2025-03-31")

    (list_url, list_headers), (doc_url, doc_headers) = api.requests[:2]
    query = urllib.parse.parse_qs(urllib.parse.urlparse(list_url).query)
    assert query["countries"] == ["US"] and query["view"] == ["full"]
    assert query["types"] == ["10-K,10-Q"] and query["source_filing_type"] == ["10-K"]
    assert query["release_datetime_from"] == ["2025-01-01"] and query["release_datetime_to"] == ["2025-03-31"]
    assert doc_url == f"{fetch.API}/filings/1/markdown/"
    assert list_headers["x-api-key"] == doc_headers["x-api-key"] == "secret-key"


def test_without_a_form_every_filing_of_the_types_is_listed(tmp_path):
    api = FakeApi([api_filing(1, form="ARS"), api_filing(2, form="20-F")])
    counts = run(tmp_path, api)

    assert "source_filing_type" not in api.requests[0][0]
    assert counts == {"done": 2, "present": 0, "failed": 0}


def test_fetch_stores_only_markdown_and_one_manifest_file_per_filing(tmp_path):
    api = FakeApi([api_filing(1), api_filing(2), api_filing(3)])
    counts = run(tmp_path, api)

    assert counts == {"done": 3, "present": 0, "failed": 0}
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()) == [
        "companies/us.jsonl",
        "manifest/1.json", "manifest/2.json", "manifest/3.json",
        "markdown/1.md", "markdown/2.md", "markdown/3.md",
    ]
    assert (tmp_path / "markdown" / "1.md").read_text(encoding="utf-8") == MARKDOWN
    assert json.loads((tmp_path / "manifest" / "1.json").read_text(encoding="utf-8")) == {
        "file": "1.md", "isic_class": "0721", "isic_division": "07", "country": "US",
        "source": "financialfilings.com", "filing_id": 1, "filing_type": "10-K",
        "company": "Acme 1", "lei": "LEI1", "cik": "0000012345", "ticker": "ACME", "exchange": "Nasdaq",
        "form": "10-K", "fiscal_year": 2024, "fiscal_period": "FY", "period_end": "2024-12-31",
        "filing_date": "2025-02-14", "source_filing_id": "0000000000-25-000001",
        "released": "2025-02-14T21:05:00+00:00",
    }
    assert not any("secret-key" in p.read_text(encoding="utf-8") for p in tmp_path.rglob("*") if p.is_file())


def test_a_filing_already_stored_is_not_requested_again(tmp_path):
    first = FakeApi([api_filing(i) for i in range(1, 6)])
    assert run(tmp_path, first, limit=2)["done"] == 2
    before = (tmp_path / "markdown" / "1.md").stat().st_mtime_ns

    second = FakeApi([api_filing(i) for i in range(1, 6)], {1: b"changed upstream"})
    counts = run(tmp_path, second, limit=2)

    assert counts == {"done": 2, "present": 2, "failed": 0}
    assert second.downloads() == [3, 4]
    assert (tmp_path / "markdown" / "1.md").read_text(encoding="utf-8") == MARKDOWN
    assert (tmp_path / "markdown" / "1.md").stat().st_mtime_ns == before
    assert sorted(p.name for p in (tmp_path / "markdown").iterdir()) == ["1.md", "2.md", "3.md", "4.md"]


def test_the_same_filing_fetched_by_two_people_at_once_is_stored_once(tmp_path):
    class Racing(fetch.DirStore):
        """Someone else stores filing 1 after the names were read and before this run writes it."""

        def create(self, name, data):
            if name == "markdown/1.md":
                (self.root / "markdown").mkdir(parents=True, exist_ok=True)
                (self.root / name).write_bytes(b"theirs")
            return super().create(name, data)

    counts = run(Racing(tmp_path), FakeApi([api_filing(1), api_filing(2)]))

    assert counts == {"done": 1, "present": 1, "failed": 0}
    assert (tmp_path / "markdown" / "1.md").read_bytes() == b"theirs"
    assert sorted(p.name for p in (tmp_path / "markdown").iterdir()) == ["1.md", "2.md"]


def test_a_filing_of_another_country_is_never_stored(tmp_path):
    api = FakeApi([api_filing(1, country="GB"), api_filing(2)])
    counts = run(tmp_path, api)

    assert counts == {"done": 1, "present": 0, "failed": 1}
    assert api.downloads() == [2]
    assert [p.name for p in (tmp_path / "markdown").iterdir()] == ["2.md"]


def test_a_filing_without_markdown_is_counted_and_the_rest_continues(tmp_path):
    api = FakeApi([api_filing(1), api_filing(2), api_filing(3)], {1: OSError("HTTP Error 404"), 2: b"  \n"})
    counts = run(tmp_path, api)

    assert counts == {"done": 1, "present": 0, "failed": 2}
    assert [p.name for p in (tmp_path / "markdown").iterdir()] == ["3.md"]
    assert [p.name for p in (tmp_path / "manifest").iterdir()] == ["3.json"]
    assert not list(tmp_path.rglob("*.tmp"))


def test_cloud_storage_objects_are_created_under_the_prefix_and_never_overwritten(gcs):
    target = fetch.GcsStore("gs://airo-filings-raw/us", client=gcs)
    gcs.objects["us/markdown/1.md"] = b"stored earlier"
    gcs.objects["us/markdown/old/9.md"] = b"not a filing of this layout"
    gcs.objects["other/markdown/2.md"] = b"another prefix"

    api = FakeApi([api_filing(1), api_filing(2)])
    counts = run(target, api)

    assert gcs.bucket_name == "airo-filings-raw"
    assert counts == {"done": 1, "present": 1, "failed": 0}
    assert api.downloads() == [2]
    assert gcs.objects["us/markdown/1.md"] == b"stored earlier"
    assert gcs.objects["us/markdown/2.md"] == MARKDOWN.encode()
    assert json.loads(gcs.objects["us/manifest/2.json"])["file"] == "2.md"
    assert target.create("markdown/2.md", b"again") is False
    assert gcs.objects["us/markdown/2.md"] == MARKDOWN.encode()


def test_cloud_storage_location_without_a_prefix(gcs):
    target = fetch.GcsStore("gs://airo-filings-raw", client=gcs)
    run(target, FakeApi([api_filing(7)]))
    assert sorted(gcs.objects) == ["companies/us.jsonl", "manifest/7.json", "markdown/7.md"]
    assert target.names("markdown") == {"7.md"}


def test_fetched_filings_run_through_the_pipeline(tmp_path):
    raw, data = tmp_path / "raw", tmp_path / "work"
    run(raw, FakeApi([api_filing(1)]))

    cli.main(["--data", str(data), "run", str(raw / "markdown"), "--manifest", str(raw / "manifest"), "--workers", "1"])

    (doc_dir,) = (data / "docs").iterdir()
    doc = json.loads((doc_dir / "document.json").read_text(encoding="utf-8"))
    assert doc["source_files"] == ["1.md"]
    assert (doc["company"], doc["country"], doc["form"], doc["isic_class"], doc["filing_id"]) == ("Acme 1", "US", "10-K", "0721", 1)
    assert (doc["fiscal_year"], doc["period_end"]) == (2024, "2024-12-31")
    assert list(doc["sections"]) == ["Item 1", "Item 1A"]
    passages = read_jsonl(doc_dir / "passages.jsonl")
    assert {p["section"] for p in passages} == {"Item 1", "Item 1A"}


def test_metadata_costs_no_request_per_filing_and_the_company_list_is_read_once(tmp_path):
    filings = [api_filing(i) for i in range(1, 6)]
    first = FakeApi(filings, page_size=100)
    run(tmp_path, first, limit=3)

    # one filing listing, one company listing, one Markdown per stored filing; no detail request
    assert first.paths("/filings/") == ["/filings/"] + [f"/filings/{i}/markdown/" for i in (1, 2, 3)]
    assert first.paths("/companies/") == ["/companies/"]
    query = urllib.parse.parse_qs(urllib.parse.urlparse(first.requests[2][0]).query)
    assert query["countries"] == ["US"] and query["view"] == ["full"]

    second = FakeApi(filings, page_size=100)
    run(tmp_path, second, limit=2)

    assert second.paths("/companies/") == []  # read from the store, not from the provider
    assert json.loads((tmp_path / "manifest" / "5.json").read_text(encoding="utf-8"))["cik"] == "0000012345"


def test_the_company_list_is_not_read_when_nothing_new_is_stored(tmp_path):
    run(tmp_path, FakeApi([api_filing(1)]))
    again = FakeApi([api_filing(1)])
    (tmp_path / "companies" / "us.jsonl").unlink()

    run(tmp_path, again)

    assert again.paths("/companies/") == [] and again.downloads() == []


def test_what_the_provider_leaves_empty_comes_from_the_cover_page(tmp_path):
    cover = """**FORM 10-K**

For the fiscal year ended September 30 , 2025

| Title of each class | Trading Symbol(s) | Name of each exchange on which registered |
| --- | --- | --- |
| Common Stock, $0.01 par value | ACM | New York Stock Exchange |
| Preferred Stock | ACM-PA | New York Stock Exchange |

**Item 1. Business**

We mine uranium.
"""
    filing = api_filing(1, form=None, fiscal_year=None, period_ending_date=None)
    api = FakeApi([filing], {1: cover.encode()}, companies=[api_company(101, ticker=None, exchanges=())])
    run(tmp_path, api)

    row = json.loads((tmp_path / "manifest" / "1.json").read_text(encoding="utf-8"))
    assert (row["form"], row["fiscal_year"], row["period_end"]) == ("10-K", 2025, "2025-09-30")
    assert (row["ticker"], row["exchange"]) == ("ACM", "New York Stock Exchange")
    assert row["cik"] == "0000012345"


def test_a_field_nobody_fills_carries_a_notice_instead_of_being_left_out(tmp_path):
    filing = api_filing(
        1, form=None, fiscal_year=None, fiscal_period=None, period_ending_date=None,
        filing_date=None, source_filing_id=None,
    )
    filing["company"]["lei"] = ""
    api = FakeApi([filing], {1: b"**Annual Report**\n\nWe mine uranium.\n"}, companies=[])
    logged = []
    fetch.fetch(tmp_path, "secret-key", "10-K", get=api, log=logged.append)

    row = json.loads((tmp_path / "manifest" / "1.json").read_text(encoding="utf-8"))
    notice = "not provided by the data provider"
    empty = ["lei", "cik", "ticker", "exchange", "form", "fiscal_year", "fiscal_period", "period_end", "filing_date", "source_filing_id"]
    assert {k: row[k] for k in empty} == dict.fromkeys(empty, notice)
    assert (row["company"], row["country"], row["isic_class"], row["released"]) == ("Acme 1", "US", "0721", "2025-02-14T21:05:00+00:00")
    assert any("1.md" in line and "no cik, exchange, filing_date" in line for line in logged)


def test_a_company_missing_from_the_list_is_asked_for_once_and_kept(tmp_path):
    api = FakeApi([api_filing(1), api_filing(2, release_datetime="2025-02-15T00:00:00+00:00")], companies=[api_company(101)])
    api.late[102] = api_company(102, ticker="LATE", cik="EODHD_LSE_LATE,CIK0000099999", exchanges=("NYSE", "Nasdaq"))
    api.filings[1]["company"]["id"] = 102
    run(tmp_path, api)

    assert api.paths("/companies/") == ["/companies/", "/companies/102/"]
    row = json.loads((tmp_path / "manifest" / "2.json").read_text(encoding="utf-8"))
    assert (row["cik"], row["ticker"], row["exchange"]) == ("0000099999", "LATE", "NYSE, Nasdaq")
    assert json.loads((tmp_path / "companies" / "102.json").read_text(encoding="utf-8"))["ticker"] == "LATE"

    later = FakeApi([api_filing(3)], companies=[])
    later.filings[0]["company"]["id"] = 102
    run(tmp_path, later)

    assert later.paths("/companies/") == []
    assert json.loads((tmp_path / "manifest" / "3.json").read_text(encoding="utf-8"))["ticker"] == "LATE"


def test_api_key_comes_from_the_environment_or_the_env_file(tmp_path, monkeypatch):
    env = tmp_path / ".env.local"
    monkeypatch.delenv("FR_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="FR_API_KEY is not set"):
        fetch.api_key(env)
    env.write_text("# Financial Reports API\nOTHER=1\nFR_API_KEY='from-file'\n", encoding="utf-8")
    assert fetch.api_key(env) == "from-file"
    monkeypatch.setenv("FR_API_KEY", "from-env")
    assert fetch.api_key(env) == "from-env"
