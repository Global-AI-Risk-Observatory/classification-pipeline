"""Recall check: a second, independent keyword list applied to the text outside the passages.

The glossaries decide which text becomes a passage, and only passages reach the
classifier. A term the glossaries lack is therefore invisible to every later
stage, and nothing in the labels shows it. This module holds a reference list
that was written independently of the glossaries (the keyword patterns of the
predecessor UK pipeline) and counts, per document, the blocks that match it but
lie in no passage. The count is a property of the run: when it rises, the
glossaries are missing a term.

The reference list is a measuring stick, not a second retrieval step: its hits
do not become passages. A term that turns up here is added to a glossary.
"""

from __future__ import annotations

import re
from collections import Counter

# (name, pattern, case sensitive). Kept as the UK pipeline had them.
REFERENCE_PATTERNS: tuple[tuple[str, str, bool], ...] = (
    ("artificial_intelligence", r"\bartificial\s+intelligence\b", False),
    ("ai", r"\bAI\b", True),  # uppercase only: "Shanghai", "Chairman"
    ("a_i", r"\ba\.i\.\b", False),
    ("machine_learning", r"\bmachine\s+learning\b", False),
    ("ml", r"\bML\b", True),
    ("machine_learned", r"\bmachine[-\s]+learned\b", False),
    ("deep_learning", r"\bdeep\s+learning\b", False),
    ("neural_network", r"\bneural\s+network", False),
    ("neural_net", r"\bneural\s+net(?:s)?\b", False),
    ("deep_neural_network", r"\bdeep\s+neural\s+network(?:s)?\b", False),
    ("large_language_model", r"\blarge\s+language\s+model", False),
    ("llm", r"\bllm\b", False),
    ("language_model", r"\blanguage\s+model(?:s)?\b", False),
    ("foundation_model", r"\bfoundation\s+model(?:s)?\b", False),
    ("generative_ai", r"\bgenerative\s+(?:ai|model)", False),
    ("gen_ai", r"\bgen\s+ai\b", False),
    ("natural_language_processing", r"\bnatural\s+language\s+processing\b", False),
    ("nlp", r"\bnlp\b", False),
    ("computer_vision", r"\bcomputer\s+vision\b", False),
    ("image_recognition", r"\bimage\s+recognition\b", False),
    ("image_classification", r"\bimage\s+classification\b", False),
    ("object_detection", r"\bobject\s+detection\b", False),
    ("semantic_segmentation", r"\bsemantic\s+segmentation\b", False),
    ("intelligent_automation", r"\bintelligent\s+automation\b", False),
    ("rpa", r"\brobotic\s+process\s+automation\b", False),
    ("rpa_acronym", r"\brpa\b", False),
    ("predictive_analytics", r"\bpredictive\s+analytics?\b", False),
    ("chatbot", r"\bchatbot", False),
    ("virtual_assistant", r"\bvirtual\s+assistant", False),
    ("recommendation_system", r"\brecommendation\s+(?:engine|system|algorithm)", False),
    ("autonomous", r"\bautonomous\b", False),
    ("algorithmic", r"\balgorithm(?:ic)?\s+(?:trading|decision|bias)", False),
    ("chatgpt", r"\bchatgpt\b", False),
    ("gpt", r"\bgpt-?\d+\b", False),
    ("gpt_family", r"\bgpt\b", False),
    ("claude", r"\bclaude\b", False),
    ("llama", r"\bllama\b", False),
    ("stable_diffusion", r"\bstable\s+diffusion\b", False),
    ("speech_recognition", r"\bspeech\s+recognition\b", False),
    ("speech_to_text", r"\bspeech[-\s]+to[-\s]+text\b", False),
    ("text_to_speech", r"\btext[-\s]+to[-\s]+speech\b", False),
    ("text_to_image", r"\btext[-\s]+to[-\s]+image\b", False),
    ("text_to_video", r"\btext[-\s]+to[-\s]+video\b", False),
    ("image_generation", r"\bimage\s+generation\b", False),
    ("copilot", r"\bcopilot\b", False),
    ("openai", r"\bopenai\b", False),
    ("anthropic", r"\banthropic\b", False),
    ("deepmind", r"\bdeepmind\b", False),
    ("explainable_ai", r"\bexplainable\s+ai\b", False),
    ("xai", r"\bxai\b", False),
    ("responsible_ai", r"\bresponsible\s+ai\b", False),
    ("ai_ethics", r"\bai\s+ethics\b", False),
    ("ethical_ai", r"\bethical\s+ai\b", False),
    ("ai_governance", r"\bai\s+governance\b", False),
    ("ai_safety", r"\bai\s+safety\b", False),
    ("ai_risk", r"\bai\s+risk(?:s)?\b", False),
    ("ai_audit", r"\bai\s+audit(?:s|ing)?\b", False),
    ("ai_regulation", r"\bai\s+regulation(?:s)?\b", False),
    ("ai_compliance", r"\bai\s+compliance\b", False),
    ("frontier_model", r"\bfrontier\s+model(?:s)?\b", False),
    ("reinforcement_learning", r"\breinforcement\s+learning\b", False),
    ("agentic", r"\bagentic\b", False),
    ("ai_agent", r"\bai\s+agent(?:s)?\b", False),
    ("intelligent_agent", r"\bintelligent\s+agent(?:s)?\b", False),
    ("multimodal", r"\bmultimodal\b", False),
    ("cognitive_computing", r"\bcognitive\s+computing\b", False),
)

_COMPILED = tuple((name, re.compile(rx, 0 if exact else re.I)) for name, rx, exact in REFERENCE_PATTERNS)
# Pre-filter: one alternation per case mode rejects the blocks without any hit.
_ANY = tuple(
    re.compile("|".join(f"(?:{rx})" for _, rx, exact in REFERENCE_PATTERNS if exact is mode), 0 if mode else re.I)
    for mode in (True, False)
)


def find(text: str) -> list[str]:
    """Names of the reference patterns that match `text`."""
    if not any(rx.search(text) for rx in _ANY):
        return []
    return [name for name, rx in _COMPILED if rx.search(text)]


def outside(blocks: list[dict], passages: list[dict]) -> dict:
    """Reference-pattern hits of one document that lie in no passage.

    Returns {"blocks": number of blocks with at least one hit, "by_pattern":
    {pattern name: number of such blocks}}. Page furniture is not searched, as
    in retrieval.
    """
    covered = {i for p in passages for i in range(p["blocks"][0], p["blocks"][1] + 1)}
    by_pattern: Counter = Counter()
    n = 0
    for b in blocks:
        if b["kind"] == "furniture" or b["i"] in covered:
            continue
        if names := find(b["text"]):
            n += 1
            by_pattern.update(names)
    return {"blocks": n, "by_pattern": dict(by_pattern.most_common())}


def total(summaries: list[dict]) -> dict:
    """The recall check of a run, from the report summaries.

    Documents processed before the check existed carry no count and are left
    out of `documents_checked`.
    """
    checked = [s["recall_check"] for s in summaries if s.get("recall_check") is not None]
    by_pattern: Counter = Counter()
    for c in checked:
        by_pattern.update(c["by_pattern"])
    return {
        "documents": len(summaries),
        "documents_checked": len(checked),
        "documents_affected": sum(c["blocks"] > 0 for c in checked),
        "blocks_outside_passages": sum(c["blocks"] for c in checked),
        "by_pattern": dict(by_pattern.most_common()),
    }
