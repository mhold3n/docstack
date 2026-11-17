#!/usr/bin/env python3
"""Build multi-bank conditioning index from mass + archetype pulls.

Agent note: replaces the single-doc distill of two random file excerpts.
Char budget applies to the style index only; prose-mode policy stays outside.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import voice_core
from banks.archetypes import load_archetypes
from banks.mass import ensure_mass, load_mass
from banks.specs import BANK_IDS


def _mass_cue_line(bank_id: str, payload: dict[str, Any] | None, top_k: int) -> str:
    if not payload:
        return f"{bank_id}: (missing)"
    parts: list[str] = []
    rates = payload.get("rates") or {}
    if rates:
        rate_bits = [f"{k}={v}" for k, v in list(rates.items())[:4]]
        parts.append("rates[" + ", ".join(rate_bits) + "]")
    top = payload.get("top") or []
    if top:
        keys = [str(row.get("key")) for row in top[:top_k]]
        parts.append("top[" + "; ".join(keys) + "]")
    if not parts:
        return f"{bank_id}: (empty)"
    return f"{bank_id}: " + " | ".join(parts)


def build_conditioning_index(
    voice_root: Path | None = None,
    *,
    max_chars: int | None = None,
    archetype_pulls_per_bank: int = 1,
    mass_top_k: int = 12,
) -> dict[str, Any]:
    """Return conditioning_brief + metadata for ensure_profile.

    When banks are disabled or mass is empty, returns empty=True brief stub.
    """
    root = voice_root or voice_core.VOICE_ROOT
    cfg = voice_core.load_config(root)
    banks_cfg = cfg.get("banks") if isinstance(cfg.get("banks"), dict) else {}
    enabled = bool(banks_cfg.get("enabled", True))
    pulls = int(banks_cfg.get("archetype_pulls_per_bank", archetype_pulls_per_bank))
    top_k = int(banks_cfg.get("mass_top_k", mass_top_k))
    budget = int(
        max_chars if max_chars is not None else cfg.get("conditioning_max_chars", 3200)
    )
    version = voice_core.hash_corpus_version(root, cfg)
    if not enabled:
        brief = (
            f"Write in the derived voice corpus_version={version[:12]}.\n"
            "Voice banks disabled in config."
        )
        return {
            "conditioning_brief": brief[:budget],
            "banks_version": version,
            "empty": False,
            "enabled": False,
        }

    manifest = ensure_mass(root, top_k=top_k)
    if manifest.get("empty") or manifest.get("n_source_files", 0) == 0:
        brief = (
            f"Voice corpus references/active/ is empty. "
            f"No bank mass. corpus_version={version}."
        )
        return {
            "conditioning_brief": brief[:budget],
            "banks_version": version,
            "empty": True,
            "enabled": True,
        }

    lines: list[str] = [
        f"Write in the derived voice corpus_version={version[:12]}.",
        "Dynamic voice banks active (multi-doc mass + archetypes).",
        "Banks: " + ", ".join(BANK_IDS) + ".",
        "Use concrete measurements and named systems before interpretation.",
        "Do not invent facts. Preserve numbers, equations, and conclusions.",
        "Mass cues:",
    ]
    for bank_id in BANK_IDS:
        payload = load_mass(root, corpus_version=version, bank_id=bank_id)
        lines.append("  " + _mass_cue_line(bank_id, payload, min(top_k, 6)))

    lines.append("Archetype pulls:")
    archetypes = load_archetypes(root)
    for bank_id in BANK_IDS:
        doc = archetypes[bank_id]
        if not doc.entries:
            lines.append(f"  [{bank_id}] (none yet)")
            continue
        for entry in doc.entries[: max(0, pulls)]:
            excerpt = entry.text.replace("\n", " ").strip()
            if len(excerpt) > 160:
                excerpt = excerpt[:160].rstrip() + "…"
            lines.append(f"  [{bank_id}] ({entry.source_path}): {excerpt}")

    brief = "\n".join(lines)
    if len(brief) > budget:
        brief = brief[:budget]
    return {
        "conditioning_brief": brief,
        "banks_version": version,
        "empty": False,
        "enabled": True,
        "n_source_files": manifest.get("n_source_files"),
    }
