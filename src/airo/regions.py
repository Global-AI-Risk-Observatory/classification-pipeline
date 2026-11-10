"""Regions: what differs between the filings of one part of the world and another, as data.

Everything else in the pipeline is the same for every filing. A region names

- `countries` and `languages`: what `fetch` asks the data provider for (ISO 3166 country codes,
  ISO 639-1 language codes of the filing as the provider records it);
- `company_ids`: the manifest fields that identify a company, in order of preference. A filing's
  company is the first of them that is known (`company_key`). US filings are identified by their
  CIK, as before; filings outside the SEC system have no CIK and are identified by their LEI;
- `sections`: how a filing is divided into sections. `"items"` takes SEC Item headings only (the
  US behavior: a filing without them has no sections). `"items_or_headings"` takes SEC Items where
  a filing has them (a non-US company filing a 20-F) and otherwise the filing's chapter headings
  (`ingest.chapter_level`).

Languages are not part of the codebook: the codebook describes concepts and is the same for every
language. The vocabulary of a language lives in its glossary (`glossaries/core.<language>.json`),
which `glossary.load` adds to the English core glossary for a filing in that language.

A filing whose country is unknown is treated as US, as every filing was before regions existed.
"""

from __future__ import annotations

from dataclasses import dataclass

# The 27 member states of the European Union (ISO 3166-1 alpha-2; Greece is GR at the provider).
EU_COUNTRIES = (
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE",
    "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
)


@dataclass(frozen=True)
class Region:
    name: str
    label: str
    countries: tuple[str, ...]
    languages: tuple[str, ...]  # empty: every language
    company_ids: tuple[str, ...]
    sections: str  # "items" | "items_or_headings"


US = Region("us", "US", ("US",), ("en",), ("cik",), "items")
EU = Region("eu", "EU", EU_COUNTRIES, ("en", "de", "fr", "es"), ("cik", "lei"), "items_or_headings")
REGIONS = {r.name: r for r in (US, EU)}

# A manifest field the provider did not fill holds this text instead (see fetch.MISSING).
_UNKNOWN = "not provided by the data provider"


def of_country(country: str | None) -> Region:
    """The region a filing belongs to by its company's country; unknown or US is the US region."""
    if not country or country == _UNKNOWN or country == "US":
        return US
    for region in REGIONS.values():
        if country in region.countries:
            return region
    raise ValueError(f"country {country} belongs to no region in airo.regions.REGIONS")


def company_key(record: dict) -> str | None:
    """The company of a document or manifest row: the first known field of its region's `company_ids`.

    If none is known, the value of the first field as it stands (None or the provider's missing-value
    text), so a US filing without a CIK is treated exactly as before.
    """
    fields = of_country(record.get("country")).company_ids
    for field in fields:
        value = record.get(field)
        if value and value != _UNKNOWN:
            return value
    return record.get(fields[0])
