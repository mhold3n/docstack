#!/usr/bin/env python3
"""Deterministic statistical mass rebuild for the eight voice banks.

Agent note: mass JSON is fully rebuilt from references/active/. Archetype
markdown is never written here.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

import ngrams
import voice_core
from banks.specs import (
    BANK_IDS,
    PHRASE_MAX_N,
    PHRASE_MIN_COUNT,
    PHRASE_MIN_N,
    assert_bank_id,
)

# Clause / grammar cue tokens (lightweight heuristics, not a tagger).
_IMPERATIVE_CUES = frozenset(
    {"measure", "record", "calculate", "compute", "plot", "note", "observe", "use"}
)
_RELATIVE_CUES = frozenset({"which", "that", "who", "whose", "where", "when"})
_TRANSITION_CUES = frozenset(
    {
        "however",
        "therefore",
        "thus",
        "furthermore",
        "meanwhile",
        "finally",
        "next",
        "then",
        "additionally",
        "overall",
    }
)
_UNIT_RE = re.compile(
    r"\b(?:kg|g|mg|mL|ml|L|kPa|Pa|psi|°C|C|K|W|kW|N|m|cm|mm|s|Hz|rpm)\b"
)
_TABLE_FIG_RE = re.compile(
    r"\b(?:table|figure|fig\.|eq\.|equation)\s*\d+", re.IGNORECASE
)
_NUMBERED_HDR_RE = re.compile(r"(?m)^#{1,3}\s+\d+[\.\)]\s+")
_PUNCT_KEYS = (
    ("period", "."),
    ("comma", ","),
    ("semicolon", ";"),
    ("colon", ":"),
    ("em_dash", "—"),
    ("ellipsis", "..."),
    ("question", "?"),
    ("paren_open", "("),
    ("paren_close", ")"),
)


def banks_cache_root(voice_root: Path) -> Path:
    """Root for versioned mass JSON."""
    return voice_root / ".cache" / "banks"


def mass_dir(voice_root: Path, corpus_version: str) -> Path:
    """Directory for one corpus_version mass snapshot."""
    return banks_cache_root(voice_root) / corpus_version


def _empty_bank(bank_id: str, corpus_version: str, n_files: int) -> dict[str, Any]:
    return {
        "bank_id": bank_id,
        "corpus_version": corpus_version,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n_source_files": n_files,
        "counts": {},
        "rates": {},
        "top": [],
    }


def _top_serialized(counter: Counter[Any], k: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key, count in ngrams.top_counts(counter, k):
        out.append({"key": ngrams.join_ngram(key), "count": int(count)})
    return out


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _split_paragraphs(text: str) -> list[str]:
    parts = re.split(r"\n\s*\n", text)
    return [p.strip() for p in parts if p.strip()]


def _build_grammar(texts: list[str], corpus_version: str, top_k: int) -> dict[str, Any]:
    cue_counts: Counter[str] = Counter()
    n_sent = 0
    n_imp = 0
    n_decl = 0
    n_rel = 0
    for text in texts:
        for sent in _split_sentences(text):
            n_sent += 1
            toks = ngrams.tokens(sent)
            if not toks:
                continue
            if toks[0] in _IMPERATIVE_CUES:
                n_imp += 1
                cue_counts[toks[0]] += 1
            else:
                n_decl += 1
            for t in toks:
                if t in _RELATIVE_CUES:
                    n_rel += 1
                    cue_counts[t] += 1
    rates = {
        "imperative_ratio": round(n_imp / n_sent, 4) if n_sent else 0.0,
        "declarative_ratio": round(n_decl / n_sent, 4) if n_sent else 0.0,
        "relative_clause_rate": round(n_rel / n_sent, 4) if n_sent else 0.0,
    }
    payload = _empty_bank("grammar", corpus_version, len(texts))
    payload["counts"] = {k: int(v) for k, v in sorted(cue_counts.items())}
    payload["rates"] = rates
    payload["top"] = _top_serialized(cue_counts, top_k)
    return payload


def _build_word(texts: list[str], corpus_version: str, top_k: int) -> dict[str, Any]:
    uni: Counter[str] = Counter()
    for text in texts:
        uni.update(ngrams.count_unigrams(ngrams.tokens(text)))
    payload = _empty_bank("word", corpus_version, len(texts))
    # Store only top mass in counts to keep JSON bounded; full top list separate.
    top = _top_serialized(uni, max(top_k, 200))
    payload["counts"] = {row["key"]: row["count"] for row in top}
    payload["top"] = top[:top_k]
    return payload


def _build_word_combo(
    texts: list[str], corpus_version: str, top_k: int
) -> dict[str, Any]:
    bi: Counter[tuple[str, ...]] = Counter()
    tri: Counter[tuple[str, ...]] = Counter()
    for text in texts:
        toks = ngrams.tokens(text)
        bi.update(ngrams.count_ngrams(toks, 2))
        tri.update(ngrams.count_ngrams(toks, 3))
    merged: Counter[tuple[str, ...]] = Counter()
    merged.update(bi)
    merged.update(tri)
    payload = _empty_bank("word_combo", corpus_version, len(texts))
    top = _top_serialized(merged, max(top_k, 200))
    payload["counts"] = {row["key"]: row["count"] for row in top}
    payload["top"] = top[:top_k]
    return payload


def _build_phrase(texts: list[str], corpus_version: str, top_k: int) -> dict[str, Any]:
    phrases: Counter[tuple[str, ...]] = Counter()
    for text in texts:
        toks = ngrams.tokens(text)
        for n in range(PHRASE_MIN_N, PHRASE_MAX_N + 1):
            phrases.update(ngrams.count_ngrams(toks, n))
    filtered = Counter({g: c for g, c in phrases.items() if c >= PHRASE_MIN_COUNT})
    payload = _empty_bank("phrase", corpus_version, len(texts))
    top = _top_serialized(filtered, max(top_k, 200))
    payload["counts"] = {row["key"]: row["count"] for row in top}
    payload["top"] = top[:top_k]
    return payload


def _build_punctuation(
    texts: list[str], corpus_version: str, top_k: int
) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    total_chars = 0
    for text in texts:
        total_chars += len(text)
        for key, ch in _PUNCT_KEYS:
            if ch == "...":
                counts[key] += text.count("...")
            else:
                counts[key] += text.count(ch)
    rates: dict[str, float] = {}
    denom = max(total_chars, 1) / 1000.0
    for key, _ in _PUNCT_KEYS:
        rates[key] = round(counts[key] / denom, 4)
    payload = _empty_bank("punctuation", corpus_version, len(texts))
    payload["counts"] = {k: int(counts[k]) for k, _ in _PUNCT_KEYS}
    payload["rates"] = rates
    payload["top"] = [
        {"key": k, "count": int(counts[k])}
        for k, _ in sorted(_PUNCT_KEYS, key=lambda kv: (-counts[kv[0]], kv[0]))[:top_k]
    ]
    return payload


def _build_phrasing(
    texts: list[str], corpus_version: str, top_k: int
) -> dict[str, Any]:
    openers: Counter[tuple[str, ...]] = Counter()
    transitions: Counter[str] = Counter()
    for text in texts:
        for sent in _split_sentences(text):
            toks = ngrams.tokens(sent)
            if toks:
                openers[tuple(toks[:2])] += 1 if len(toks) >= 2 else 0
                if toks:
                    openers[(toks[0],)] += 1
            for t in toks:
                if t in _TRANSITION_CUES:
                    transitions[t] += 1
    merged: Counter[Any] = Counter()
    for g, c in openers.items():
        if c:
            merged[g] += c
    for t, c in transitions.items():
        merged[(t,)] += c
    payload = _empty_bank("phrasing", corpus_version, len(texts))
    top = _top_serialized(merged, max(top_k, 100))
    payload["counts"] = {row["key"]: row["count"] for row in top}
    payload["top"] = top[:top_k]
    return payload


def _build_paragraph(
    texts: list[str], corpus_version: str, top_k: int
) -> dict[str, Any]:
    buckets: Counter[str] = Counter()
    first_uni: Counter[str] = Counter()
    lengths: list[int] = []
    for text in texts:
        for para in _split_paragraphs(text):
            toks = ngrams.tokens(para)
            n = len(toks)
            lengths.append(n)
            if n <= 20:
                buckets["0-20"] += 1
            elif n <= 40:
                buckets["21-40"] += 1
            elif n <= 80:
                buckets["41-80"] += 1
            else:
                buckets["81+"] += 1
            sents = _split_sentences(para)
            if sents:
                first_uni.update(ngrams.tokens(sents[0])[:8])
    mean_len = round(sum(lengths) / len(lengths), 2) if lengths else 0.0
    payload = _empty_bank("paragraph", corpus_version, len(texts))
    payload["counts"] = {
        **{f"bucket:{k}": int(v) for k, v in sorted(buckets.items())},
        **{f"first:{k}": int(v) for k, v in ngrams.top_counts(first_uni, 100)},
    }
    payload["rates"] = {"mean_paragraph_words": mean_len}
    payload["top"] = _top_serialized(first_uni, top_k)
    return payload


def _build_technical(
    texts: list[str], corpus_version: str, top_k: int
) -> dict[str, Any]:
    cues: Counter[str] = Counter()
    unit_hits = 0
    n_toks = 0
    for text in texts:
        toks = ngrams.tokens(text)
        n_toks += len(toks)
        for m in _UNIT_RE.finditer(text):
            unit_hits += 1
            cues[m.group(0)] += 1
        for m in _TABLE_FIG_RE.finditer(text):
            cues[m.group(0).lower()] += 1
        for m in _NUMBERED_HDR_RE.finditer(text):
            cues["numbered_header"] += 1
    payload = _empty_bank("technical_writing", corpus_version, len(texts))
    payload["counts"] = {k: int(v) for k, v in sorted(cues.items())}
    payload["rates"] = {"unit_density": round(unit_hits / n_toks, 4) if n_toks else 0.0}
    payload["top"] = _top_serialized(cues, top_k)
    return payload


_BUILDERS = {
    "grammar": _build_grammar,
    "word": _build_word,
    "word_combo": _build_word_combo,
    "phrase": _build_phrase,
    "punctuation": _build_punctuation,
    "phrasing": _build_phrasing,
    "paragraph": _build_paragraph,
    "technical_writing": _build_technical,
}


def load_active_texts(voice_root: Path) -> dict[str, str]:
    """Map basename -> body for active prose files."""
    active = voice_core.active_dir(voice_root)
    out: dict[str, str] = {}
    if not active.is_dir():
        return out
    for path in sorted(active.iterdir()):
        if not path.is_file():
            continue
        if path.name.startswith(".") or path.name.startswith("._"):
            continue
        if path.suffix.lower() not in voice_core.PROSE_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        out[path.name] = text.replace("\x00", "")
    return out


def rebuild_mass(
    voice_root: Path | None = None,
    *,
    corpus_version: str | None = None,
    top_k: int = 12,
) -> dict[str, Any]:
    """Rebuild all eight bank JSON files. Returns manifest dict."""
    root = voice_root or voice_core.VOICE_ROOT
    cfg = voice_core.load_config(root)
    version = corpus_version or voice_core.hash_corpus_version(root, cfg)
    texts_map = load_active_texts(root)
    texts = list(texts_map.values())
    out_dir = mass_dir(root, version)
    out_dir.mkdir(parents=True, exist_ok=True)
    banks_meta: dict[str, str] = {}
    for bank_id in BANK_IDS:
        builder = _BUILDERS[bank_id]
        payload = builder(texts, version, top_k)
        path = out_dir / f"{bank_id}.json"
        voice_core.atomic_write_json(path, payload)
        banks_meta[bank_id] = str(path)
    manifest = {
        "corpus_version": version,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n_source_files": len(texts_map),
        "source_files": sorted(texts_map.keys()),
        "banks": banks_meta,
        "top_k": top_k,
        "empty": len(texts_map) == 0,
    }
    voice_core.atomic_write_json(out_dir / "manifest.json", manifest)
    # Pointer for warm loads.
    voice_core.atomic_write_json(
        banks_cache_root(root) / "latest.json",
        {"corpus_version": version, "path": str(out_dir)},
    )
    return manifest


def load_mass(
    voice_root: Path | None = None,
    *,
    corpus_version: str | None = None,
    bank_id: str | None = None,
) -> dict[str, Any] | None:
    """Load mass manifest or one bank JSON. None if missing."""
    root = voice_root or voice_core.VOICE_ROOT
    cfg = voice_core.load_config(root)
    version = corpus_version or voice_core.hash_corpus_version(root, cfg)
    out_dir = mass_dir(root, version)
    if bank_id is None:
        path = out_dir / "manifest.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    assert_bank_id(bank_id)
    path = out_dir / f"{bank_id}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_mass(
    voice_root: Path | None = None,
    *,
    top_k: int = 12,
) -> dict[str, Any]:
    """Rebuild mass when missing or corpus_version stale."""
    root = voice_root or voice_core.VOICE_ROOT
    cfg = voice_core.load_config(root)
    version = voice_core.hash_corpus_version(root, cfg)
    existing = load_mass(root, corpus_version=version)
    if existing and existing.get("corpus_version") == version:
        return existing
    return rebuild_mass(root, corpus_version=version, top_k=top_k)
