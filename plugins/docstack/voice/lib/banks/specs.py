#!/usr/bin/env python3
"""Frozen bank ids and mass/archetype contracts for multi-doc voice banks.

Agent note: bank_id strings are the public API. Do not rename without a
corpus_version bump and archetype frontmatter migration.
"""

from __future__ import annotations

from typing import Final

# Exact ids from the multi-doc voice banks plan.
BANK_IDS: Final[tuple[str, ...]] = (
    "grammar",
    "word",
    "word_combo",
    "phrase",
    "punctuation",
    "phrasing",
    "paragraph",
    "technical_writing",
)

# Human-readable selection rules for harvest agents (archetype append).
ARCHETYPE_RULES: Final[dict[str, str]] = {
    "grammar": (
        "Cite 3–8 sentence pairs that show preferred clause shape "
        "(imperative vs declarative, relative-clause use)."
    ),
    "word": (
        "High-frequency content words that are Max-typical; denylist AI-tell tokens."
    ),
    "word_combo": "Top collocations with source citations.",
    "phrase": "Formula phrases for labs/essays (3–8 token spans).",
    "punctuation": (
        "Short excerpts where punctuation policy is visible "
        "(period, comma, semicolon, colon, dash, ellipsis, question, paren)."
    ),
    "phrasing": "Opening/transition lines.",
    "paragraph": "Full short paragraphs that match bank rhythm.",
    "technical_writing": (
        "Lab/report fragments with measurements and named systems "
        "(units, tables, figures, equation-adjacent lines, numbered headers)."
    ),
}

# Mass builder contracts: what counts/rates/top mean per bank.
MASS_CONTRACTS: Final[dict[str, str]] = {
    "grammar": (
        "counts: clause-cue token freqs; rates: imperative_ratio, "
        "declarative_ratio, relative_clause_rate; top: cue tokens."
    ),
    "word": "counts: unigram freqs; rates: {}; top: unigrams.",
    "word_combo": "counts: bigram+trigram freqs; rates: {}; top: collocations.",
    "phrase": "counts: 3–8 gram freqs above floor; rates: {}; top: phrases.",
    "punctuation": (
        "counts: punct char freqs; rates: per-1k-chars rates; top: punct keys."
    ),
    "phrasing": (
        "counts: opener unigram/bigram and transition marker freqs; "
        "rates: {}; top: openers/transitions."
    ),
    "paragraph": (
        "counts: paragraph length bucket freqs + first-sentence unigrams; "
        "rates: mean_paragraph_words; top: first-sentence templates."
    ),
    "technical_writing": (
        "counts: unit tokens, table/figure cues, numbered-header cues; "
        "rates: unit_density; top: technical cues."
    ),
}

PHRASE_MIN_N = 3
PHRASE_MAX_N = 8
PHRASE_MIN_COUNT = 2


def assert_bank_id(bank_id: str) -> str:
    """Raise ValueError if bank_id is not in BANK_IDS."""
    if bank_id not in BANK_IDS:
        raise ValueError(f"unknown bank_id: {bank_id}")
    return bank_id
