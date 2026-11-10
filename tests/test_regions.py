"""Regions and languages: what a non-US filing changes, and that a US filing is handled as before."""

import json
import urllib.parse

import pytest

from airo import classify, fetch, glossary, ingest, regions
from airo.coders import gemini

MISSING = "not provided by the data provider"


# --- regions -------------------------------------------------------------------------------------

@pytest.mark.parametrize("country", [None, "", MISSING, "US"])
def test_unknown_or_us_country_is_the_us_region(country):
    assert regions.of_country(country) is regions.US


@pytest.mark.parametrize("country", ["DE", "FR", "ES", "IE", "AT", "BE", "LU", "MT", "NL", "SE"])
def test_eu_member_states_are_the_eu_region(country):
    assert regions.of_country(country) is regions.EU


def test_a_country_of_no_region_is_refused():
    with pytest.raises(ValueError, match="belongs to no region"):
        regions.of_country("JP")


def test_eu_has_27_member_states():
    assert len(set(regions.EU_COUNTRIES)) == 27


def test_us_company_is_its_cik_even_without_one():
    assert regions.company_key({"country": "US", "cik": "0000012345", "lei": "LEI1"}) == "0000012345"
    assert regions.company_key({"country": "US", "cik": MISSING, "lei": "LEI1"}) == MISSING
    assert regions.company_key({"cik": None, "lei": "LEI1"}) is None


def test_eu_company_is_its_cik_if_it_has_one_else_its_lei():
    assert regions.company_key({"country": "NL", "cik": "0000937966", "lei": "LEI2"}) == "0000937966"
    assert regions.company_key({"country": "DE", "cik": MISSING, "lei": "LEI3"}) == "LEI3"
    assert regions.company_key({"country": "DE", "cik": None, "lei": MISSING}) is None


# --- sections ------------------------------------------------------------------------------------

EU_REPORT = """# Annual Report 2025

# Lagebericht

Die Gesellschaft entwickelt Software.

## Geschäftsmodell

Wir nutzen KI in der Fertigung.

# Risikobericht

## Technologische Risiken

Der Einsatz von KI kann zu Fehlern führen.

# Konzernabschluss

Text.
"""

US_REPORT = """**Item 1A. Risk Factors**

We use AI.

**Item 7. Management's Discussion and Analysis**

Text.
"""


def _parse(tmp_path, text, mode):
    path = tmp_path / "r.md"
    path.write_text(text, encoding="utf-8")
    return ingest.parse(path, mode)


def test_chapter_level_is_the_shallowest_level_used_three_times():
    assert ingest.chapter_level([1, 2, 1, 2, 1, 3]) == 1
    assert ingest.chapter_level([1, 2, 2, 2, 3]) == 2
    assert ingest.chapter_level([1, 3]) is None


def test_filing_without_items_has_no_sections_in_items_mode(tmp_path):
    doc, blocks = _parse(tmp_path, EU_REPORT, "items")
    assert doc["sections"] == {}
    assert {b["section"] for b in blocks} == {None}


def test_filing_without_items_is_divided_by_its_chapters(tmp_path):
    doc, blocks = _parse(tmp_path, EU_REPORT, "items_or_headings")
    assert list(doc["sections"]) == ["Annual Report 2025", "Lagebericht", "Risikobericht", "Konzernabschluss"]
    hit = next(b for b in blocks if "kann zu Fehlern" in b["text"])
    assert hit["section"] == "Risikobericht" and hit["heading"] == "Technologische Risiken"


def test_filing_with_items_keeps_its_items_in_either_mode(tmp_path):
    items, _ = _parse(tmp_path, US_REPORT, "items")
    either, _ = _parse(tmp_path, US_REPORT, "items_or_headings")
    assert items["sections"] == either["sections"]
    assert list(items["sections"]) == ["Item 1A", "Item 7"]


def test_sections_mode_does_not_change_the_document_id_or_blocks_of_a_filing_with_items(tmp_path):
    a, ba = _parse(tmp_path, US_REPORT, "items")
    b, bb = _parse(tmp_path, US_REPORT, "items_or_headings")
    assert a["doc_id"] == b["doc_id"] and ba == bb


def test_unknown_sections_mode_is_refused(tmp_path):
    with pytest.raises(ValueError, match="sections_mode"):
        _parse(tmp_path, US_REPORT, "chapters")


# --- glossaries ----------------------------------------------------------------------------------

def _hits(text, language):
    return glossary.load(None, language=language).find(text).get("ai", [])


def test_a_language_glossary_applies_only_to_filings_in_that_language():
    assert "künstliche Intelligenz" in _hits("Wir setzen KI-gestützte Prozesse ein.", "de")
    assert _hits("Wir setzen KI-gestützte Prozesse ein.", "en") == []
    assert _hits("Wir setzen KI-gestützte Prozesse ein.", None) == []
    assert _hits("Nous utilisons l'IA générative.", "fr") and _hits("Nous utilisons l'IA générative.", "es")
    assert _hits("The IA division grew.", "en") == []


def test_the_english_core_glossary_applies_in_every_language():
    assert "ChatGPT" in _hits("Nos équipes utilisent ChatGPT.", "fr")
    assert "artificial intelligence" in _hits("Die AI-Strategie des Konzerns.", "de")


def test_inflected_forms_hit_the_canonical_term():
    assert _hits("Einsatz maschinellen Lernens und neuronaler Netze", "de") == ["maschinelles Lernen", "neuronales Netz"]
    assert _hits("redes neuronales y aprendizaje automático", "es") == ["aprendizaje automático", "red neuronal"]


def test_abbreviations_are_case_sensitive():
    assert _hits("Die Kinder spielen, ki ist kein Wort.", "de") == []
    assert _hits("ia en minuscules", "fr") == []


def test_a_language_without_a_glossary_gets_the_english_core_only():
    assert glossary.load(None, language="it").sources == ["core"]
    assert glossary.load(None, language="de").sources == ["core", "core.de"]
    assert glossary.load(None).sources == ["core"]


@pytest.mark.parametrize("code", ["de", "fr", "es"])
def test_language_glossaries_hold_ai_terms_with_a_reason(code):
    terms = json.loads((glossary.GLOSSARY_DIR / f"core.{code}.json").read_text(encoding="utf-8"))["terms"]
    assert terms and all(t["tier"] == "ai" and t["why"] and t["group"] for t in terms)


# --- tasks and prompts ---------------------------------------------------------------------------

def _task(pid, language=None, text="We use AI."):
    t = {"passage_id": pid, "company": "ACME", "form": "10-K", "fiscal_year": 2025, "section": None,
         "heading": None, "matched_terms": {"ai": ["artificial intelligence"]}, "text": text}
    if language:
        t["language"] = language
    return t


def test_tasks_carry_the_language_only_when_it_is_known():
    doc = {"doc_id": "d", "company": "A", "form": "Annual Report", "fiscal_year": 2025}
    p = {"passage_id": "d:1-2", "doc_id": "d", "section": None, "section_title": None, "heading": None,
         "matched": {}, "text": "x"}
    assert "language" not in classify.tasks([doc], [p])[0]
    assert "language" not in classify.tasks([{**doc, "language": MISSING}], [p])[0]
    assert classify.tasks([{**doc, "language": "de"}], [p])[0]["language"] == "de"


def test_by_language_keeps_the_order_of_tasks_without_language():
    tasks = [_task(str(i)) for i in range(5)]
    assert classify.by_language(tasks) == tasks


def test_by_language_puts_the_tasks_of_one_language_together():
    tasks = [_task("1", "fr"), _task("2"), _task("3", "de"), _task("4", "en"), _task("5", "fr")]
    assert [t["passage_id"] for t in classify.by_language(tasks)] == ["3", "2", "4", "1", "5"]


def test_batches_without_languages_are_the_plain_slices():
    tasks = [_task(str(i)) for i in range(95)]
    assert gemini.batches(tasks, 40) == [tasks[0:40], tasks[40:80], tasks[80:95]]


def test_a_batch_never_holds_two_languages():
    tasks = [_task("1", "de"), _task("2", "de"), _task("3", "fr"), _task("4")]
    assert [[t["passage_id"] for t in b] for b in gemini.batches(tasks, 40)] == [["1", "2"], ["3"], ["4"]]


def test_english_tasks_render_and_prompt_as_before():
    tasks = [_task("1"), _task("2", "en")]
    assert "Language" not in gemini.render_task(tasks[0]) and "Language" not in gemini.render_task(tasks[1])
    assert gemini._OTHER_LANGUAGE not in gemini.build_batch_prompt("CODEBOOK", tasks)
    assert gemini._OTHER_LANGUAGE not in gemini.build_prompt("CODEBOOK", tasks[0])


def test_foreign_tasks_name_their_language_and_get_the_instruction_once():
    tasks = [_task("1", "de"), _task("2", "de")]
    prompt = gemini.build_batch_prompt("CODEBOOK", tasks)
    assert prompt.count(gemini._OTHER_LANGUAGE) == 1 and prompt.count("Language: de") == 2
    assert gemini.build_prompt("CODEBOOK", tasks[0]).count(gemini._OTHER_LANGUAGE) == 1


def test_quotes_in_guillemets_are_found_again():
    text = classify._squash("Le Groupe précise que « l'IA générative » est utilisée.")
    # A model asked for JSON tends to swap the guillemets for straight quotes and the apostrophe for a straight one.
    assert classify._locate('Le Groupe précise que " l\'IA générative " est utilisée.', text) == text


def test_near_copies_compare_accented_words_as_words():
    assert classify._words("Künstliche Intelligenz für Prozesse") == {"künstliche", "intelligenz", "für", "prozesse"}


def test_copies_of_an_eu_company_are_grouped_by_its_lei():
    doc = {"country": "DE", "cik": MISSING, "lei": "LEI9", "released": "2025-04-01"}
    entries = [(_task("a", "de", "Wir nutzen KI."), doc), (_task("b", "de", "Wir nutzen KI."), {**doc, "form": "x"})]
    tasks, copies = classify.collapse_copies(entries)
    assert [t["passage_id"] for t in tasks] == ["a"] and copies == [{"passage_id": "b", "copy_of": "a"}]


# --- fetch ---------------------------------------------------------------------------------------

class _Api:
    def __init__(self):
        self.urls = []

    def __call__(self, url, headers=None):
        self.urls.append(url)
        return json.dumps({"results": [], "next": None}).encode()


def _query(url):
    return urllib.parse.parse_qs(urllib.parse.urlparse(url).query)


def test_us_listing_is_asked_for_as_before():
    api = _Api()
    list(fetch.listing("k", "10-K", get=api))
    q = _query(api.urls[0])
    assert q["countries"] == ["US"] and "languages" not in q


def test_eu_listing_asks_for_the_member_states_and_the_languages():
    api = _Api()
    list(fetch.listing("k", "10-K,10-K-ESEF", get=api, region=regions.EU))
    q = _query(api.urls[0])
    assert q["countries"] == [",".join(regions.EU_COUNTRIES)] and q["languages"] == ["en,de,fr,es"]


def test_company_list_is_kept_per_region():
    assert fetch.companies_file(regions.US) == "companies/us.jsonl"
    assert fetch.companies_file(regions.EU) == "companies/eu.jsonl"


def test_manifest_of_an_eu_filing_has_its_language_and_the_provider_type_as_form():
    filing = {"id": 5, "company": {"name": "X AG", "lei": "LEI5", "country_code": "DE", "sub_industry_code": "2620"},
              "filing_type": {"code": "10-K-ESEF", "name": "Annual Report (ESEF)"}, "language": {"code": "de"},
              "source_filing_type": None, "fiscal_year": 2024}
    row = fetch.manifest_row(filing, "5.md")
    assert row["language"] == "de" and row["form"] == "Annual Report (ESEF)" and row["country"] == "DE"
    assert regions.company_key(row) == "LEI5"
