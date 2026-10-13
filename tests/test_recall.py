"""The recall check: reference patterns applied to the blocks outside the passages."""

from airo import glossary, recall, retrieve


def block(i: int, text: str, kind: str = "paragraph") -> dict:
    return {"i": i, "kind": kind, "text": text, "section": "Item 1", "heading": None}


def test_reference_list_is_the_one_of_the_predecessor_pipeline():
    names = [name for name, _, _ in recall.REFERENCE_PATTERNS]
    assert len(names) == len(set(names)) == 66
    assert [name for name, _, exact in recall.REFERENCE_PATTERNS if exact] == ["ai", "ml"]


def test_find_names_every_pattern_that_matches_and_respects_case():
    assert recall.find("We use machine learning and an LLM.") == ["machine_learning", "llm"]
    assert recall.find("Our AI roadmap") == ["ai"]
    assert recall.find("Shanghai and the chairman said") == []  # "ai" only in upper case, as a word
    assert recall.find("ml of water") == []
    assert recall.find("Speech-to-text and GPT-4") == ["gpt", "gpt_family", "speech_to_text"]
    assert recall.find("") == []


def test_outside_counts_only_blocks_that_lie_in_no_passage():
    blocks = [
        block(0, "We use artificial intelligence in underwriting."),
        block(1, "Claims are handled by our staff."),
        block(2, "An autonomous haulage fleet operates in the pit."),
        block(3, "Table of Contents: Artificial Intelligence", kind="furniture"),
        block(4, "The LLM and the chatbot are autonomous."),
        block(5, "Nothing to see."),
    ]
    passages = [{"blocks": [0, 1]}]

    assert recall.outside(blocks, passages) == {
        "blocks": 2,
        "by_pattern": {"autonomous": 2, "llm": 1, "chatbot": 1},
    }
    assert recall.outside(blocks, [{"blocks": [0, 5]}]) == {"blocks": 0, "by_pattern": {}}
    assert recall.outside([], []) == {"blocks": 0, "by_pattern": {}}


def test_total_adds_up_the_documents_and_leaves_out_those_without_a_check():
    summaries = [
        {"recall_check": {"blocks": 2, "by_pattern": {"autonomous": 2, "llm": 1}}},
        {"recall_check": {"blocks": 0, "by_pattern": {}}},
        {"recall_check": {"blocks": 1, "by_pattern": {"llm": 1}}},
        {"recall_check": None},  # processed before the check existed
        {},
    ]
    assert recall.total(summaries) == {
        "documents": 5,
        "documents_checked": 3,
        "documents_affected": 2,
        "blocks_outside_passages": 3,
        "by_pattern": {"autonomous": 2, "llm": 2},
    }


def test_the_core_glossary_finds_the_terms_the_check_showed_missing():
    matcher = glossary.load()
    assert matcher.find("An autonomous haulage fleet operates in the pit.") == {"context": ["autonomous"]}
    assert matcher.find("Our multi-modal freight network grew.") == {"context": ["multimodal"]}
    # They are context terms: on their own they make an implicit mention, which is classified like any other.
    doc = {"doc_id": "d1", "sections": {}, "isic_class": None}
    (p,) = retrieve.passages(doc, [block(0, "An autonomous haulage fleet operates in the pit.")], matcher=matcher)
    assert p["mention"] == "implicit"
    assert recall.outside([block(0, "An autonomous haulage fleet operates in the pit.")], [p]) == {"blocks": 0, "by_pattern": {}}
