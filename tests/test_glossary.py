"""Tests for airo.glossary: term matching and glossary loading.

Synthetic glossaries only, written to tmp_path in the documented shape
(core.json plus isic/<division>.json with class_terms). The real files under
glossaries/ are never read.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from airo import glossary

CORE = {
    "id": "core",
    "name": "Core AI vocabulary",
    "terms": [
        {
            "term": "artificial intelligence",
            "tier": "ai",
            "variants": ["AI", "A.I."],
            "case_sensitive_variants": ["AI", "A.I."],
            "why": "the core term and its abbreviations",
        },
        {"term": "machine learning", "tier": "ai", "variants": ["ML model"], "why": "a sub-field"},
        {"term": "chatbot", "tier": "ai", "why": "an AI product"},
        {"term": "data center", "tier": "context", "variants": ["data centre"], "why": "where AI runs"},
    ],
}
MINING = {
    "id": "07",
    "name": "Mining of metal ores",
    "terms": [
        {
            "term": "autonomous haulage",
            "tier": "ai",
            "variants": ["driverless truck", "AHS"],
            "case_sensitive_variants": ["AHS"],
            "why": "driverless mine trucks",
        }
    ],
    "class_terms": {
        "0721": [
            {
                "term": "in-situ recovery",
                "tier": "context",
                "variants": ["ISR"],
                "case_sensitive_variants": ["ISR"],
                "why": "uranium extraction method",
            }
        ]
    },
}


@pytest.fixture
def root(tmp_path) -> Path:
    (tmp_path / "isic").mkdir()
    (tmp_path / "core.json").write_text(json.dumps(CORE), encoding="utf-8")
    (tmp_path / "isic" / "07.json").write_text(json.dumps(MINING), encoding="utf-8")
    return tmp_path


@pytest.fixture
def core() -> glossary.Matcher:
    return glossary.Matcher([("core", CORE["terms"])])


# --------------------------------------------------------------------------
# matching
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "We use AI in our mills.",
        "AI-driven demand is rising.",
        "Artificial intelligence (AI) is new.",
        "RISKS RELATED TO AI",
        "“AI” in quotes",
        "A.I. with dots",
    ],
)
def test_case_sensitive_variant_matches_as_a_whole_word(core, text):
    assert core.find(text) == {"ai": ["artificial intelligence"]}


@pytest.mark.parametrize(
    "text",
    [
        "The Chairman said we maintain an office in Shanghai.",
        "THE CHAIRMAN SAID WE MAINTAIN AN OFFICE IN SHANGHAI.",
        "said",
        "Shanghai",
        "Chairman",
        "maintain",
        "ai",
        "Ai",
        "AIG and FAIR and PAID",
        "",
    ],
)
def test_case_sensitive_variant_never_matches_inside_words_or_in_other_case(core, text):
    assert core.find(text) == {}


@pytest.mark.parametrize(
    "text",
    [
        "Our data center is in Austin.",
        "Power demand from data centers is growing.",
        "Data-center operators buy power.",
        "DATA CENTERS use power.",
        "Our data centre is in Leeds.",
        "Two data centres in Leeds.",
    ],
)
def test_plural_hyphen_space_and_case_variation_hit_the_canonical_term(core, text):
    assert core.find(text) == {"context": ["data center"]}


@pytest.mark.parametrize("text", ["datacenter", "data centered", "metadata center", "data"])
def test_phrase_tokens_stay_whole_words(core, text):
    assert core.find(text) == {}


@pytest.mark.parametrize(
    "text",
    ["Machine Learning", "MACHINE LEARNING", "machine-learning models", "We train ML models."],
)
def test_phrases_without_case_sensitive_variants_match_in_any_case(core, text):
    assert core.find(text) == {"ai": ["machine learning"]}


def test_variants_report_the_canonical_term(root):
    matcher = glossary.load("0721", root=root)

    assert matcher.find("Driverless trucks haul ore.") == {"ai": ["autonomous haulage"]}
    assert matcher.find("The AHS fleet grew.") == {"ai": ["autonomous haulage"]}
    assert matcher.find("ISR wells at Palangana.") == {"context": ["in-situ recovery"]}
    assert matcher.find("Our ML model and chatbot.") == {"ai": ["chatbot", "machine learning"]}


def test_only_the_listed_variants_are_case_sensitive(root):
    matcher = glossary.load("0721", root=root)

    assert matcher.find("ahs") == {}
    assert matcher.find("isr") == {}
    assert matcher.find("AUTONOMOUS HAULAGE") == {"ai": ["autonomous haulage"]}
    assert matcher.find("In Situ Recovery") == {"context": ["in-situ recovery"]}


def test_find_groups_hits_by_tier_in_tier_order(core):
    found = core.find("Machine learning workloads at AI data centers.")

    assert found == {"ai": ["artificial intelligence", "machine learning"], "context": ["data center"]}
    assert list(found) == list(glossary.TIERS)


def test_matcher_length_counts_distinct_phrases():
    # "AI" is a variant and a case-sensitive variant of the same term: one phrase.
    terms = [{"term": "artificial intelligence", "tier": "ai", "variants": ["AI"], "case_sensitive_variants": ["AI"]}]

    assert len(glossary.Matcher([("x", terms)])) == 2


# --------------------------------------------------------------------------
# trie pre-filter
# --------------------------------------------------------------------------


def every_phrase() -> list[str]:
    terms = CORE["terms"] + MINING["terms"] + MINING["class_terms"]["0721"]
    return [p for t in terms for p in [t["term"], *t.get("variants", [])]]


@pytest.mark.parametrize("phrase", every_phrase())
def test_trie_prefilter_accepts_every_phrase_the_per_term_search_finds(root, phrase):
    """The pre-filter may only reject blocks; it must never drop one the per-term search would hit."""
    matcher = glossary.load("0721", root=root)
    text = f"We discussed {phrase} last year."

    assert matcher.find(text), phrase
    assert any(rx.search(text.replace("-", " ")) for rx in matcher._any), phrase


@pytest.mark.parametrize(
    "text",
    ["We mine uranium in Texas.", "The Chairman said we maintain an office in Shanghai.", "datacenter"],
)
def test_trie_prefilter_and_per_term_search_agree_on_a_block_without_a_hit(root, text):
    matcher = glossary.load("0721", root=root)

    assert matcher.find(text) == {}
    assert not any(rx.search(text.replace("-", " ")) for rx in matcher._any)


def test_trie_regex_merges_shared_prefixes_and_matches_each_phrase():
    rx = re.compile(glossary._trie_regex(["data center", "data centre", "data-scientist", "chatbot"]), re.I)

    assert rx.pattern.count("data") == 1
    for text in ("a data center", "DATA CENTRES", "data scientists", "chatbots"):
        assert rx.search(text), text
    for text in ("datacenter", "data", "centre", "scientist", "chatbotting"):
        assert not rx.search(text), text


def test_trie_prefilter_accepts_a_phrase_that_is_a_prefix_of_one_other_phrase():
    terms = [
        {"term": "machine learning", "tier": "ai", "variants": ["machine learning model"]},
        {"term": "data center", "tier": "context", "variants": ["data center operator"]},
    ]
    matcher = glossary.Matcher([("x", terms)])

    assert matcher.find("We use machine learning.") == {"ai": ["machine learning"]}
    assert matcher.find("Our data center is in Austin.") == {"context": ["data center"]}


# --------------------------------------------------------------------------
# loading
# --------------------------------------------------------------------------


def test_load_class_takes_core_division_and_class_terms(root):
    matcher = glossary.load("0721", root=root)

    assert matcher.sources == ["core", "isic:07", "isic:0721"]
    assert matcher.find("AI, autonomous haulage and ISR.") == {
        "ai": ["artificial intelligence", "autonomous haulage"],
        "context": ["in-situ recovery"],
    }


def test_load_class_without_class_terms_takes_core_and_division(root):
    matcher = glossary.load("0710", root=root)

    assert matcher.sources == ["core", "isic:07"]
    assert matcher.find("autonomous haulage") == {"ai": ["autonomous haulage"]}
    assert matcher.find("ISR") == {}


@pytest.mark.parametrize("isic_class", [None, "", "9999"])
def test_load_unknown_class_takes_core_only(root, isic_class):
    matcher = glossary.load(isic_class, root=root)

    assert matcher.sources == ["core"]
    assert matcher.find("We use AI.") == {"ai": ["artificial intelligence"]}
    assert matcher.find("autonomous haulage and ISR") == {}


def test_load_is_cached_per_class_and_root(root):
    assert glossary.load("0721", root=root) is glossary.load("0721", root=root)
    assert glossary.load("0721", root=root) is not glossary.load("0710", root=root)
