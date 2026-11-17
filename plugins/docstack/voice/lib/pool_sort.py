#!/usr/bin/env python3
"""Join picklist + blacklist + voice-kept into a three-bucket pool sort.

Agent note: DefinitelyNot beats DefinitelyYes. Mixed is the remainder of the
blacklist scan universe. Writes caches only. Does not convert or promote.
Refuses when latest.json is older than blacklist.json so a pre-cleanup
picklist cannot drive the join.
"""

from __future__ import annotations

import enum
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import blacklist as blacklist_mod
import picklist as picklist_mod
import voice_core

__all__ = [
    "Bucket",
    "Reason",
    "PoolRow",
    "PoolSort",
    "build_pool_sort",
    "cli_pool_sort",
]


class Bucket(enum.StrEnum):
    """Closed partition. Every universe path lands in exactly one."""

    DEFINITELY_NOT = "definitely_not"
    DEFINITELY_YES = "definitely_yes"
    MIXED = "mixed"


class Reason(enum.StrEnum):
    """Why a path landed where it did. Closed tags for report tallies."""

    BLACKLIST_HARD = "blacklist_hard"
    BLACKLIST_VOICE = "blacklist_voice"
    PICKLIST_NOT_MAX = "picklist_not_max"
    PICKLIST_RESCUE = "picklist_rescue"
    PICKLIST_CONFIRM = "picklist_confirm"
    PICKLIST_MIXED = "picklist_mixed"
    PICKLIST_ABSTAIN = "picklist_abstain"
    PICKLIST_CONVERTED = "picklist_converted"
    NO_PICKLIST_ROW = "no_picklist_row"
    VOICE_KEPT = "voice_kept"
    VOICE_KEPT_ONLY = "voice_kept_only"
    UNSCORED = "unscored"
    RESCUE_NOT_VOICE_KEPT = "rescue_not_voice_kept"
    CONFIRM_NOT_VOICE_KEPT = "confirm_not_voice_kept"


@dataclass(frozen=True)
class PoolRow:
    """One classified path with closed reason tags."""

    path: str
    bucket: Bucket
    reasons: tuple[Reason, ...]
    urgency: str = ""
    overlap: float | None = None
    prior_tier: str = ""
    prior_rule: str = ""


@dataclass
class PoolSort:
    """Full partition plus run metadata."""

    run_id: str
    universe_count: int
    definitely_not: list[PoolRow] = field(default_factory=list)
    definitely_yes: list[PoolRow] = field(default_factory=list)
    mixed: list[PoolRow] = field(default_factory=list)
    reason_tallies: dict[str, int] = field(default_factory=dict)


def _cache_dir(voice_root: Path) -> Path:
    return voice_root / ".cache" / "picklist"


def _blacklist_path(voice_root: Path) -> Path:
    return _cache_dir(voice_root) / "blacklist.json"


def _picklist_path(voice_root: Path) -> Path:
    return _cache_dir(voice_root) / "latest.json"


def _whitelist_path(voice_root: Path) -> Path:
    return _cache_dir(voice_root) / "whitelist-kept.json"


def _out_dir(voice_root: Path, run_id: str) -> Path:
    return _cache_dir(voice_root) / "pool-sort" / run_id


def new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _require_fresh_picklist(voice_root: Path) -> None:
    """Refuse a picklist older than the blacklist (pre-cleanup stale)."""
    pl = _picklist_path(voice_root)
    bl = _blacklist_path(voice_root)
    if not pl.is_file():
        raise FileNotFoundError(f"no picklist at {pl}; run voicectl picklist")
    if not bl.is_file():
        raise FileNotFoundError(f"no blacklist at {bl}; run voicectl blacklist")
    if pl.stat().st_mtime < bl.stat().st_mtime:
        raise RuntimeError(
            "picklist is older than blacklist; run voicectl picklist first "
            f"(picklist mtime {pl.stat().st_mtime}, "
            f"blacklist mtime {bl.stat().st_mtime})"
        )


def _load_whitelist(voice_root: Path) -> dict[str, float]:
    """path -> overlap from whitelist-kept.json."""
    path = _whitelist_path(voice_root)
    if not path.is_file():
        raise FileNotFoundError(
            f"no whitelist-kept at {path}; rebuild voice-kept list first"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("rows") or []
    out: dict[str, float] = {}
    for row in rows:
        p = str(Path(row["path"]).resolve())
        out[p] = float(row.get("overlap") or 0.0)
    return out


def _blacklist_cause_map(
    bl: blacklist_mod.Blacklist,
) -> dict[str, blacklist_mod.ExcludeCause]:
    return {str(row.path.resolve()): row.cause for row in bl.rows}


def _picklist_index(
    pl: picklist_mod.Picklist,
) -> dict[str, picklist_mod.PickRow]:
    return {str(row.path.resolve()): row for row in pl.rows}


def _classify(
    path: Path,
    *,
    bl_cause: blacklist_mod.ExcludeCause | None,
    pick: picklist_mod.PickRow | None,
    overlap: float | None,
    voice_kept: bool,
) -> PoolRow:
    """Apply closed rules. DefinitelyNot wins over DefinitelyYes."""
    reasons: list[Reason] = []
    prior_tier = ""
    prior_rule = ""
    urgency = ""

    if pick is not None:
        prior_tier = pick.prior_tier
        prior_rule = pick.prior_rule
        if pick.urgency is not None:
            urgency = pick.urgency.name.lower()

    # --- Definitely not ---
    if bl_cause is blacklist_mod.ExcludeCause.HARD_MARKER:
        reasons.append(Reason.BLACKLIST_HARD)
    elif bl_cause is blacklist_mod.ExcludeCause.VOICE_MISMATCH:
        reasons.append(Reason.BLACKLIST_VOICE)

    if pick is not None and pick.kind is picklist_mod.RowKind.NOT_MAX:
        reasons.append(Reason.PICKLIST_NOT_MAX)

    if reasons and (
        Reason.BLACKLIST_HARD in reasons
        or Reason.BLACKLIST_VOICE in reasons
        or Reason.PICKLIST_NOT_MAX in reasons
    ):
        # Only the not-reasons for the not bucket.
        not_reasons = tuple(
            r
            for r in reasons
            if r
            in (
                Reason.BLACKLIST_HARD,
                Reason.BLACKLIST_VOICE,
                Reason.PICKLIST_NOT_MAX,
            )
        )
        return PoolRow(
            path=str(path),
            bucket=Bucket.DEFINITELY_NOT,
            reasons=not_reasons,
            urgency=urgency,
            overlap=overlap,
            prior_tier=prior_tier,
            prior_rule=prior_rule,
        )

    # --- Definitely yes ---
    is_rescue = (
        pick is not None
        and pick.kind is picklist_mod.RowKind.BATCH
        and pick.urgency is picklist_mod.Urgency.RESCUE
    )
    is_confirm = (
        pick is not None
        and pick.kind is picklist_mod.RowKind.BATCH
        and pick.urgency is picklist_mod.Urgency.CONFIRM
    )
    if (is_rescue or is_confirm) and voice_kept:
        yes_reasons: list[Reason] = [Reason.VOICE_KEPT]
        if is_rescue:
            yes_reasons.append(Reason.PICKLIST_RESCUE)
        else:
            yes_reasons.append(Reason.PICKLIST_CONFIRM)
        return PoolRow(
            path=str(path),
            bucket=Bucket.DEFINITELY_YES,
            reasons=tuple(yes_reasons),
            urgency=urgency,
            overlap=overlap,
            prior_tier=prior_tier,
            prior_rule=prior_rule,
        )

    # --- Mixed ---
    mixed_reasons: list[Reason] = []
    if pick is None:
        mixed_reasons.append(Reason.NO_PICKLIST_ROW)
    elif pick.kind is picklist_mod.RowKind.BATCH:
        if pick.urgency is picklist_mod.Urgency.MIXED:
            mixed_reasons.append(Reason.PICKLIST_MIXED)
        elif pick.urgency is picklist_mod.Urgency.RESCUE:
            mixed_reasons.append(Reason.RESCUE_NOT_VOICE_KEPT)
        elif pick.urgency is picklist_mod.Urgency.CONFIRM:
            mixed_reasons.append(Reason.CONFIRM_NOT_VOICE_KEPT)
    elif pick.kind is picklist_mod.RowKind.ABSTAIN:
        mixed_reasons.append(Reason.PICKLIST_ABSTAIN)
    elif pick.kind is picklist_mod.RowKind.CONVERTED:
        mixed_reasons.append(Reason.PICKLIST_CONVERTED)

    if voice_kept and not (is_rescue or is_confirm):
        mixed_reasons.append(Reason.VOICE_KEPT_ONLY)
    if not voice_kept and bl_cause is None:
        mixed_reasons.append(Reason.UNSCORED)

    if not mixed_reasons:
        mixed_reasons.append(Reason.NO_PICKLIST_ROW)

    return PoolRow(
        path=str(path),
        bucket=Bucket.MIXED,
        reasons=tuple(dict.fromkeys(mixed_reasons)),
        urgency=urgency,
        overlap=overlap,
        prior_tier=prior_tier,
        prior_rule=prior_rule,
    )


def build_pool_sort(
    voice_root: Path | None = None,
    run_id: str | None = None,
) -> PoolSort:
    """Load caches, classify the blacklist universe, write pool-sort artifacts."""
    root = voice_root or voice_core.VOICE_ROOT
    _require_fresh_picklist(root)
    rid = run_id or new_run_id()

    cfg = voice_core.load_config(root)
    roots = voice_core.default_dump_roots(root)
    universe = blacklist_mod._targets(roots, root, cfg)
    bl = blacklist_mod.load_blacklist(root)
    pl = picklist_mod.load_picklist(root)
    kept = _load_whitelist(root)
    cause_map = _blacklist_cause_map(bl)
    pick_map = _picklist_index(pl)

    result = PoolSort(run_id=rid, universe_count=len(universe))
    for path in universe:
        key = str(path.resolve())
        row = _classify(
            path,
            bl_cause=cause_map.get(key),
            pick=pick_map.get(key),
            overlap=kept.get(key),
            voice_kept=key in kept,
        )
        if row.bucket is Bucket.DEFINITELY_NOT:
            result.definitely_not.append(row)
        elif row.bucket is Bucket.DEFINITELY_YES:
            result.definitely_yes.append(row)
        else:
            result.mixed.append(row)

    # Stable path order inside each bucket.
    result.definitely_not.sort(key=lambda r: r.path.lower())
    result.definitely_yes.sort(
        key=lambda r: (
            0 if r.urgency == "rescue" else 1,
            -(r.overlap or 0.0),
            r.path.lower(),
        )
    )
    result.mixed.sort(key=lambda r: r.path.lower())

    tallies: Counter[str] = Counter()
    for row in result.definitely_not + result.definitely_yes + result.mixed:
        for reason in row.reasons:
            tallies[reason.value] += 1
    result.reason_tallies = dict(sorted(tallies.items()))

    _write_artifacts(root, result)
    return result


def _row_to_dict(row: PoolRow) -> dict[str, Any]:
    return {
        "path": row.path,
        "bucket": row.bucket.value,
        "reasons": [r.value for r in row.reasons],
        "urgency": row.urgency,
        "overlap": row.overlap,
        "prior_tier": row.prior_tier,
        "prior_rule": row.prior_rule,
    }


def _write_paths(path: Path, rows: list[PoolRow]) -> None:
    path.write_text(
        "".join(f"{r.path}\n" for r in rows),
        encoding="utf-8",
    )


def _write_artifacts(voice_root: Path, result: PoolSort) -> None:
    out = _out_dir(voice_root, result.run_id)
    out.mkdir(parents=True, exist_ok=True)
    _write_paths(out / "definitely-not-paths.txt", result.definitely_not)
    _write_paths(out / "definitely-yes-paths.txt", result.definitely_yes)
    _write_paths(out / "mixed-paths.txt", result.mixed)

    # Stable convert-queue pointers. yes-bucket-paths.txt is the lint-safe name
    # for recipes; keep the older filename as a duplicate for existing notes.
    yes_body = (out / "definitely-yes-paths.txt").read_text(encoding="utf-8")
    latest_yes = _cache_dir(voice_root) / "definitely-yes-paths.txt"
    latest_yes.write_text(yes_body, encoding="utf-8")
    yes_bucket = _cache_dir(voice_root) / "yes-bucket-paths.txt"
    yes_bucket.write_text(yes_body, encoding="utf-8")

    report = {
        "run_id": result.run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "universe_count": result.universe_count,
        "counts": {
            "definitely_not": len(result.definitely_not),
            "definitely_yes": len(result.definitely_yes),
            "mixed": len(result.mixed),
        },
        "reason_tallies": result.reason_tallies,
        "partition_ok": (
            len(result.definitely_not) + len(result.definitely_yes) + len(result.mixed)
            == result.universe_count
        ),
        "paths": {
            "definitely_not": str(out / "definitely-not-paths.txt"),
            "definitely_yes": str(out / "definitely-yes-paths.txt"),
            "mixed": str(out / "mixed-paths.txt"),
            "definitely_yes_latest": str(latest_yes),
            "yes_bucket_latest": str(yes_bucket),
        },
        "definitely_not": [_row_to_dict(r) for r in result.definitely_not],
        "definitely_yes": [_row_to_dict(r) for r in result.definitely_yes],
        "mixed": [_row_to_dict(r) for r in result.mixed],
    }
    (out / "report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    # Slim stdout companion next to latest yes list.
    (_cache_dir(voice_root) / "pool-sort-latest.json").write_text(
        json.dumps(
            {
                "run_id": result.run_id,
                "counts": report["counts"],
                "reason_tallies": result.reason_tallies,
                "partition_ok": report["partition_ok"],
                "paths": report["paths"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def cli_pool_sort(argv: list[str], voice_root: Path | None = None) -> int:
    """CLI for `voicectl pool-sort`."""
    root = voice_root or voice_core.VOICE_ROOT
    if argv and argv[0] in ("-h", "--help"):
        print("usage: voicectl pool-sort", file=sys.stderr)
        return 2
    try:
        result = build_pool_sort(root)
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        print(f"pool-sort failed: {exc}", file=sys.stderr)
        return 1
    summary = {
        "run_id": result.run_id,
        "universe_count": result.universe_count,
        "counts": {
            "definitely_not": len(result.definitely_not),
            "definitely_yes": len(result.definitely_yes),
            "mixed": len(result.mixed),
        },
        "reason_tallies": result.reason_tallies,
        "paths": {
            "definitely_not": str(
                _out_dir(root, result.run_id) / "definitely-not-paths.txt"
            ),
            "definitely_yes": str(
                _out_dir(root, result.run_id) / "definitely-yes-paths.txt"
            ),
            "mixed": str(_out_dir(root, result.run_id) / "mixed-paths.txt"),
            "definitely_yes_latest": str(_cache_dir(root) / "definitely-yes-paths.txt"),
            "yes_bucket_latest": str(_cache_dir(root) / "yes-bucket-paths.txt"),
            "report": str(_out_dir(root, result.run_id) / "report.json"),
        },
    }
    print(json.dumps(summary, indent=2))
    return 0
