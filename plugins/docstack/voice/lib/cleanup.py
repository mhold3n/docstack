#!/usr/bin/env python3
"""Consolidate references dump mirrors and quarantine exact duplicate downloads.

Agent note: operates only under references/{Drive,Takeout,Takeout 3,Takeout 4}.
Never touches active/, candidates/, or library/. Inventory and plan are
read-only. Apply moves unique Takeout*/Drive content into Drive, quarantines
sha256 duplicates, flattens nested Drive/Drive, then removes empty Takeout
3/4 husks. Undo reverses ledger rows in reverse order.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import voice_core

__all__ = [
    "PROTECTED_DIRNAMES",
    "cache_root",
    "new_run_id",
    "run_dir",
    "build_inventory",
    "build_plan",
    "apply_plan",
    "undo_run",
    "cli_cleanup",
]

# Corpus tiers. Any op whose src or dest resolves under these is refused.
PROTECTED_DIRNAMES = frozenset({"active", "candidates", "library"})
# Files below this size are still moved for consolidate, but skip hash reclaim.
_MIN_HASH_BYTES = 1024
_SKIP_NAMES = frozenset({".DS_Store", "Thumbs.db", "desktop.ini"})
# Copy-suffix heuristic for winner ranking.
_COPY_SUFFIX_RE = re.compile(
    r"(?:\s*\(\d+\))|(?:\s+copy(?:\s+\d+)?)|(?:\s+Copy(?:\s+\d+)?)$",
    re.IGNORECASE,
)

OpKind = Literal["move", "quarantine", "flatten", "rmdir"]


@dataclass(frozen=True)
class PlanOp:
    """One filesystem mutation. Ordered in plan.json and ledger.jsonl."""

    kind: OpKind
    src: str
    dest: str = ""
    reason: str = ""
    sha256: str = ""
    size: int = 0


@dataclass
class InventoryReport:
    """Hash scan summary written next to the sqlite index."""

    run_id: str
    roots: dict[str, dict[str, Any]] = field(default_factory=dict)
    file_count: int = 0
    hashed_count: int = 0
    duplicate_groups: int = 0
    reclaimable_bytes: int = 0
    nested_drive: bool = False
    peer_folders: list[str] = field(default_factory=list)


def cache_root(voice_root: Path) -> Path:
    """Parent for all cleanup runs."""
    return voice_root / ".cache" / "references-cleanup"


def new_run_id() -> str:
    """UTC timestamp run id. Collision-safe at second resolution for this tool."""
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def run_dir(voice_root: Path, run_id: str) -> Path:
    return cache_root(voice_root) / run_id


def references_dir(voice_root: Path) -> Path:
    return voice_root / "references"


def _is_protected(path: Path, refs: Path) -> bool:
    """True when path is under a corpus tier directory inside references/."""
    try:
        rel = path.resolve().relative_to(refs.resolve())
    except ValueError:
        # Outside references/ (e.g. .cache quarantine) is not a corpus tier.
        return False
    parts = rel.parts
    return bool(parts) and parts[0] in PROTECTED_DIRNAMES


def _path_allowed(path: Path, refs: Path, voice_root: Path) -> bool:
    """Ops may touch dump trees under references/ or this tool's cache only."""
    resolved = path.resolve()
    if _is_protected(resolved, refs):
        return False
    try:
        resolved.relative_to(refs.resolve())
        return True
    except ValueError:
        pass
    try:
        resolved.relative_to(cache_root(voice_root).resolve())
        return True
    except ValueError:
        return False


def _refuse_if_protected(
    paths: list[Path], refs: Path, voice_root: Path | None = None
) -> None:
    """Refuse corpus tiers. When voice_root is set, also refuse alien destinations."""
    for p in paths:
        if _is_protected(p, refs):
            raise RuntimeError(f"refusing protected path: {p}")
        if voice_root is not None and not _path_allowed(p, refs, voice_root):
            raise RuntimeError(f"refusing path outside references/cleanup cache: {p}")


def dump_drive_roots(refs: Path) -> list[tuple[str, Path]]:
    """Named dump Drive roots that currently exist.

    Agent note: label is used in reports. Path is the Drive folder that peers
    with references/Drive (Takeout N wraps an inner Drive/).
    """
    out: list[tuple[str, Path]] = []
    drive = refs / "Drive"
    if drive.is_dir():
        out.append(("drive", drive))
    for label, rel in (
        ("takeout3", Path("Takeout 3") / "Drive"),
        ("takeout4", Path("Takeout 4") / "Drive"),
    ):
        p = refs / rel
        if p.is_dir():
            out.append((label, p))
    # Empty husk Takeout/Takeout has no Drive peer; still note Takeout root.
    takeout = refs / "Takeout"
    if takeout.is_dir():
        inner = takeout / "Takeout"
        # Prefer inner Takeout/Drive if present; else the Takeout dir itself
        # only for non-Drive leftovers after consolidate.
        cand = inner / "Drive" if (inner / "Drive").is_dir() else None
        if cand is not None:
            out.append(("takeout", cand))
    return out


def _sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            buf = f.read(chunk)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def _has_copy_suffix(name: str) -> bool:
    stem = Path(name).stem
    return bool(_COPY_SUFFIX_RE.search(stem))


def winner_rank(path: Path, refs: Path) -> tuple:
    """Lower tuple wins. Drive over Takeout*, shorter rel, no copy suffix, lex.

    Agent note: matches the plan's winner rule as a total order.
    """
    try:
        rel = path.resolve().relative_to(refs.resolve())
    except ValueError:
        rel = Path(path.name)
    parts = rel.parts
    under_drive = 0 if parts and parts[0] == "Drive" else 1
    # Nested Drive/Drive ranks worse than top Drive (longer path).
    nested_penalty = (
        1 if len(parts) >= 2 and parts[0] == "Drive" and parts[1] == "Drive" else 0
    )
    copy_pen = 1 if _has_copy_suffix(path.name) else 0
    return (under_drive, nested_penalty, len(parts), copy_pen, str(rel).lower())


def _open_index(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS files (
            path TEXT PRIMARY KEY,
            root_label TEXT NOT NULL,
            rel TEXT NOT NULL,
            size INTEGER NOT NULL,
            mtime REAL NOT NULL,
            sha256 TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_files_sha ON files(sha256)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_files_rel ON files(rel)")
    return conn


def _iter_files(root: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        # Do not descend into protected names if somehow nested.
        dirnames[:] = [
            d for d in dirnames if d not in PROTECTED_DIRNAMES and d != ".git"
        ]
        for name in filenames:
            if name in _SKIP_NAMES or name.startswith("._"):
                continue
            yield Path(dirpath) / name


def build_inventory(
    voice_root: Path,
    run_id: str | None = None,
    *,
    progress: bool = True,
) -> InventoryReport:
    """Walk dump Drive roots, hash files ≥1KB, write sqlite + report.json."""
    refs = references_dir(voice_root)
    rid = run_id or new_run_id()
    rdir = run_dir(voice_root, rid)
    rdir.mkdir(parents=True, exist_ok=True)
    db_path = rdir / "hash-index.sqlite"
    if db_path.exists():
        db_path.unlink()
    conn = _open_index(db_path)
    report = InventoryReport(run_id=rid)
    report.nested_drive = (refs / "Drive" / "Drive").is_dir()

    roots = dump_drive_roots(refs)
    # Peer folder names at Drive top level across roots.
    top_by_label: dict[str, set[str]] = {}
    for label, root in roots:
        names = {
            p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")
        }
        top_by_label[label] = names
        report.roots[label] = {
            "path": str(root),
            "top_dirs": sorted(names),
        }

    if "drive" in top_by_label:
        drive_tops = top_by_label["drive"]
        peers: set[str] = set()
        for label, names in top_by_label.items():
            if label == "drive":
                continue
            peers |= names & drive_tops
        report.peer_folders = sorted(peers)

    hashed = 0
    counted = 0
    for label, root in roots:
        for path in _iter_files(root):
            try:
                st = path.stat()
            except OSError:
                continue
            if not path.is_file():
                continue
            rel = str(path.relative_to(root)).replace("\\", "/")
            sha: str | None = None
            if st.st_size >= _MIN_HASH_BYTES:
                try:
                    sha = _sha256_file(path)
                    hashed += 1
                except OSError as exc:
                    print(f"hash skip {path}: {exc}", file=sys.stderr)
            counted += 1
            if progress and counted % 200 == 0:
                print(
                    f"inventory … {counted} files, {hashed} hashed",
                    file=sys.stderr,
                )
            conn.execute(
                "INSERT OR REPLACE INTO files("
                "path, root_label, rel, size, mtime, sha256"
                ") VALUES (?,?,?,?,?,?)",
                (str(path), label, rel, st.st_size, st.st_mtime, sha),
            )
    conn.commit()

    # Duplicate groups among hashed files.
    rows = conn.execute(
        """
        SELECT sha256, COUNT(*), SUM(size), GROUP_CONCAT(path, '\n')
        FROM files
        WHERE sha256 IS NOT NULL
        GROUP BY sha256
        HAVING COUNT(*) > 1
        """
    ).fetchall()
    reclaim = 0
    for sha, n, total_size, _paths in rows:
        # Keep one copy's bytes; rest are reclaimable.
        # total_size counts each file; reclaim (n-1)/n of sum when equal sizes.
        # Safer: sum sizes minus max single size in group.
        sizes = [
            r[0]
            for r in conn.execute(
                "SELECT size FROM files WHERE sha256 = ?", (sha,)
            ).fetchall()
        ]
        reclaim += sum(sizes) - max(sizes)
    report.file_count = counted
    report.hashed_count = hashed
    report.duplicate_groups = len(rows)
    report.reclaimable_bytes = reclaim
    conn.close()

    (rdir / "inventory.json").write_text(
        json.dumps(asdict(report), indent=2) + "\n", encoding="utf-8"
    )
    return report


def _load_files(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    cur = conn.execute("SELECT path, root_label, rel, size, mtime, sha256 FROM files")
    return [
        {
            "path": r[0],
            "root_label": r[1],
            "rel": r[2],
            "size": r[3],
            "mtime": r[4],
            "sha256": r[5],
        }
        for r in cur.fetchall()
    ]


def build_plan(voice_root: Path, run_id: str) -> dict[str, Any]:
    """Emit Move/Quarantine/Flatten/Rmdir ops from an inventory index.

    Agent note: Drive wins. Unique Takeout*/Drive files move into Drive when
    the relative path is free. Same-path different hash goes to
    references/Takeout/<rel>. Exact hash losers quarantine under the run dir.
    """
    refs = references_dir(voice_root)
    rdir = run_dir(voice_root, run_id)
    db_path = rdir / "hash-index.sqlite"
    if not db_path.is_file():
        raise FileNotFoundError(f"missing inventory index: {db_path}")
    conn = sqlite3.connect(str(db_path))
    files = _load_files(conn)
    conn.close()

    drive_root = refs / "Drive"
    takeout_dest_root = refs / "Takeout"
    quarantine_root = rdir / "quarantine"
    ops: list[PlanOp] = []
    planned_srcs: set[str] = set()

    def add_op(op: PlanOp) -> None:
        if op.src in planned_srcs:
            return
        src_p = Path(op.src)
        dest_p = Path(op.dest) if op.dest else src_p
        _refuse_if_protected([src_p, dest_p], refs, voice_root)
        ops.append(op)
        planned_srcs.add(op.src)

    # 1) Exact-hash duplicate groups first. Flatten must not run before this or
    # a nested Drive/Drive copy lifts into a second live path beside its twin.
    by_sha: dict[str, list[dict[str, Any]]] = {}
    for rec in files:
        sha = rec["sha256"]
        if not sha:
            continue
        by_sha.setdefault(sha, []).append(rec)

    for sha, group in by_sha.items():
        if len(group) < 2:
            continue
        ranked = sorted(group, key=lambda r: winner_rank(Path(r["path"]), refs))
        keeper = ranked[0]
        for loser in ranked[1:]:
            src = Path(loser["path"])
            if str(src) in planned_srcs:
                continue
            try:
                qrel = src.resolve().relative_to(refs.resolve())
            except ValueError:
                qrel = Path(src.name)
            qdest = quarantine_root / qrel
            add_op(
                PlanOp(
                    kind="quarantine",
                    src=str(src),
                    dest=str(qdest),
                    reason=f"duplicate_of:{keeper['path']}",
                    sha256=sha,
                    size=int(loser["size"]),
                )
            )

    # 2) Flatten nested Drive/Drive → Drive for files not already quarantined.
    nested = drive_root / "Drive"
    if nested.is_dir():
        for path in _iter_files(nested):
            if str(path) in planned_srcs:
                continue
            rel = path.relative_to(nested)
            dest = drive_root / rel
            try:
                st = path.stat()
            except OSError:
                continue
            sha = ""
            if st.st_size >= _MIN_HASH_BYTES:
                try:
                    sha = _sha256_file(path)
                except OSError:
                    sha = ""
            if dest.exists():
                same = False
                if sha and dest.is_file() and dest.stat().st_size == st.st_size:
                    try:
                        same = _sha256_file(dest) == sha
                    except OSError:
                        same = False
                if same:
                    qdest = quarantine_root / "flatten-dup" / rel
                    add_op(
                        PlanOp(
                            kind="quarantine",
                            src=str(path),
                            dest=str(qdest),
                            reason="flatten_duplicate",
                            sha256=sha,
                            size=st.st_size,
                        )
                    )
                else:
                    tdest = takeout_dest_root / "Drive-nested-conflict" / rel
                    add_op(
                        PlanOp(
                            kind="move",
                            src=str(path),
                            dest=str(tdest),
                            reason="flatten_conflict",
                            sha256=sha,
                            size=st.st_size,
                        )
                    )
            else:
                add_op(
                    PlanOp(
                        kind="flatten",
                        src=str(path),
                        dest=str(dest),
                        reason="nested_drive",
                        sha256=sha,
                        size=st.st_size,
                    )
                )

    # 3) Remaining Takeout*/Drive files → Drive or Takeout.
    for rec in files:
        if rec["root_label"] == "drive":
            continue
        src = Path(rec["path"])
        if str(src) in planned_srcs:
            continue
        if not src.exists():
            continue
        rel = rec["rel"]
        dest_drive = drive_root / rel
        sha = rec["sha256"] or ""
        size = int(rec["size"])
        if dest_drive.exists():
            same = False
            if sha and dest_drive.is_file():
                # Prefer index lookup: if dest is also indexed with same sha.
                dest_rec = next(
                    (
                        r
                        for r in files
                        if r["path"] == str(dest_drive) and r["sha256"] == sha
                    ),
                    None,
                )
                if dest_rec is not None:
                    same = True
                elif dest_drive.stat().st_size == size:
                    try:
                        same = _sha256_file(dest_drive) == sha
                    except OSError:
                        same = False
            if same:
                # Should already be quarantined in step 2; if not, quarantine.
                try:
                    qrel = src.resolve().relative_to(refs.resolve())
                except ValueError:
                    qrel = Path(src.name)
                add_op(
                    PlanOp(
                        kind="quarantine",
                        src=str(src),
                        dest=str(quarantine_root / qrel),
                        reason=f"duplicate_of:{dest_drive}",
                        sha256=sha,
                        size=size,
                    )
                )
            else:
                # Unique content at colliding path → Takeout/<rel>.
                add_op(
                    PlanOp(
                        kind="move",
                        src=str(src),
                        dest=str(takeout_dest_root / rel),
                        reason="path_conflict_unique",
                        sha256=sha,
                        size=size,
                    )
                )
        else:
            add_op(
                PlanOp(
                    kind="move",
                    src=str(src),
                    dest=str(dest_drive),
                    reason="merge_into_drive",
                    sha256=sha,
                    size=size,
                )
            )

    # 4) Schedule empty husk removal for Takeout 3/4 after apply empties them.
    for husk_name in ("Takeout 3", "Takeout 4"):
        husk = refs / husk_name
        if husk.is_dir():
            add_op(
                PlanOp(
                    kind="rmdir",
                    src=str(husk),
                    dest="",
                    reason="empty_takeout_husk",
                )
            )

    plan = {
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "op_count": len(ops),
        "by_kind": {
            k: sum(1 for o in ops if o.kind == k)
            for k in ("move", "quarantine", "flatten", "rmdir")
        },
        "reclaimable_bytes_planned": sum(o.size for o in ops if o.kind == "quarantine"),
        "ops": [asdict(o) for o in ops],
    }
    (rdir / "plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    return plan


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _append_ledger(rdir: Path, row: dict[str, Any]) -> None:
    with (rdir / "ledger.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _relocate(src: Path, dest: Path) -> None:
    """Move src to dest. Idempotent if src gone and dest present."""
    if not src.exists():
        if dest.exists():
            return
        raise FileNotFoundError(f"src missing and dest absent: {src}")
    if dest.exists():
        if src.resolve() == dest.resolve():
            return
        raise FileExistsError(f"dest exists: {dest}")
    _ensure_parent(dest)
    shutil.move(str(src), str(dest))


def _rm_empty_dirs(path: Path, stop_at: Path) -> None:
    """Remove empty directories from path upward until stop_at (exclusive)."""
    cur = path
    stop_at = stop_at.resolve()
    while cur.exists() and cur.resolve() != stop_at:
        try:
            cur.rmdir()
        except OSError:
            break
        cur = cur.parent


def _strip_junk_files(root: Path) -> int:
    """Delete .DS_Store / Thumbs.db under root. Returns count removed.

    Agent note: inventory skips these, so husk rmdir would otherwise stick.
    """
    removed = 0
    if not root.is_dir():
        return 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if name in _SKIP_NAMES or name.startswith("._"):
                try:
                    (Path(dirpath) / name).unlink()
                    removed += 1
                except OSError:
                    pass
    return removed


def sweep_leftover_husks(voice_root: Path) -> dict[str, Any]:
    """Remove junk-only Takeout 3/4 and nested Drive/Drive after a main apply."""
    refs = references_dir(voice_root)
    report: dict[str, Any] = {"stripped": {}, "removed": []}
    nested = refs / "Drive" / "Drive"
    if nested.is_dir():
        report["stripped"]["Drive/Drive"] = _strip_junk_files(nested)
        for dirpath, _dns, filenames in os.walk(nested, topdown=False):
            if filenames:
                continue
            try:
                Path(dirpath).rmdir()
            except OSError:
                pass
        if not nested.exists():
            report["removed"].append(str(nested))
    for husk_name in ("Takeout 3", "Takeout 4"):
        husk = refs / husk_name
        if not husk.is_dir():
            continue
        report["stripped"][husk_name] = _strip_junk_files(husk)
        for dirpath, _dns, filenames in os.walk(husk, topdown=False):
            if filenames:
                continue
            try:
                Path(dirpath).rmdir()
            except OSError:
                pass
        if not husk.exists():
            report["removed"].append(str(husk))
    # Empty Takeout/Takeout husk from the original empty mirror.
    inner = refs / "Takeout" / "Takeout"
    if inner.is_dir():
        report["stripped"]["Takeout/Takeout"] = _strip_junk_files(inner)
        for dirpath, _dns, filenames in os.walk(inner, topdown=False):
            if filenames:
                continue
            try:
                Path(dirpath).rmdir()
            except OSError:
                pass
    return report


def apply_plan(voice_root: Path, run_id: str) -> dict[str, Any]:
    """Execute plan.json. Append ledger before each successful mutation."""
    refs = references_dir(voice_root)
    rdir = run_dir(voice_root, run_id)
    plan_path = rdir / "plan.json"
    if not plan_path.is_file():
        raise FileNotFoundError(f"missing plan: {plan_path}")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    ops = plan.get("ops") or []
    applied = 0
    skipped = 0
    errors: list[str] = []

    for raw in ops:
        op = PlanOp(
            kind=raw["kind"],
            src=raw["src"],
            dest=raw.get("dest") or "",
            reason=raw.get("reason") or "",
            sha256=raw.get("sha256") or "",
            size=int(raw.get("size") or 0),
        )
        src = Path(op.src)
        dest = Path(op.dest) if op.dest else None
        try:
            if op.kind == "rmdir":
                # Strip inventory-skipped junk so husks can actually go away.
                if src.is_dir():
                    _strip_junk_files(src)
                    for dirpath, dirnames, filenames in os.walk(src, topdown=False):
                        if filenames:
                            continue
                        p = Path(dirpath)
                        try:
                            p.rmdir()
                        except OSError:
                            pass
                    if src.exists():
                        skipped += 1
                        _append_ledger(
                            rdir,
                            {
                                "status": "skipped",
                                "op": asdict(op),
                                "detail": "not_empty",
                                "ts": time.time(),
                            },
                        )
                        continue
                _append_ledger(
                    rdir,
                    {
                        "status": "ok",
                        "op": asdict(op),
                        "ts": time.time(),
                    },
                )
                applied += 1
                continue

            assert dest is not None
            _refuse_if_protected([src, dest], refs, voice_root)
            if not src.exists() and dest.exists():
                skipped += 1
                _append_ledger(
                    rdir,
                    {
                        "status": "skipped",
                        "op": asdict(op),
                        "detail": "already_applied",
                        "ts": time.time(),
                    },
                )
                continue
            # Ledger first with pending, then mutate, then ok.
            _append_ledger(
                rdir,
                {
                    "status": "pending",
                    "op": asdict(op),
                    "ts": time.time(),
                },
            )
            _relocate(src, dest)
            # Clean empty parents under Takeout mirrors.
            if op.kind in ("move", "quarantine", "flatten"):
                _rm_empty_dirs(src.parent, refs)
            _append_ledger(
                rdir,
                {
                    "status": "ok",
                    "op": asdict(op),
                    "ts": time.time(),
                },
            )
            applied += 1
        except Exception as exc:  # noqa: BLE001 — boundary: record and continue
            errors.append(f"{op.kind} {op.src}: {exc}")
            _append_ledger(
                rdir,
                {
                    "status": "error",
                    "op": asdict(op),
                    "error": str(exc),
                    "ts": time.time(),
                },
            )

    # Always sweep junk-only husks after ops; inventory skips .DS_Store.
    husk_report = sweep_leftover_husks(voice_root)
    summary = {
        "run_id": run_id,
        "applied": applied,
        "skipped": skipped,
        "errors": errors,
        "husk_sweep": husk_report,
    }
    (rdir / "apply-summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def undo_run(voice_root: Path, run_id: str) -> dict[str, Any]:
    """Reverse successful move/quarantine/flatten ops from the ledger."""
    refs = references_dir(voice_root)
    rdir = run_dir(voice_root, run_id)
    ledger_path = rdir / "ledger.jsonl"
    if not ledger_path.is_file():
        raise FileNotFoundError(f"missing ledger: {ledger_path}")
    rows = [
        json.loads(line)
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    # Reverse only ok mutations that relocated a file.
    ok_ops = [
        r
        for r in rows
        if r.get("status") == "ok"
        and (r.get("op") or {}).get("kind") in ("move", "quarantine", "flatten")
    ]
    undone = 0
    errors: list[str] = []
    for row in reversed(ok_ops):
        op = row["op"]
        src = Path(op["src"])
        dest = Path(op["dest"])
        try:
            _refuse_if_protected([src, dest], refs, voice_root)
            if dest.exists() and not src.exists():
                _ensure_parent(src)
                shutil.move(str(dest), str(src))
                undone += 1
                _append_ledger(
                    rdir,
                    {
                        "status": "undone",
                        "op": op,
                        "ts": time.time(),
                    },
                )
            elif src.exists():
                _append_ledger(
                    rdir,
                    {
                        "status": "undo_skipped",
                        "op": op,
                        "detail": "src_already_present",
                        "ts": time.time(),
                    },
                )
            else:
                errors.append(f"cannot undo missing dest: {dest}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"undo {dest} -> {src}: {exc}")
    summary = {"run_id": run_id, "undone": undone, "errors": errors}
    (rdir / "undo-summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def _parse_cleanup_argv(argv: list[str]) -> tuple[str, dict[str, str], list[str]]:
    """Parse `cleanup <sub> [--run ID] [args…]`."""
    if not argv:
        return "", {}, []
    sub = argv[0]
    flags: dict[str, str] = {}
    rest: list[str] = []
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--run" and i + 1 < len(argv):
            flags["run"] = argv[i + 1]
            i += 2
            continue
        if a.startswith("--run="):
            flags["run"] = a.split("=", 1)[1]
            i += 1
            continue
        rest.append(a)
        i += 1
    return sub, flags, rest


def cli_cleanup(argv: list[str], voice_root: Path | None = None) -> int:
    """CLI entry for `voicectl cleanup …`. Returns process exit code."""
    root = voice_root or voice_core.VOICE_ROOT
    sub, flags, _rest = _parse_cleanup_argv(argv)
    if sub in ("", "-h", "--help") or sub not in (
        "inventory",
        "plan",
        "apply",
        "undo",
        "sweep",
    ):
        print(
            "usage: voicectl cleanup inventory|plan|apply|undo|sweep [--run ID]",
            file=sys.stderr,
        )
        return 2
    try:
        if sub == "inventory":
            rid = flags.get("run") or new_run_id()
            report = build_inventory(root, rid)
            print(json.dumps(asdict(report), indent=2))
            print(f"run_id={rid}", file=sys.stderr)
            return 0
        if sub == "plan":
            rid = flags.get("run")
            if not rid:
                # Inventory first when no run supplied.
                rid = new_run_id()
                build_inventory(root, rid)
            elif not (run_dir(root, rid) / "hash-index.sqlite").is_file():
                build_inventory(root, rid)
            plan = build_plan(root, rid)
            # Compact stdout: omit full ops list for readability; path on disk.
            summary = {
                k: plan[k]
                for k in (
                    "run_id",
                    "created_at",
                    "op_count",
                    "by_kind",
                    "reclaimable_bytes_planned",
                )
            }
            summary["plan_path"] = str(run_dir(root, rid) / "plan.json")
            print(json.dumps(summary, indent=2))
            return 0
        if sub == "apply":
            rid = flags.get("run")
            if not rid:
                print("cleanup apply requires --run ID", file=sys.stderr)
                return 2
            summary = apply_plan(root, rid)
            print(json.dumps(summary, indent=2))
            return 0 if not summary.get("errors") else 1
        if sub == "undo":
            rid = flags.get("run")
            if not rid:
                print("cleanup undo requires --run ID", file=sys.stderr)
                return 2
            summary = undo_run(root, rid)
            print(json.dumps(summary, indent=2))
            return 0 if not summary.get("errors") else 1
        if sub == "sweep":
            print(json.dumps(sweep_leftover_husks(root), indent=2))
            return 0
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        print(f"cleanup {sub} failed: {exc}", file=sys.stderr)
        return 1
    return 2
