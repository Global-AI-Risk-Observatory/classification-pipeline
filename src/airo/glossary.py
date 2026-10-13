"""Glossaries: one core AI vocabulary plus one glossary per industry.

Industries follow ISIC Rev. 5, the classification the data provider attaches to
every company. A document is searched with
  core.json  +  isic/<division>.json  +  that file's class_terms[<class>]
so a telecom operator and a uranium miner are searched with different lingo.

Each term has a tier:
  "ai"       the term itself denotes AI (a hit is enough),
  "context"  industry lingo around which AI is discussed (not proof by itself).
"""

from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

# Repo checkout: <root>/glossaries. Installed package (container): set AIRO_GLOSSARIES.
GLOSSARY_DIR = Path(os.environ.get("AIRO_GLOSSARIES") or Path(__file__).resolve().parents[2] / "glossaries")
TIERS = ("ai", "context")


def _pattern(phrase: str) -> str:
    """Regex for a phrase: whole words, any hyphen/space joining, optional plural."""
    tokens = [re.escape(t) for t in re.split(r"[-\s]+", phrase.strip()) if t]
    return r"(?<!\w)" + r"[-\s]?".join(tokens) + r"(?:s|es)?(?!\w)"


def _trie_regex(phrases: list[str]) -> str:
    """One regex matching any of the phrases, with shared prefixes merged.

    A flat alternation of ~2,000 phrases makes Python's regex engine try every
    alternative at every position; the merged trie form is an order of
    magnitude faster and is what makes the per-block pre-filter affordable.
    Phrases are matched on text where hyphens are replaced by spaces.
    """
    trie: dict = {}
    for phrase in phrases:
        node = trie
        for ch in re.sub(r"[-\s]+", " ", phrase.strip()):
            node = node.setdefault(ch, {})
        node[""] = {}

    def build(node: dict) -> str:
        if "" in node and len(node) == 1:
            return ""
        parts, optional = [], False
        for ch, child in sorted(node.items()):
            if ch == "":
                optional = True
            else:
                parts.append(re.escape(ch) + build(child))
        # A lone branch still needs the group when the node is optional, or
        # the "?" would bind to its last character only.
        body = parts[0] if len(parts) == 1 and not optional else "(?:" + "|".join(parts) + ")"
        return body + "?" if optional else body

    return r"(?<!\w)" + build(trie) + r"(?:s|es)?(?!\w)"


class Matcher:
    """Finds glossary terms in text. Built once per industry, reused for every block."""

    def __init__(self, glossaries: list[tuple[str, list[dict]]]):
        self.sources = [name for name, _ in glossaries]
        # Canonical term -> group: the core glossary's group, "industry" for an industry glossary's term.
        self.groups: dict[str, str] = {}
        self._terms: list[tuple[str, str, re.Pattern]] = []  # (canonical term, tier, regex)
        seen = set()
        exact_phrases, loose_phrases = [], []
        for _, terms in glossaries:
            for t in terms:
                self.groups.setdefault(t["term"], t.get("group") or "industry")
                exact = set(t.get("case_sensitive_variants", []))
                for phrase in [t["term"], *t.get("variants", [])]:
                    key = (phrase if phrase in exact else phrase.casefold(), phrase in exact)
                    if key in seen:
                        continue
                    seen.add(key)
                    (exact_phrases if phrase in exact else loose_phrases).append(phrase)
                    flags = 0 if phrase in exact else re.I
                    self._terms.append((t["term"], t["tier"], re.compile(_pattern(phrase), flags)))
        # Pre-filter: one trie regex per case mode rejects the (vast majority
        # of) blocks without any term; only hit blocks are searched per term.
        self._any = [
            re.compile(_trie_regex(p), flags)
            for p, flags in ((exact_phrases, 0), (loose_phrases, re.I))
            if p
        ]

    def __len__(self) -> int:
        return len(self._terms)

    def find(self, text: str) -> dict[str, list[str]]:
        """Return {tier: [canonical terms]} for the tiers that hit."""
        return {tier: sorted(terms) for tier, terms in self.find_detailed(text).items()}

    def find_detailed(self, text: str) -> dict[str, dict[str, list[str]]]:
        """Return {tier: {canonical term: [wordings found in the text]}}."""
        plain = text.replace("-", " ")
        if not any(rx.search(plain) for rx in self._any):
            return {}
        hits: dict[str, dict[str, list[str]]] = {}
        for term, tier, rx in self._terms:
            if m := rx.search(text):
                found = hits.setdefault(tier, {}).setdefault(term, [])
                if m.group(0) not in found:
                    found.append(m.group(0))
        return {tier: hits[tier] for tier in TIERS if tier in hits}


@lru_cache(maxsize=None)
def load(isic_class: str | None = None, root: Path = GLOSSARY_DIR) -> Matcher:
    """Matcher for a company's 4-digit ISIC class; core vocabulary only if unknown."""
    glossaries = [("core", json.loads((root / "core.json").read_text(encoding="utf-8"))["terms"])]
    if isic_class:
        division = root / "isic" / f"{isic_class[:2]}.json"
        if division.exists():
            g = json.loads(division.read_text(encoding="utf-8"))
            glossaries.append((f"isic:{g['id']}", g["terms"]))
            if isic_class in g.get("class_terms", {}):
                glossaries.append((f"isic:{isic_class}", g["class_terms"][isic_class]))
    return Matcher(glossaries)
