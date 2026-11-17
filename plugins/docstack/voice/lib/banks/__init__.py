#!/usr/bin/env python3
"""Multi-doc voice banks: mass JSON + archetype markdown.

Public API used by voice_core ensure/condition and voicectl banks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from banks.archetypes import (
    append_entry,
    load_archetype,
    load_archetypes,
    scaffold_all,
    verify_archetypes,
)
from banks.condition import build_conditioning_index
from banks.mass import ensure_mass, load_mass, rebuild_mass
from banks.specs import ARCHETYPE_RULES, BANK_IDS, assert_bank_id

__all__ = [
    "BANK_IDS",
    "ARCHETYPE_RULES",
    "assert_bank_id",
    "rebuild_mass",
    "ensure_mass",
    "load_mass",
    "load_archetype",
    "load_archetypes",
    "append_entry",
    "scaffold_all",
    "verify_archetypes",
    "build_conditioning_index",
    "cli_banks",
]


def cli_banks(argv: list[str], voice_root: Path | None = None) -> int:
    """voicectl banks rebuild|status|show BANK|verify|scaffold."""
    import json
    import sys

    import voice_core

    root = voice_root or voice_core.VOICE_ROOT
    if not argv or argv[0] in ("-h", "--help"):
        print(
            "usage: voicectl banks rebuild|status|show BANK|verify|scaffold",
            file=sys.stderr,
        )
        return 2
    cmd = argv[0]
    cfg = voice_core.load_config(root)
    banks_cfg = cfg.get("banks") if isinstance(cfg.get("banks"), dict) else {}
    top_k = int(banks_cfg.get("mass_top_k", 12))

    if cmd == "rebuild":
        scaffold_all(root)
        manifest = rebuild_mass(root, top_k=top_k)
        print(json.dumps(manifest, indent=2))
        return 0
    if cmd == "status":
        scaffold_all(root)
        manifest = ensure_mass(root, top_k=top_k)
        verification = verify_archetypes(root)
        print(
            json.dumps(
                {"mass": manifest, "archetypes": verification},
                indent=2,
            )
        )
        return 0 if verification.get("ok") else 1
    if cmd == "show":
        if len(argv) < 2:
            print("banks show requires BANK id", file=sys.stderr)
            return 2
        bank_id = assert_bank_id(argv[1])
        payload = load_mass(root, bank_id=bank_id)
        doc = load_archetype(root, bank_id)
        print(
            json.dumps(
                {
                    "mass": payload,
                    "archetype": {
                        "path": str(doc.path),
                        "entry_count": doc.entry_count,
                        "entries": [
                            {
                                "index": e.index,
                                "source_path": e.source_path,
                                "span": e.span,
                                "text": e.text[:400],
                            }
                            for e in doc.entries
                        ],
                    },
                },
                indent=2,
            )
        )
        return 0 if payload else 1
    if cmd == "verify":
        report = verify_archetypes(root)
        print(json.dumps(report, indent=2))
        return 0 if report.get("ok") else 1
    if cmd == "scaffold":
        paths = scaffold_all(root)
        print(json.dumps([str(p) for p in paths], indent=2))
        return 0
    print(f"unknown banks subcommand: {cmd}", file=sys.stderr)
    return 2
