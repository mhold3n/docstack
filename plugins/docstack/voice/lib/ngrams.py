#!/usr/bin/env python3
"""Shared tokenization and n-gram helpers for blacklist and voice banks.

Agent note: keep TOKEN_RE identical to the historical blacklist pattern so
ingest overlap scores do not drift when helpers move here.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from typing import Any

# Bank-match tokens: lowercase alnum runs of length >= 3 (stopwords kept).
TOKEN_RE = re.compile(r"[a-z0-9]{3,}")


def tokens(text: str) -> list[str]:
    """Tokenize prose for bank-match and mass counts."""
    return TOKEN_RE.findall(text.lower())


def unigram_set(toks: Iterable[str]) -> frozenset[str]:
    """Unique unigrams from a token sequence."""
    return frozenset(toks)


def bigrams(toks: list[str]) -> list[tuple[str, str]]:
    """Ordered bigrams from tokens."""
    if len(toks) < 2:
        return []
    return list(zip(toks, toks[1:], strict=False))


def bigram_set(toks: list[str]) -> frozenset[tuple[str, str]]:
    """Unique bigrams from tokens."""
    return frozenset(bigrams(toks))


def ngrams(toks: list[str], n: int) -> list[tuple[str, ...]]:
    """Ordered n-grams of width n."""
    if n < 1 or len(toks) < n:
        return []
    return [tuple(toks[i : i + n]) for i in range(len(toks) - n + 1)]


def count_ngrams(toks: list[str], n: int) -> Counter[tuple[str, ...]]:
    """Frequency table of n-grams."""
    return Counter(ngrams(toks, n))


def count_unigrams(toks: list[str]) -> Counter[str]:
    """Frequency table of unigrams."""
    return Counter(toks)


def top_counts(counter: Counter[Any], k: int) -> list[tuple[Any, int]]:
    """Deterministic top-k: count desc, then string key asc for ties."""
    items = list(counter.items())
    items.sort(key=lambda kv: (-kv[1], str(kv[0])))
    return items[: max(0, k)]


def join_ngram(gram: tuple[str, ...] | str) -> str:
    """Render an n-gram key for JSON / conditioning text."""
    if isinstance(gram, str):
        return gram
    return " ".join(gram)
