#!/usr/bin/env python3
"""Quarantine blacklist and converted dump sources out of the live population.

Agent note: moves dumps under references/{Drive,Takeout*} into a reversible
cache tree. Never touches active/, candidates/, or library/. Rewrites picklist
queues so leftover convert work is the yes-bucket misses. Default CLI applies.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import blacklist as blacklist_mod
import cleanup as cleanup_mod
import marker_runtime
import voice_core

__all__ = [
    "TrimOp",
    "TrimPlan",
    "cache_root",
    "run_dir",
    "build_plan",
    "apply_plan",
    "cli_population_trim",
]

Reason = Literal["blacklist", "converted_done"]
DUMP_TOPS = frozenset({"Drive", "Takeout", "Takeout 3", "Takeout 4"})


@dataclass(frozen=True)
class TrimOp:
    """One dump-source quarantine. dest keeps the path under references/."""

    src: str
    dest: str
    reason: Reason


@dataclass
class TrimPlan:
    """Ops plus the picklist queues that apply will write."""

    run_id: str
    ops: list[TrimOp]
    convert_remaining: list[str]
    failed_convert: list[str]
    contribute_candidates: list[str]


def cache_root(voice_root: Path) -> Path:
    return voice_root / ".cache" / "references-cleanup" / "population-trim"


def run_dir(voice_root: Path, run_id: str) -> Path:
    return cache_root(voice_root) / run_id


def _picklist_dir(voice_root: Path) -> Path:
    return voice_root / ".cache" / "picklist"


def _path_key(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path)


def _read_paths(path: Path) -> list[Path]:
    if not path.is_file():
        return []
    out: list[Path] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        out.append(Path(text))
    return out


def _write_paths(path: Path, paths: list[str]) -> None:
    path.write_text("".join(f"{p}\n" for p in paths), encoding="utf-8")


def _is_dump_source(path: Path, refs: Path) -> bool:
    if not path.is_file():
        return False
    if cleanup_mod._is_protected(path, refs):
        return False
    try:
        rel = path.resolve().relative_to(refs.resolve())
    except ValueError:
        return False
    return bool(rel.parts) and rel.parts[0] in DUMP_TOPS


def _quarantine_dest(src: Path, refs: Path, quarantine: Path) -> Path:
    rel = src.resolve().relative_to(refs.resolve())
    return quarantine / rel


def _extract_status_map(voice_root: Path) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for rec in marker_runtime.list_status(voice_root):
        source = str(rec.get("source_path") or "")
        status = rec.get("status")
        if not source or not status:
            continue
        out.setdefault(_path_key(Path(source)), set()).add(str(status))
    return out


def _is_converted_done(
    path: Path, statuses: dict[str, set[str]], candidates: Path
) -> bool:
    if "ok" in statuses.get(_path_key(path), set()):
        return True
    return (candidates / f"{path.stem}.md").is_file()


def _picklist_converted_dumps(voice_root: Path, refs: Path) -> list[Path]:
    """Dump sources tagged picklist_converted on the frozen pool-sort report.

    Frozen on purpose. This trim must not rebuild pool-sort as a side effect.
    """
    latest = _picklist_dir(voice_root) / "pool-sort-latest.json"
    if not latest.is_file():
        return []
    try:
        meta = json.loads(latest.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    run_id = str(meta.get("run_id") or "")
    report_path = _picklist_dir(voice_root) / "pool-sort" / run_id / "report.json"
    if not report_path.is_file():
        return []
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    out: list[Path] = []
    seen: set[str] = set()
    for bucket in ("definitely_yes", "mixed", "definitely_not"):
        for row in report.get(bucket) or []:
            if "picklist_converted" not in (row.get("reasons") or []):
                continue
            raw = str(row.get("path") or "")
            if not raw:
                continue
            path = Path(raw)
            key = _path_key(path)
            if key in seen:
                continue
            seen.add(key)
            if _is_dump_source(path, refs):
                out.append(path)
    return out


def _claim(
    ops: list[TrimOp],
    claimed: set[str],
    src: Path,
    dest: Path,
    reason: Reason,
) -> None:
    key = _path_key(src)
    if key in claimed:
        return
    claimed.add(key)
    ops.append(TrimOp(src=str(src), dest=str(dest), reason=reason))


def _live_targets(voice_root: Path) -> list[Path]:
    cfg = voice_core.load_config(voice_root)
    roots = voice_core.default_dump_roots(voice_root)
    return blacklist_mod._targets(roots, voice_root, cfg)


def _candidate_paths(voice_root: Path) -> list[str]:
    candidates = voice_core.candidates_dir(voice_root)
    if not candidates.is_dir():
        return []
    return [str(p) for p in sorted(candidates.glob("*.md")) if p.is_file()]


def build_plan(voice_root: Path, run_id: str) -> TrimPlan:
    """Build quarantine ops from blacklist.json + yes-bucket + frozen converted."""
    refs = cleanup_mod.references_dir(voice_root)
    quarantine = run_dir(voice_root, run_id) / "quarantine"
    candidates = voice_core.candidates_dir(voice_root)
    statuses = _extract_status_map(voice_root)
    picklist = _picklist_dir(voice_root)
    yes_paths = _read_paths(picklist / "yes-bucket-paths.txt")
    if not yes_paths:
        yes_paths = _read_paths(picklist / "definitely-yes-paths.txt")

    ops: list[TrimOp] = []
    claimed: set[str] = set()

    bl = blacklist_mod.load_blacklist(voice_root)
    for row in bl.rows:
        src = Path(row.path)
        if not src.is_file():
            continue
        if cleanup_mod._is_protected(src, refs):
            continue
        if not _is_dump_source(src, refs):
            continue
        dest = _quarantine_dest(src, refs, quarantine)
        _claim(ops, claimed, src, dest, "blacklist")

    converted_sources = list(yes_paths)
    converted_sources.extend(_picklist_converted_dumps(voice_root, refs))
    for src in converted_sources:
        if not _is_dump_source(src, refs):
            continue
        if not _is_converted_done(src, statuses, candidates):
            continue
        dest = _quarantine_dest(src, refs, quarantine)
        _claim(ops, claimed, src, dest, "converted_done")

    convert_remaining: list[str] = []
    failed_convert: list[str] = []
    for src in yes_paths:
        if _is_converted_done(src, statuses, candidates):
            continue
        convert_remaining.append(str(src))
        st = statuses.get(_path_key(src), set())
        if "failed" in st and "ok" not in st:
            failed_convert.append(str(src))

    return TrimPlan(
        run_id=run_id,
        ops=ops,
        convert_remaining=convert_remaining,
        failed_convert=failed_convert,
        contribute_candidates=_candidate_paths(voice_root),
    )


def _rewrite_queues(voice_root: Path, plan: TrimPlan) -> dict[str, str]:
    picklist = _picklist_dir(voice_root)
    picklist.mkdir(parents=True, exist_ok=True)
    paths = {
        "convert_remaining": str(picklist / "convert-remaining-paths.txt"),
        "contribute_candidates": str(picklist / "contribute-candidates-paths.txt"),
        "yes_bucket": str(picklist / "yes-bucket-paths.txt"),
        "definitely_yes": str(picklist / "definitely-yes-paths.txt"),
        "failed_convert": str(picklist / "failed-convert-paths.txt"),
    }
    _write_paths(Path(paths["convert_remaining"]), plan.convert_remaining)
    _write_paths(Path(paths["contribute_candidates"]), plan.contribute_candidates)
    _write_paths(Path(paths["yes_bucket"]), plan.convert_remaining)
    _write_paths(Path(paths["definitely_yes"]), plan.convert_remaining)
    _write_paths(Path(paths["failed_convert"]), plan.failed_convert)
    return paths


def apply_plan(
    voice_root: Path, plan: TrimPlan, *, dry_run: bool = False
) -> dict[str, Any]:
    """Ledger-then-move each op. dry_run writes plan.json only."""
    refs = cleanup_mod.references_dir(voice_root)
    rdir = run_dir(voice_root, plan.run_id)
    rdir.mkdir(parents=True, exist_ok=True)
    plan_payload = {
        "run_id": plan.run_id,
        "ops": [asdict(op) for op in plan.ops],
        "convert_remaining": plan.convert_remaining,
        "failed_convert": plan.failed_convert,
        "contribute_candidates_count": len(plan.contribute_candidates),
    }
    (rdir / "plan.json").write_text(
        json.dumps(plan_payload, indent=2) + "\n", encoding="utf-8"
    )

    live_before = len(_live_targets(voice_root))
    moved_blacklist = 0
    moved_converted = 0
    skipped = 0
    errors: list[str] = []

    if dry_run:
        for op in plan.ops:
            if Path(op.src).is_file():
                if op.reason == "blacklist":
                    moved_blacklist += 1
                else:
                    moved_converted += 1
            else:
                skipped += 1
        live_after = live_before - moved_blacklist - moved_converted
        summary = {
            "run_id": plan.run_id,
            "dry_run": True,
            "moved_blacklist": moved_blacklist,
            "moved_converted": moved_converted,
            "remaining_convert": len(plan.convert_remaining),
            "contribute_candidates": len(plan.contribute_candidates),
            "live_targets_before": live_before,
            "live_targets_after": live_after,
            "skipped": skipped,
            "errors": errors,
            "paths": {
                "plan": str(rdir / "plan.json"),
                "quarantine": str(rdir / "quarantine"),
            },
        }
        (rdir / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )
        return summary

    for op in plan.ops:
        src = Path(op.src)
        dest = Path(op.dest)
        try:
            cleanup_mod._refuse_if_protected([src, dest], refs, voice_root)
            if not src.exists() and dest.exists():
                skipped += 1
                cleanup_mod._append_ledger(
                    rdir,
                    {
                        "status": "skipped",
                        "op": asdict(op),
                        "detail": "already_applied",
                        "ts": time.time(),
                    },
                )
                continue
            if not src.exists():
                skipped += 1
                cleanup_mod._append_ledger(
                    rdir,
                    {
                        "status": "skipped",
                        "op": asdict(op),
                        "detail": "missing",
                        "ts": time.time(),
                    },
                )
                continue
            cleanup_mod._append_ledger(
                rdir,
                {
                    "status": "pending",
                    "op": asdict(op),
                    "ts": time.time(),
                },
            )
            cleanup_mod._relocate(src, dest)
            cleanup_mod._rm_empty_dirs(src.parent, refs)
            cleanup_mod._append_ledger(
                rdir,
                {
                    "status": "ok",
                    "op": asdict(op),
                    "ts": time.time(),
                },
            )
            if op.reason == "blacklist":
                moved_blacklist += 1
            else:
                moved_converted += 1
        except Exception as exc:  # noqa: BLE001 — boundary: record and continue
            errors.append(f"{op.reason} {op.src}: {exc}")
            cleanup_mod._append_ledger(
                rdir,
                {
                    "status": "error",
                    "op": asdict(op),
                    "error": str(exc),
                    "ts": time.time(),
                },
            )

    queue_paths = _rewrite_queues(voice_root, plan)
    live_after = len(_live_targets(voice_root))
    summary = {
        "run_id": plan.run_id,
        "dry_run": False,
        "moved_blacklist": moved_blacklist,
        "moved_converted": moved_converted,
        "remaining_convert": len(plan.convert_remaining),
        "contribute_candidates": len(plan.contribute_candidates),
        "live_targets_before": live_before,
        "live_targets_after": live_after,
        "skipped": skipped,
        "errors": errors,
        "paths": {
            "plan": str(rdir / "plan.json"),
            "ledger": str(rdir / "ledger.jsonl"),
            "quarantine": str(rdir / "quarantine"),
            **queue_paths,
        },
    }
    (rdir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def run_trim(
    voice_root: Path, *, dry_run: bool = False, run_id: str | None = None
) -> dict[str, Any]:
    rid = run_id or cleanup_mod.new_run_id()
    plan = build_plan(voice_root, rid)
    return apply_plan(voice_root, plan, dry_run=dry_run)


def _parse_argv(argv: list[str]) -> tuple[bool, str | None]:
    dry_run = False
    run_id: str | None = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg in ("-h", "--help"):
            raise ValueError("help")
        if arg == "--dry-run":
            dry_run = True
            i += 1
            continue
        if arg == "--run" and i + 1 < len(argv):
            run_id = argv[i + 1]
            i += 2
            continue
        if arg.startswith("--run="):
            run_id = arg.split("=", 1)[1]
            i += 1
            continue
        raise ValueError(f"unknown argument: {arg}")
    return dry_run, run_id


def cli_population_trim(argv: list[str], voice_root: Path | None = None) -> int:
    """CLI entry for `voicectl population-trim`. Default applies."""
    root = voice_root or voice_core.VOICE_ROOT
    try:
        dry_run, run_id = _parse_argv(argv)
    except ValueError as exc:
        print(
            "usage: voicectl population-trim [--dry-run] [--run ID]",
            file=sys.stderr,
        )
        if str(exc) != "help":
            print(exc, file=sys.stderr)
        return 2
    try:
        summary = run_trim(root, dry_run=dry_run, run_id=run_id)
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        print(f"population-trim failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2))
    return 0 if not summary.get("errors") else 1
