#!/usr/bin/env python3
"""Dump blacklist: institutional markers first, voice mismatch only after.

Agent note: one public build, one public load, three public renders.
Does not convert, promote, park, or edit authorship.rules. Hard-marker
rows may carry an optional audit voice score that does not change inclusion
or rank. Voice-mismatch rows never carry markers. Picklist not_max text is
a note when latest.json exists. It is not a gate.
"""

from __future__ import annotations

import enum
import hashlib
import json
import os
import re
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import marker_runtime
import ngrams
import voice_core

__all__ = [
    "build_blacklist",
    "load_blacklist",
    "render_blacklist",
    "render_blacklist_paths",
    "render_blacklist_json",
    "Blacklist",
    "ExcludeRow",
    "ExcludeCause",
    "MarkerKind",
    "MarkerHit",
    "VoiceScore",
]

# Bump when the marker table or _KEEP_OVERLAP changes. Load does not rescore.
_GATE_VERSION = "1"
# Pages 1–2, then this many characters. Marker cache uses the same cap.
_PEEK_CHARS = 8000
# Below this, density is a coin flip on a cover sheet, so the file stays unscored.
_MIN_TOKS = 40
# Bank-match gap: lowest full was 0.2333, highest skip was 0.2147.
# Applied to the solo-blended overlap. At or above this, the file is kept.
_KEEP_OVERLAP = 0.22
_UNI_WEIGHT = 0.45
_BI_WEIGHT = 0.55
_SOLO_BLEND = 0.5
_EXCERPT_CHARS = 80
# Agent note: TOKEN_RE lives in ngrams; alias kept for any local readers.
_TOKEN_RE = ngrams.TOKEN_RE


class ExcludeCause(enum.StrEnum):
    """Why this path is on the exclude list. Closed set.

    HARD_MARKER: the gate fired. Voice was not computed.
    VOICE_MISMATCH: no hard marker, peek had enough tokens, blended overlap
    is below the keep cut.
    """

    HARD_MARKER = "hard_marker"
    VOICE_MISMATCH = "voice_mismatch"


class MarkerKind(enum.StrEnum):
    """Identity of a hit. The regex that produces it stays private."""

    ISBN = "isbn"
    DOI = "doi"
    NASA_STD = "nasa_std"
    NASA_TP = "nasa_tp"
    NASA_TM = "nasa_tm"
    MIL_STD = "mil_std"
    AISI = "aisi"
    ASME_RULES = "asme_rules"
    IMPRINT = "imprint"
    RIGHTS = "rights"
    SYLLABUS = "syllabus"


@dataclass(frozen=True)
class MarkerHit:
    """One match in the peek. excerpt is the matched span, capped."""

    kind: MarkerKind
    excerpt: str


@dataclass(frozen=True)
class VoiceScore:
    """Inverse of bank-match file_score, solo-blended. mismatch is not stored.

    uni_density and bi_density are pool overlap. solo_* are the solo bank.
    When the comparison has no solo files, solo densities are 0 and overlap
    uses the pool densities alone.
    """

    overlap: float
    n_toks: int
    uni_density: float
    bi_density: float
    solo_uni_density: float
    solo_bi_density: float

    @property
    def mismatch(self) -> float:
        """1 - overlap. Derived so the two cannot drift."""
        return 1.0 - self.overlap


@dataclass(frozen=True)
class ExcludeRow:
    """One ranked exclude. rank is 1-based, assigned only by _rank.

    note is picklist not_max text for this path, or empty. It does not
    decide cause.
    """

    path: Path
    rank: int
    cause: ExcludeCause
    reason: str
    markers: tuple[MarkerHit, ...]
    voice: VoiceScore | None
    prior_tier: str
    prior_rule: str
    extract_kind: str
    note: str = ""

    def __post_init__(self) -> None:
        """HARD_MARKER <=> markers nonempty (voice optional audit).
        VOICE_MISMATCH <=> voice is not None and markers is empty.
        """
        if self.rank < 1:
            raise ValueError("rank is 1-based")
        if self.cause is ExcludeCause.HARD_MARKER:
            if not self.markers:
                raise ValueError("hard-marker row requires markers")
            return
        if self.cause is ExcludeCause.VOICE_MISMATCH:
            if self.markers or self.voice is None:
                raise ValueError("voice-mismatch row has a score and no markers")
            return
        raise ValueError(f"unknown exclude cause: {self.cause}")


@dataclass(frozen=True)
class Blacklist:
    """Ranked excludes plus run counts. rows is the only exclude sequence.

    Order: hard-marker rows by (-distinct kinds, path), then voice-mismatch
    rows by (-mismatch, path). scanned == len(rows) + kept + unscored.
    bank_digest fingerprints the bank used for voice scoring.
    """

    rows: tuple[ExcludeRow, ...]
    scanned: int
    kept: int
    unscored: int
    bank_files: int
    solo_files: int
    bank_digest: str = ""

    def excluded_paths(self) -> tuple[Path, ...]:
        return tuple(row.path for row in self.rows)


@dataclass(frozen=True)
class _MarkerRule:
    """One catalog row. hard kinds fire alone. Cluster kinds need two."""

    kind: MarkerKind
    pattern: re.Pattern[str]
    hard: bool
    stub: str


def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


# Kind and regex live in this tuple only. A new MarkerKind fails import
# until a row is added here.
_MARKER_RULES: tuple[_MarkerRule, ...] = (
    _MarkerRule(
        MarkerKind.ISBN,
        _compile(
            r"\bISBN(?:-1[03])?[:\s]+"
            r"(?:97[89](?:[- ]?\d){10}|(?:\d[- ]?){9}[\dXx])\b"
        ),
        True,
        "ISBN",
    ),
    _MarkerRule(
        MarkerKind.DOI,
        _compile(
            r"(?:\bdoi[:\s]+|https?://(?:dx\.)?doi\.org/)"
            r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+"
        ),
        True,
        "doi.org",
    ),
    _MarkerRule(
        MarkerKind.NASA_STD,
        _compile(r"\bNASA[-\s]?STD[-\s]?\d+"),
        True,
        "NASA-STD",
    ),
    _MarkerRule(
        MarkerKind.NASA_TP,
        _compile(r"\bNASA(?:\s*/\s*|-)TP(?:-\d+|\b)"),
        True,
        "NASA/TP",
    ),
    _MarkerRule(
        MarkerKind.NASA_TM,
        _compile(r"\bNASA(?:\s*/\s*|-)TM(?:-\d+|\b)"),
        True,
        "NASA/TM",
    ),
    _MarkerRule(
        MarkerKind.MIL_STD,
        _compile(r"\bMIL[-\s]STD[-\s]?\d+"),
        True,
        "MIL-STD",
    ),
    _MarkerRule(
        MarkerKind.AISI,
        _compile(r"\bAISI-\d{2,4}\b"),
        True,
        "AISI-",
    ),
    _MarkerRule(
        MarkerKind.ASME_RULES,
        _compile(
            r"\bASME\b[\s\S]{0,80}?\b(?:rules|standards?|specifications?)\b"
            r"|\b(?:rules|standards?|specifications?)\b[\s\S]{0,40}?\bASME\b"
        ),
        True,
        "ASME",
    ),
    _MarkerRule(
        MarkerKind.IMPRINT,
        _compile(
            r"\b(?:"
            r"university press"
            r"|mcgraw[-\s]hill"
            r"|john wiley|wiley(?:\s*&\s*sons|-vch)"
            r"|springer(?:[-\s]verlag|\s+nature)?"
            r"|pearson education|prentice hall"
            r"|cengage learning"
            r"|elsevier"
            r")\b"
        ),
        True,
        "University Press",
    ),
    _MarkerRule(
        MarkerKind.RIGHTS,
        _compile(r"\ball rights reserved\b|copyright\s*©|©\s*(?:19|20)\d{2}\b"),
        False,
        "All rights reserved",
    ),
    _MarkerRule(
        MarkerKind.SYLLABUS,
        _compile(
            r"\b(?:syllabus|learning outcomes?|course objectives?"
            r"|office hours|grading policy)\b"
        ),
        False,
        "syllabus",
    ),
)

_HARD_KINDS = frozenset(rule.kind for rule in _MARKER_RULES if rule.hard)
_CLUSTER_KINDS = frozenset(rule.kind for rule in _MARKER_RULES if not rule.hard)
_STUBS = {rule.kind: rule.stub for rule in _MARKER_RULES}


def _assert_catalog() -> None:
    seen = [rule.kind for rule in _MARKER_RULES]
    if len(seen) != len(set(seen)):
        raise RuntimeError("marker kind repeated in catalog")
    missing = set(MarkerKind) - set(seen)
    if missing:
        names = ", ".join(sorted(kind.value for kind in missing))
        raise RuntimeError(f"marker catalog missing {names}")


_assert_catalog()


@dataclass(frozen=True)
class _Peek:
    kind: str
    text: str


@dataclass(frozen=True)
class _FileGrams:
    path: Path
    solo: bool
    uni: frozenset[str]
    bi: frozenset[tuple[str, str]]


@dataclass(frozen=True)
class _Draft:
    """Unranked exclude. _rank is the only place that builds ExcludeRow."""

    path: Path
    cause: ExcludeCause
    reason: str
    markers: tuple[MarkerHit, ...]
    voice: VoiceScore | None
    prior_tier: str
    prior_rule: str
    extract_kind: str
    note: str


class _VoiceBank:
    """Pool grams from candidates and active. Solo is a derived subset."""

    def __init__(self, files: tuple[_FileGrams, ...]) -> None:
        self.files = files

    @property
    def bank_files(self) -> int:
        return len(self.files)

    @property
    def solo_files(self) -> int:
        return sum(1 for item in self.files if item.solo)

    @property
    def digest(self) -> str:
        """Stable fingerprint of bank membership for audit, not ranking."""
        parts = [
            f"{item.path.resolve()}|{'1' if item.solo else '0'}"
            for item in sorted(self.files, key=lambda f: str(f.path).lower())
        ]
        return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]

    @classmethod
    def from_root(cls, voice_root: Path, solo_candidates: set[Path]) -> _VoiceBank:
        files: list[_FileGrams] = []
        seen: set[Path] = set()
        # Active is solo because promote already certified it. Candidates
        # are solo only when solo_candidates says so. Mixed stays pool.
        sources = (
            (voice_core.candidates_dir(voice_root), False),
            (voice_core.active_dir(voice_root), True),
        )
        for directory, force_solo in sources:
            if not directory.is_dir():
                continue
            for path in sorted(directory.iterdir()):
                if not _prose_file(path):
                    continue
                resolved = path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                toks = _tokens(_read_prose(resolved))
                if not toks:
                    continue
                solo = force_solo or resolved in solo_candidates
                files.append(
                    _FileGrams(
                        path=resolved,
                        solo=solo,
                        uni=ngrams.unigram_set(toks),
                        bi=ngrams.bigram_set(toks),
                    )
                )
        return cls(tuple(files))


def _prose_file(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.name.startswith(".") or path.name.startswith("._"):
        return False
    return path.suffix.lower() in voice_core.PROSE_SUFFIXES


def _read_prose(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text.replace("\x00", "")


def _tokens(text: str) -> list[str]:
    """Bank-match tokens. Stopwords stay in the density."""
    return ngrams.tokens(text)


def _is_under(path: Path, parent: Path) -> bool:
    if not parent.exists():
        return False
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def _resolve_key(raw: str) -> str:
    try:
        return str(Path(raw).resolve())
    except OSError:
        return raw


def _latest_rows(voice_root: Path) -> list[dict[str, Any]]:
    """Picklist rows when latest.json exists. Missing or broken yields [].

    Agent note: a stale picklist must not block the marker gate. Notes and
    solo membership simply stay empty.
    """
    path = voice_root / ".cache" / "picklist" / "latest.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = data.get("rows") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _not_max_notes(rows: list[dict[str, Any]]) -> dict[str, str]:
    notes: dict[str, str] = {}
    for row in rows:
        if str(row.get("kind") or "") != "not_max":
            continue
        raw = str(row.get("path") or "")
        reason = str(row.get("reason") or "").strip()
        if raw and reason:
            notes[_resolve_key(raw)] = reason
    return notes


def _solo_candidate_paths(voice_root: Path, rows: list[dict[str, Any]]) -> set[Path]:
    """Candidates materialized from an unshared rescue or confirm row.

    No picklist file means this set is empty. Only active prose is solo then.
    """
    unshared: set[str] = set()
    for row in rows:
        if str(row.get("kind") or "") != "batch":
            continue
        urgency = str(row.get("urgency") or "").lower()
        if urgency not in ("rescue", "confirm"):
            continue
        raw = str(row.get("path") or "")
        if raw:
            unshared.add(_resolve_key(raw))
    if not unshared:
        return set()
    found: set[Path] = set()
    extracted = marker_runtime.extracted_dir(voice_root)
    for record_path in extracted.glob("*.json"):
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if record.get("status") != "ok":
            continue
        source = str(record.get("source_path") or "")
        dest = str(record.get("materialized_path") or "")
        if not source or not dest:
            continue
        if _resolve_key(source) not in unshared:
            continue
        try:
            dest_path = Path(dest).resolve()
        except OSError:
            continue
        if dest_path.is_file():
            found.add(dest_path)
    return found


def _targets(roots: list[Path], voice_root: Path, cfg: dict[str, Any]) -> list[Path]:
    """Non-skip PDF/DOCX under roots, plus every candidates/*.md.

    active/ and library/ are never targets, even when a root points there.
    """
    found: list[Path] = []
    seen: set[str] = set()
    for row in voice_core.triage_paths(roots, cfg):
        if row.get("suggested_tier") == "skip":
            continue
        if str(row.get("ext") or "").lower() not in marker_runtime.CONVERT_SUFFIXES:
            continue
        path = Path(str(row["path"]))
        if not path.is_file():
            continue
        if _is_under(path, voice_core.active_dir(voice_root)):
            continue
        if _is_under(path, voice_core.library_dir(voice_root)):
            continue
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        found.append(path.resolve())
    candidates = voice_core.candidates_dir(voice_root)
    if candidates.is_dir():
        for path in sorted(candidates.glob("*.md")):
            if not _prose_file(path):
                continue
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            found.append(path.resolve())
    return found


def _peek(path: Path, voice_root: Path) -> _Peek:
    """Cheap text. Never calls convert.

    Order matches picklist: Marker cache, pdftotext pages 1–2, DOCX XML,
    then extract_text for markdown already on disk.
    """
    excerpt = marker_runtime.cached_excerpt(voice_root, path, _PEEK_CHARS)
    if excerpt:
        return _Peek("marker_cache", excerpt[:_PEEK_CHARS])
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        text = _pdftotext_head(path)
        if text:
            return _Peek("pdftotext", text[:_PEEK_CHARS])
    elif suffix == ".docx":
        text = _docx_xml_head(path)
        if text:
            return _Peek("docx_xml", text[:_PEEK_CHARS])
    elif suffix in voice_core.PROSE_SUFFIXES:
        try:
            text = voice_core.extract_text(path, _PEEK_CHARS)
        except (OSError, RuntimeError):
            text = ""
        if text.strip():
            return _Peek("markdown", text[:_PEEK_CHARS])
    return _Peek("none", "")


def _pdftotext_head(path: Path) -> str:
    """Pages 1–2 via pdftotext. Empty on a missing binary or a failed run.

    Agent note: copied from picklist. Importing that helper would publish
    picklist's private peek as a second way into this gate.
    """
    binary = os.environ.get("PDFTOTEXT_BIN") or "pdftotext"
    try:
        proc = subprocess.run(
            [binary, "-f", "1", "-l", "2", "-layout", "-enc", "UTF-8", str(path), "-"],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").replace("\x00", "").strip()


def _docx_xml_head(path: Path) -> str:
    """Plain text from word/document.xml. Empty on failure.

    Agent note: copied from picklist for the same reason as _pdftotext_head.
    """
    try:
        with zipfile.ZipFile(path) as archive:
            raw = archive.read("word/document.xml")
    except (OSError, KeyError, zipfile.BadZipFile):
        return ""
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError:
        return ""
    texts: list[str] = []
    for el in root.iter():
        if el.tag.endswith("}t") and el.text:
            texts.append(el.text)
        if el.tag.endswith("}tab"):
            texts.append("\t")
        if el.tag.endswith("}br") or el.tag.endswith("}cr"):
            texts.append("\n")
    return re.sub(r"[ \t]+\n", "\n", "".join(texts)).strip()


def _excerpt(match: re.Match[str]) -> str:
    text = re.sub(r"\s+", " ", match.group(0)).strip()
    return text[:_EXCERPT_CHARS]


def _marker_hits(text: str) -> tuple[MarkerHit, ...]:
    """First match of each kind. Later duplicates do not change the gate."""
    if not text:
        return ()
    hits: list[MarkerHit] = []
    for rule in _MARKER_RULES:
        match = rule.pattern.search(text)
        if match is None:
            continue
        hits.append(MarkerHit(kind=rule.kind, excerpt=_excerpt(match)))
    return tuple(hits)


def _is_hard(hits: tuple[MarkerHit, ...]) -> bool:
    """One hard kind fires. Cluster kinds fire only as a pair of kinds.

    Agent note: a lone "All rights reserved" stays on the voice path.
    Two syllabus phrases are still one kind and do not fire.
    """
    kinds = {hit.kind for hit in hits}
    if kinds & _HARD_KINDS:
        return True
    return len(kinds & _CLUSTER_KINDS) >= 2


def _hard_reason(hits: tuple[MarkerHit, ...]) -> str:
    kinds = ", ".join(hit.kind.value for hit in hits)
    return f"Hard marker {kinds} ({hits[0].excerpt})."


def _union(
    files: list[_FileGrams],
) -> tuple[set[str], set[tuple[str, str]]]:
    uni: set[str] = set()
    bi: set[tuple[str, str]] = set()
    for item in files:
        uni.update(item.uni)
        bi.update(item.bi)
    return uni, bi


def _density(
    tokens: list[str],
    uni: set[str],
    bi: set[tuple[str, str]],
) -> tuple[float, float]:
    count = len(tokens)
    uni_density = sum(1 for token in tokens if token in uni) / count
    pairs = count - 1
    if pairs <= 0:
        return uni_density, 0.0
    bi_hits = sum(
        1
        for left, right in zip(tokens, tokens[1:], strict=False)
        if (left, right) in bi
    )
    return uni_density, bi_hits / pairs


def _score(text: str, bank: _VoiceBank, path: Path) -> VoiceScore | None:
    """Blended overlap for a survivor. None when the comparison bank is empty.

    Agent note: the file's own grams are left out. A candidate scored against
    a bank that contains itself clears the keep cut, so a pre-promote exclude
    would never fire.
    """
    tokens = _tokens(text)
    if len(tokens) < _MIN_TOKS or bank.bank_files == 0:
        return None
    pool = [item for item in bank.files if item.path != path]
    if not pool:
        return None
    solo = [item for item in pool if item.solo]
    pool_uni, pool_bi = _union(pool)
    uni_density, bi_density = _density(tokens, pool_uni, pool_bi)
    if solo:
        solo_uni_set, solo_bi_set = _union(solo)
        solo_uni, solo_bi = _density(tokens, solo_uni_set, solo_bi_set)
        blended_uni = _SOLO_BLEND * uni_density + _SOLO_BLEND * solo_uni
        blended_bi = _SOLO_BLEND * bi_density + _SOLO_BLEND * solo_bi
    else:
        solo_uni = 0.0
        solo_bi = 0.0
        blended_uni = uni_density
        blended_bi = bi_density
    overlap = round(_UNI_WEIGHT * blended_uni + _BI_WEIGHT * blended_bi, 4)
    return VoiceScore(
        overlap=overlap,
        n_toks=len(tokens),
        uni_density=round(uni_density, 4),
        bi_density=round(bi_density, 4),
        solo_uni_density=round(solo_uni, 4),
        solo_bi_density=round(solo_bi, 4),
    )


def _rank(drafts: list[_Draft]) -> tuple[ExcludeRow, ...]:
    def _key(draft: _Draft) -> tuple[int, float, str]:
        path_key = str(draft.path).lower()
        if draft.cause is ExcludeCause.HARD_MARKER:
            distinct = -float(len({hit.kind for hit in draft.markers}))
            return (0, distinct, path_key)
        if draft.cause is ExcludeCause.VOICE_MISMATCH:
            assert draft.voice is not None
            return (1, -draft.voice.mismatch, path_key)
        raise ValueError(f"unknown exclude cause: {draft.cause}")

    ordered = sorted(drafts, key=_key)
    rows: list[ExcludeRow] = []
    for index, draft in enumerate(ordered, start=1):
        rows.append(
            ExcludeRow(
                path=draft.path,
                rank=index,
                cause=draft.cause,
                reason=draft.reason,
                markers=draft.markers,
                voice=draft.voice,
                prior_tier=draft.prior_tier,
                prior_rule=draft.prior_rule,
                extract_kind=draft.extract_kind,
                note=draft.note,
            )
        )
    return tuple(rows)


def _check_counts(blacklist: Blacklist) -> None:
    expected = len(blacklist.rows) + blacklist.kept + blacklist.unscored
    if blacklist.scanned != expected:
        raise ValueError(
            f"scanned {blacklist.scanned} != rows+kept+unscored {expected}"
        )


def _blacklist_path(voice_root: Path) -> Path:
    return voice_root / ".cache" / "picklist" / "blacklist.json"


def _lock_path(voice_root: Path) -> Path:
    return voice_root / ".cache" / "picklist" / "blacklist.lock"


def _marker_to_dict(hit: MarkerHit) -> dict[str, str]:
    return {"kind": hit.kind.value, "excerpt": hit.excerpt}


def _voice_to_dict(voice: VoiceScore | None) -> dict[str, Any] | None:
    if voice is None:
        return None
    return {
        "overlap": voice.overlap,
        "n_toks": voice.n_toks,
        "uni_density": voice.uni_density,
        "bi_density": voice.bi_density,
        "solo_uni_density": voice.solo_uni_density,
        "solo_bi_density": voice.solo_bi_density,
    }


def _row_to_dict(row: ExcludeRow) -> dict[str, Any]:
    return {
        "path": str(row.path),
        "rank": row.rank,
        "cause": row.cause.value,
        "reason": row.reason,
        "markers": [_marker_to_dict(hit) for hit in row.markers],
        "voice": _voice_to_dict(row.voice),
        "prior_tier": row.prior_tier,
        "prior_rule": row.prior_rule,
        "extract_kind": row.extract_kind,
        "note": row.note,
    }


def _to_payload(blacklist: Blacklist) -> dict[str, Any]:
    return {
        "gate_version": _GATE_VERSION,
        "scanned": blacklist.scanned,
        "kept": blacklist.kept,
        "unscored": blacklist.unscored,
        "bank_files": blacklist.bank_files,
        "solo_files": blacklist.solo_files,
        "bank_digest": blacklist.bank_digest,
        "rows": [_row_to_dict(row) for row in blacklist.rows],
    }


def _voice_from_dict(data: Any) -> VoiceScore | None:
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ValueError("voice must be an object or null")
    overlap = float(data["overlap"])
    if overlap < 0.0 or overlap > 1.0:
        raise ValueError("overlap is outside 0..1")
    return VoiceScore(
        overlap=overlap,
        n_toks=int(data["n_toks"]),
        uni_density=float(data["uni_density"]),
        bi_density=float(data["bi_density"]),
        solo_uni_density=float(data["solo_uni_density"]),
        solo_bi_density=float(data["solo_bi_density"]),
    )


def _row_from_dict(data: dict[str, Any]) -> ExcludeRow:
    markers: list[MarkerHit] = []
    raw_markers = data.get("markers") or []
    if not isinstance(raw_markers, list):
        raise ValueError("markers must be a list")
    for item in raw_markers:
        if not isinstance(item, dict):
            raise ValueError("marker must be an object")
        markers.append(
            MarkerHit(
                kind=MarkerKind(str(item["kind"])),
                excerpt=str(item.get("excerpt") or ""),
            )
        )
    return ExcludeRow(
        path=Path(str(data["path"])),
        rank=int(data["rank"]),
        cause=ExcludeCause(str(data["cause"])),
        reason=str(data.get("reason") or ""),
        markers=tuple(markers),
        voice=_voice_from_dict(data.get("voice")),
        prior_tier=str(data.get("prior_tier") or ""),
        prior_rule=str(data.get("prior_rule") or ""),
        extract_kind=str(data.get("extract_kind") or ""),
        note=str(data.get("note") or ""),
    )


def _suggested_stubs(blacklist: Blacklist) -> list[str]:
    """Skip and library hints derived from rows. Nothing writes them."""
    counts: dict[MarkerKind, int] = {}
    for row in blacklist.rows:
        if row.cause is not ExcludeCause.HARD_MARKER:
            continue
        for hit in row.markers:
            counts[hit.kind] = counts.get(hit.kind, 0) + 1
    lines: list[str] = []
    for kind in sorted(counts, key=lambda item: item.value):
        lines.append(
            f"- id: blacklist-{kind.value}\n"
            f"  tier: skip\n"
            f"  name_contains: [{_STUBS[kind]!r}]\n"
            f"  # {counts[kind]} row(s); not applied"
        )
    voice_rows = sum(
        1 for row in blacklist.rows if row.cause is ExcludeCause.VOICE_MISMATCH
    )
    if voice_rows:
        lines.append(
            f"- id: blacklist-voice-mismatch\n"
            f"  tier: library\n"
            f"  # {voice_rows} path(s) below keep cut {_KEEP_OVERLAP:.2f}; "
            f"not applied"
        )
    return lines


def build_blacklist(roots: list[Path], root: Path | None = None) -> Blacklist:
    """Walk dumps and candidates, gate, score survivors, write blacklist.json.

    Does not convert, promote, park, or edit authorship.rules. Holds
    .cache/picklist/blacklist.lock for the write. Does not take the picklist lock.
    """
    voice_root = root or voice_core.VOICE_ROOT
    cfg = voice_core.load_config(voice_root)
    latest = _latest_rows(voice_root)
    notes = _not_max_notes(latest)
    bank = _VoiceBank.from_root(voice_root, _solo_candidate_paths(voice_root, latest))
    targets = _targets(roots, voice_root, cfg)
    drafts: list[_Draft] = []
    kept = 0
    unscored = 0
    for path in targets:
        peek = _peek(path, voice_root)
        decision = voice_core.classify_authorship(path, cfg)
        note = notes.get(str(path), "")
        hits = _marker_hits(peek.text)
        # Agent note: voice is computed for audit even when hard markers fire.
        # Hard inclusion ignores voice; voice-mismatch uses the keep cut only.
        voice = _score(peek.text, bank, path)
        if _is_hard(hits):
            drafts.append(
                _Draft(
                    path=path,
                    cause=ExcludeCause.HARD_MARKER,
                    reason=_hard_reason(hits),
                    markers=hits,
                    voice=voice,
                    prior_tier=str(decision["suggested_tier"]),
                    prior_rule=str(decision["rule_id"]),
                    extract_kind=peek.kind,
                    note=note,
                )
            )
            continue
        if voice is None:
            unscored += 1
            continue
        if voice.overlap < _KEEP_OVERLAP:
            drafts.append(
                _Draft(
                    path=path,
                    cause=ExcludeCause.VOICE_MISMATCH,
                    reason=(
                        f"Overlap {voice.overlap:.4f} is below the keep cut "
                        f"{_KEEP_OVERLAP:.2f}."
                    ),
                    markers=(),
                    voice=voice,
                    prior_tier=str(decision["suggested_tier"]),
                    prior_rule=str(decision["rule_id"]),
                    extract_kind=peek.kind,
                    note=note,
                )
            )
            continue
        kept += 1
    blacklist = Blacklist(
        rows=_rank(drafts),
        scanned=len(targets),
        kept=kept,
        unscored=unscored,
        bank_files=bank.bank_files,
        solo_files=bank.solo_files,
        bank_digest=bank.digest,
    )
    _check_counts(blacklist)
    with voice_core.FileLock(_lock_path(voice_root)):
        voice_core.atomic_write_json(
            _blacklist_path(voice_root), _to_payload(blacklist)
        )
    return blacklist


def load_blacklist(root: Path | None = None) -> Blacklist:
    """Read blacklist.json. Does not peek and does not rescore."""
    voice_root = root or voice_core.VOICE_ROOT
    path = _blacklist_path(voice_root)
    if not path.is_file():
        raise FileNotFoundError(f"no blacklist at {path}; run voicectl blacklist")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("blacklist JSON must be an object")
    raw_rows = data.get("rows")
    if not isinstance(raw_rows, list):
        raise ValueError("blacklist JSON missing rows")
    rows = tuple(_row_from_dict(row) for row in raw_rows)
    for index, row in enumerate(rows, start=1):
        if row.rank != index:
            raise ValueError("blacklist ranks are not 1..n in order")
    blacklist = Blacklist(
        rows=rows,
        scanned=int(data["scanned"]),
        kept=int(data["kept"]),
        unscored=int(data["unscored"]),
        bank_files=int(data["bank_files"]),
        solo_files=int(data["solo_files"]),
        bank_digest=str(data.get("bank_digest") or ""),
    )
    _check_counts(blacklist)
    return blacklist


def render_blacklist(bl: Blacklist) -> str:
    """Markdown view plus suggested rule stubs. Derived; not a second store."""
    lines = [
        "# Voice blacklist",
        "",
        (
            f"scanned {bl.scanned}, kept {bl.kept}, unscored {bl.unscored}, "
            f"bank files {bl.bank_files}, solo files {bl.solo_files}, "
            f"bank digest {bl.bank_digest or '(none)'}."
        ),
        (
            f"Keep cut {_KEEP_OVERLAP:.2f}. Hard markers exclude regardless of "
            "voice; voice on those rows is audit-only."
        ),
        "",
        "## Hard marker",
        "",
    ]
    hard = [row for row in bl.rows if row.cause is ExcludeCause.HARD_MARKER]
    voice = [row for row in bl.rows if row.cause is ExcludeCause.VOICE_MISMATCH]
    lines.extend(_render_section(hard))
    lines.append("## Voice mismatch")
    lines.append("")
    lines.extend(_render_section(voice))
    lines.append("## Suggested stubs (not applied)")
    lines.append("")
    stubs = _suggested_stubs(bl)
    if stubs:
        lines.extend(stubs)
    else:
        lines.append("(none)")
    lines.append("")
    return "\n".join(lines)


def _render_section(rows: list[ExcludeRow]) -> list[str]:
    if not rows:
        return ["(none)", ""]
    lines: list[str] = []
    for row in rows:
        lines.append(
            f"- [{row.rank}] `{row.path}` {row.cause.value} "
            f"prior={row.prior_tier}/{row.prior_rule}. {row.reason}"
        )
        if row.note:
            lines.append(f"  note: {row.note}")
    lines.append("")
    return lines


def render_blacklist_paths(bl: Blacklist) -> str:
    """excluded_paths(), one per line, rank order."""
    return "".join(f"{path}\n" for path in bl.excluded_paths())


def render_blacklist_json(bl: Blacklist) -> str:
    """JSON view of the same Blacklist. Derived."""
    return json.dumps(_to_payload(bl), indent=2) + "\n"
