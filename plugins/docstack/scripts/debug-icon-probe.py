#!/usr/bin/env python3
"""Probe docstack vs pstack skill icon frontmatter for slash vs badge tests."""

# #region agent log
import json
import time
from pathlib import Path

LOG_PATH = Path("/Users/maxholden/.cursor/voice/.cursor/debug-a4af42.log")
SESSION = "a4af42"


def log(hypothesis_id: str, location: str, message: str, data: dict) -> None:
    """Append one NDJSON debug line for the debug-mode session."""
    payload = {
        "sessionId": SESSION,
        "runId": "icon-probe-1",
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


# #endregion

DOCSTACK = Path("/Users/maxholden/.cursor/plugins/local/docstack")
PSTACK = Path(
    "/Users/maxholden/.cursor/plugins/cache/cursor-public/pstack/"
    "e1cc03121a0e71129a4fb730d7c5528a0a3e43c8"
)

# Icons Cursor docs name as examples for Custom Mode badges.
DOCUMENTED_ICONS = {
    "code",
    "terminal",
    "bug",
    "git-branch",
    "book-open",
    "beaker",
    "shield",
    "rocket",
    "crown",  # used by poteto-mode in the wild
}


def parse_frontmatter(path: Path) -> dict:
    """Parse YAML-ish frontmatter keys from a SKILL.md."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    out = {}
    for line in parts[1].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def main() -> None:
    plugin_json = json.loads(
        (DOCSTACK / ".cursor-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    logo_rel = plugin_json.get("logo")
    logo_path = DOCSTACK / logo_rel if logo_rel else None
    # #region agent log
    log(
        "A",
        "debug-icon-probe.py:plugin-logo",
        "Plugin logo field and file existence",
        {
            "logoField": logo_rel,
            "logoExists": bool(logo_path and logo_path.is_file()),
            "logoBytes": logo_path.stat().st_size
            if logo_path and logo_path.is_file()
            else None,
            "note": "Store/Customize uses plugin logo; slash menu may not",
        },
    )
    # #endregion

    docs_skills = sorted((DOCSTACK / "skills").glob("*/SKILL.md"))
    with_icon = []
    without_icon = []
    for skill in docs_skills:
        fm = parse_frontmatter(skill)
        entry = {
            "skill": skill.parent.name,
            "icon": fm.get("icon"),
            "color": fm.get("color"),
            "iconInDocumentedSet": fm.get("icon") in DOCUMENTED_ICONS
            if fm.get("icon")
            else None,
        }
        if fm.get("icon"):
            with_icon.append(entry)
        else:
            without_icon.append(entry)

    # #region agent log
    log(
        "B",
        "debug-icon-probe.py:docstack-skill-icons",
        "Which docstack skills declare icon/color frontmatter",
        {
            "withIconCount": len(with_icon),
            "withoutIconCount": len(without_icon),
            "withIcon": with_icon,
            "sampleWithout": [e["skill"] for e in without_icon[:8]],
            "docsClaim": "icon/color style Custom Mode badge only, not slash menu",
        },
    )
    # #endregion

    poteto = parse_frontmatter(PSTACK / "skills" / "poteto-mode" / "SKILL.md")
    docs_mode = parse_frontmatter(DOCSTACK / "skills" / "docs-mode" / "SKILL.md")
    # #region agent log
    log(
        "C",
        "debug-icon-probe.py:icon-name-validity",
        "Compare poteto-mode vs docs-mode icon names against documented set",
        {
            "potetoMode": poteto,
            "docsMode": docs_mode,
            "docsModeIconValidPerDocsExamples": docs_mode.get("icon")
            in DOCUMENTED_ICONS,
            "docsSaysBookOpenNotBook": True,
            "expectedSlashBehavior": (
                "both show generic cube if slash ignores skill icon"
            ),
        },
    )
    # #endregion

    # #region agent log
    log(
        "D",
        "debug-icon-probe.py:surface-matrix",
        "Surface matrix from Cursor docs + user screenshots",
        {
            "storeCustomize": "plugin.json logo PNG — user confirmed book shows",
            "slashMenu": "no documented skill/plugin image mapping — user sees cubes",
            "customModeBadge": "skill frontmatter icon+color — untested in this run",
            "hypotheses": {
                "A": "slash menu never uses plugin logo PNG",
                "B": "slash menu never uses skill icon frontmatter",
                "C": "icon:book invalid; book-open needed for Custom Mode badge only",
                "D": "pstack poteto-mode also cubes in slash (control)",
                "E": "Custom Mode badge can show named icon while slash stays cube",
            },
        },
    )
    # #endregion

    print(json.dumps({"ok": True, "loggedTo": str(LOG_PATH)}, indent=2))


if __name__ == "__main__":
    main()
