#!/usr/bin/env python3
"""Archetype markdown read/validate/append for multi-doc voice banks.

Agent note: append-only. Harvest agents cite source_path under active/.
Mass JSON is never written here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import voice_core
from banks.specs import ARCHETYPE_RULES, BANK_IDS, assert_bank_id

_FRONT_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)
_ENTRY_RE = re.compile(
    r"(?ms)^### Entry\s+(\d+)\s*\n"
    r"-+\s*\n"
    r"source_path:\s*(.+?)\s*\n"
    r"(?:span:\s*(.+?)\s*\n)?"
    r"\n(.*?)(?=^### Entry\s+\d+|\Z)"
)


@dataclass(frozen=True)
class ArchetypeEntry:
    """One curated exemplar pulled from active/."""

    index: int
    source_path: str
    text: str
    span: str | None = None


@dataclass(frozen=True)
class ArchetypeDoc:
    """Parsed archetype markdown for one bank."""

    bank_id: str
    path: Path
    corpus_version_at_last_harvest: str
    entry_count: int
    entries: tuple[ArchetypeEntry, ...]
    raw: str


def archetypes_dir(voice_root: Path) -> Path:
    """Directory holding the eight archetype markdown files."""
    return voice_root / "banks" / "archetypes"


def archetype_path(voice_root: Path, bank_id: str) -> Path:
    """Path to one archetype doc."""
    assert_bank_id(bank_id)
    return archetypes_dir(voice_root) / f"{bank_id}.md"


def _parse_frontmatter(raw: str) -> dict[str, str]:
    match = _FRONT_RE.match(raw)
    if not match:
        return {}
    out: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        out[key.strip()] = val.strip().strip("\"'")
    return out


def _render_frontmatter(bank_id: str, corpus_version: str, entry_count: int) -> str:
    return (
        "---\n"
        f"bank_id: {bank_id}\n"
        f"corpus_version_at_last_harvest: {corpus_version}\n"
        f"entry_count: {entry_count}\n"
        "---\n"
    )


def scaffold_archetype(voice_root: Path, bank_id: str) -> Path:
    """Create empty archetype doc if missing. Returns path."""
    assert_bank_id(bank_id)
    directory = archetypes_dir(voice_root)
    directory.mkdir(parents=True, exist_ok=True)
    path = archetype_path(voice_root, bank_id)
    if path.is_file():
        return path
    rule = ARCHETYPE_RULES[bank_id]
    body = (
        _render_frontmatter(bank_id, "", 0)
        + f"\n# Archetype bank: `{bank_id}`\n\n"
        + f"Selection rule: {rule}\n\n"
        + "## Entries\n\n"
    )
    path.write_text(body, encoding="utf-8")
    return path


def scaffold_all(voice_root: Path) -> list[Path]:
    """Ensure all eight archetype files exist."""
    return [scaffold_archetype(voice_root, bank_id) for bank_id in BANK_IDS]


def load_archetype(voice_root: Path, bank_id: str) -> ArchetypeDoc:
    """Parse one archetype file. Scaffolds if missing."""
    path = scaffold_archetype(voice_root, bank_id)
    raw = path.read_text(encoding="utf-8")
    front = _parse_frontmatter(raw)
    entries: list[ArchetypeEntry] = []
    for match in _ENTRY_RE.finditer(raw):
        entries.append(
            ArchetypeEntry(
                index=int(match.group(1)),
                source_path=match.group(2).strip(),
                span=(match.group(3).strip() if match.group(3) else None),
                text=match.group(4).strip(),
            )
        )
    declared = int(front.get("entry_count") or len(entries))
    return ArchetypeDoc(
        bank_id=front.get("bank_id") or bank_id,
        path=path,
        corpus_version_at_last_harvest=front.get("corpus_version_at_last_harvest", ""),
        entry_count=declared,
        entries=tuple(entries),
        raw=raw,
    )


def load_archetypes(voice_root: Path) -> dict[str, ArchetypeDoc]:
    """Load all eight archetype docs."""
    return {bank_id: load_archetype(voice_root, bank_id) for bank_id in BANK_IDS}


def _active_source_ok(voice_root: Path, source_path: str) -> bool:
    """True when source_path names an existing file under active/."""
    active = voice_core.active_dir(voice_root)
    candidate = Path(source_path)
    if candidate.is_absolute():
        try:
            candidate.resolve().relative_to(active.resolve())
        except ValueError:
            return False
        return candidate.is_file()
    # Basename or relative under active/
    direct = active / candidate.name
    if direct.is_file():
        return True
    rel = active / candidate
    return rel.is_file()


def append_entry(
    voice_root: Path,
    bank_id: str,
    *,
    source_path: str,
    text: str,
    span: str | None = None,
    corpus_version: str = "",
) -> ArchetypeDoc:
    """Append one entry. Raises ValueError if source_path is not under active/."""
    assert_bank_id(bank_id)
    text = text.strip()
    if not text:
        raise ValueError("entry text is empty")
    if not _active_source_ok(voice_root, source_path):
        raise ValueError(f"source_path not found under active/: {source_path}")
    doc = load_archetype(voice_root, bank_id)
    # Dedup on source_path + exact text.
    for existing in doc.entries:
        if existing.source_path == source_path and existing.text.strip() == text:
            return doc
    next_index = len(doc.entries) + 1
    block = f"### Entry {next_index}\n---\nsource_path: {source_path}\n"
    if span:
        block += f"span: {span}\n"
    block += f"\n{text}\n\n"
    # Rewrite frontmatter entry_count and harvest version.
    body_wo_front = _FRONT_RE.sub("", doc.raw, count=1)
    if "## Entries" not in body_wo_front:
        body_wo_front = body_wo_front.rstrip() + "\n\n## Entries\n\n"
    new_count = next_index
    version = corpus_version or doc.corpus_version_at_last_harvest
    new_raw = (
        _render_frontmatter(bank_id, version, new_count)
        + body_wo_front.rstrip()
        + "\n\n"
        + block
    )
    doc.path.write_text(new_raw, encoding="utf-8")
    return load_archetype(voice_root, bank_id)


def verify_archetypes(voice_root: Path) -> dict[str, Any]:
    """Check frontmatter entry_count vs parsed entries and source paths."""
    report: dict[str, Any] = {"ok": True, "banks": {}}
    for bank_id in BANK_IDS:
        doc = load_archetype(voice_root, bank_id)
        missing: list[str] = []
        for entry in doc.entries:
            if not _active_source_ok(voice_root, entry.source_path):
                missing.append(entry.source_path)
        count_ok = doc.entry_count == len(doc.entries)
        bank_ok = count_ok and not missing
        if not bank_ok:
            report["ok"] = False
        report["banks"][bank_id] = {
            "entry_count_declared": doc.entry_count,
            "entry_count_parsed": len(doc.entries),
            "count_ok": count_ok,
            "missing_sources": missing,
        }
    return report
