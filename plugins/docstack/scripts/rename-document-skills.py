#!/usr/bin/env python3
"""Rename every docstack skill/agent to a document-* id.

Agent note: one map owns old→new. Rerun is idempotent when the new
name already exists and the old name is gone. Updates frontmatter name,
directory paths, slash refs, and bold skill tokens across the plugin.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
REPO = PLUGIN.parent.parent
SKILLS = PLUGIN / "skills"
AGENTS = PLUGIN / "agents"

# Prefer short document-* ids when the old name already carried a docs prefix.
SPECIAL: dict[str, str] = {
    "docs-mode": "document-mode",
    "docstack-help": "document-help",
    "setup-docstack": "document-setup",
    "create-docs-verify-skill": "document-create-verify-skill",
    "maintain-docs-verify-skill": "document-maintain-verify-skill",
    "docs-agent": "document-agent",
}


def document_name(old: str) -> str:
    if old.startswith("document-"):
        return old
    if old in SPECIAL:
        return SPECIAL[old]
    return f"document-{old}"


def skill_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for path in sorted(SKILLS.iterdir()):
        if not path.is_dir():
            continue
        old = path.name
        mapping[old] = document_name(old)
    return mapping


def agent_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for path in sorted(AGENTS.glob("*.md")):
        old = path.stem
        mapping[old] = document_name(old)
    return mapping


def git_mv(src: Path, dst: Path) -> None:
    if src.resolve() == dst.resolve():
        return
    if dst.exists():
        if not src.exists():
            return
        raise SystemExit(f"target exists: {dst}")
    rel_src = src.relative_to(REPO)
    rel_dst = dst.relative_to(REPO)
    subprocess.run(
        ["git", "mv", str(rel_src), str(rel_dst)],
        check=True,
        cwd=REPO,
    )


def rewrite_text(text: str, pairs: list[tuple[str, str]]) -> str:
    # Longest old names first so create-docs-verify-skill beats docs.
    for old, new in pairs:
        if old == new:
            continue
        text = text.replace(f"skills/{old}/", f"skills/{new}/")
        text = text.replace(f"agents/{old}.md", f"agents/{new}.md")
        text = text.replace(f"agents/{old}", f"agents/{new}")
        text = text.replace(f"../{old}/", f"../{new}/")
        text = text.replace(f"/{old}", f"/{new}")
        text = text.replace(f"**{old}**", f"**{new}**")
        text = text.replace(f"`{old}`", f"`{new}`")
        text = text.replace(f"[{old}]", f"[{new}]")
        text = re.sub(
            rf"(?m)^(name:\s*){re.escape(old)}\s*$",
            rf"\1{new}",
            text,
        )
        # Principles index: bare principle-<title> → document-principle-<title>
        # Skip when already under document- to keep reruns idempotent.
        if old.startswith("principle-") and new.startswith("document-principle-"):
            leaf = old[len("principle-") :]
            text = re.sub(
                rf"(?<!document-)principle-{re.escape(leaf)}",
                f"document-principle-{leaf}",
                text,
            )
    return text


def main() -> int:
    skills = skill_map()
    agents = agent_map()
    # git mv skills
    for old, new in skills.items():
        git_mv(SKILLS / old, SKILLS / new)
    for old, new in agents.items():
        git_mv(AGENTS / f"{old}.md", AGENTS / f"{new}.md")

    pairs = sorted(
        {**skills, **agents}.items(),
        key=lambda kv: len(kv[0]),
        reverse=True,
    )

    # Rewrite every text file under the plugin (skip voice/.venv).
    skip_parts = {".venv", "node_modules", "__pycache__"}
    for path in PLUGIN.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip_parts for part in path.parts):
            continue
        if path.suffix.lower() not in {
            ".md",
            ".json",
            ".txt",
            ".yml",
            ".yaml",
            ".sh",
            ".py",
            ".toml",
        }:
            continue
        if path.name == "rename-document-skills.py":
            continue
        original = path.read_text(encoding="utf-8")
        updated = rewrite_text(original, pairs)
        # docs-mode → document-mode already covered; also fix leftover "docs-mode"
        # phrases that describe the product mode after folder rename.
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            print(f"rewrote {path.relative_to(PLUGIN)}")

    print("skill map:")
    for old, new in sorted(skills.items()):
        print(f"  {old} -> {new}")
    print("agent map:")
    for old, new in sorted(agents.items()):
        print(f"  {old} -> {new}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
