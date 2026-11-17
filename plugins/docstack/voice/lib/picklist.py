#!/usr/bin/env python3
"""Phase-0 convert picklist: Max-authored PDF/DOCX queue for Marker.

Agent note: schedules Marker batches from cheap text plus the path-tier prior.
Does not convert, promote, park, or edit authorship.rules. One public build,
one public load, one public render. Batch JSON is an internal cache.
Judges emit disposition+shared only; urgency and rank are shell-derived.
"""

from __future__ import annotations

import enum
import hashlib
import json
import os
import re
import subprocess
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import marker_runtime
import tracing
import voice_core

__all__ = [
    "build_picklist",
    "load_picklist",
    "render_picklist",
    "render_picklist_paths",
    "render_picklist_json",
    "Picklist",
    "PickRow",
    "RowKind",
    "Urgency",
]

# Bump when the judge prompt changes. Salted into batch_id.
_RUBRIC_VERSION = "1"
# Files that share a parent directory share a judge call, in name order.
_BATCH_SIZE = 6
# First-page budget per file inside one judge call.
_EXTRACT_CHARS = 1200
_REASON_MAX = 280
_WORKERS = 4


class RowKind(enum.StrEnum):
    """What the merged row means. Closed set.

    BATCH / NOT_MAX come from a judge. ABSTAIN is judge omission, empty
    extract, or a judge error (errors are not cached). CONVERTED is assigned
    by the shell when marker_runtime.cached_excerpt hits status ok; a judge
    is not asked, and a judge payload cannot select this kind.
    """

    BATCH = "batch"
    NOT_MAX = "not_max"
    ABSTAIN = "abstain"
    CONVERTED = "converted"


class Urgency(enum.IntEnum):
    """Convert order among BATCH rows only. Derived, never stored by the judge.

    RESCUE: body says Max, path prior is not candidate (library, review, default).
    CONFIRM: body says Max, path prior is already candidate, shared is false.
    MIXED: body says Max and shared is true (group writeup or partial prose).
    Lower sorts first.
    """

    RESCUE = 0
    CONFIRM = 1
    MIXED = 2


class _ExtractKind(enum.StrEnum):
    MARKER_CACHE = "marker_cache"
    PDFTOTEXT = "pdftotext"
    DOCX_XML = "docx_xml"
    NONE = "none"


@dataclass(frozen=True)
class _PathPrior:
    """Snapshot of classify_authorship for one path. Not written back."""

    suggested_tier: str
    rule_id: str


@dataclass(frozen=True)
class _CheapExtract:
    kind: _ExtractKind
    text: str
    sha256: str


@dataclass(frozen=True)
class _SourceCard:
    """One file as the judge sees it. Built before any agent runs."""

    path: Path
    size: int
    mtime_ns: int
    prior: _PathPrior
    extract: _CheapExtract


@dataclass(frozen=True)
class _Batch:
    """Disjoint directory window. Identity is batch_id."""

    batch_id: str
    cards: tuple[_SourceCard, ...]


@dataclass(frozen=True)
class _JudgeFact:
    """Boundary type. Parser output. No rank, no Marker fields."""

    path: Path
    kind: RowKind  # BATCH, NOT_MAX, or ABSTAIN only
    shared: bool
    reason: str


@dataclass(frozen=True)
class PickRow:
    """One line of the picklist. rank is 1-based inside BATCH, else None."""

    path: Path
    kind: RowKind
    urgency: Urgency | None
    rank: int | None
    reason: str
    prior_tier: str
    prior_rule: str
    extract_kind: str

    def __post_init__(self) -> None:
        batch = self.kind is RowKind.BATCH
        if batch != (self.urgency is not None) or batch != (self.rank is not None):
            raise ValueError("urgency and rank are set exactly on batch rows")
        if self.kind is RowKind.CONVERTED and self.reason != "extraction cache hit":
            raise ValueError("converted rows are shell-authored")


@dataclass(frozen=True)
class Picklist:
    """Merged result. rows are the single sequence; views below are filters.

    Order: BATCH by (urgency, path), then NOT_MAX by path, then ABSTAIN by
    path, then CONVERTED by path.
    """

    rows: tuple[PickRow, ...]

    def batch_paths(self) -> tuple[Path, ...]:
        """Default convert queue: rescue then confirm. Mixed is separate."""
        return tuple(
            r.path
            for r in self.rows
            if r.kind is RowKind.BATCH
            and r.urgency in (Urgency.RESCUE, Urgency.CONFIRM)
        )

    def mixed_paths(self) -> tuple[Path, ...]:
        """Shared/group Max rows — review, not the default convert queue."""
        return tuple(
            r.path
            for r in self.rows
            if r.kind is RowKind.BATCH and r.urgency is Urgency.MIXED
        )

    def excluded_paths(self) -> tuple[Path, ...]:
        """Explicitly not Max-authored. Abstain is not an exclusion."""
        return tuple(r.path for r in self.rows if r.kind is RowKind.NOT_MAX)

    def disagreements(self) -> tuple[PickRow, ...]:
        """Prior tier and body verdict disagree.

        Includes rescue, mixed whose prior was not candidate, and not_max
        whose prior was candidate.
        """
        out: list[PickRow] = []
        for row in self.rows:
            if row.kind is RowKind.BATCH and row.urgency is Urgency.RESCUE:
                out.append(row)
            elif (
                row.kind is RowKind.BATCH
                and row.urgency is Urgency.MIXED
                and row.prior_tier != "candidate"
            ):
                out.append(row)
            elif row.kind is RowKind.NOT_MAX and row.prior_tier == "candidate":
                out.append(row)
        return tuple(out)


_RUBRIC = """
You decide whether Max Holden authored each file, so a human can choose what
to run through Marker later. You do not convert, and you do not suggest
Marker flags, OCR settings, or promote.

Each batch is one directory window. Use siblings: a rubric or datasheet next
to a writeup is evidence about the writeup, not a reason to mark the rubric
as his. Filename rules already ran. Their tier is a hint and is often wrong.
Known misses: names matching "copy of" land in library before a Holden match;
Takeout school folders often match no school needle; "group" is only reached
when an earlier lab/report rule did not fire; "Holden" in a manual, datasheet,
or SSL note is not authorship. Bylines and first-person lab prose are in the
extract. When the extract has real prose, do not decide from the filename.

False-positive exemplars (not Max for voice training): Knight physics /
"physics for scientists", student manuals, safety data sheets, SSL certificates,
.ipt CAD, solution manuals, instruction sheets, blank templates, syllabi,
guidelines, handouts "for students".

For each path you were given, return one object with keys path, disposition
(batch|not_max|abstain), shared (bool), and reason (one sentence).
Wrap them as {"judgments": [...]}.

batch: the prose is his (solo lab, proposal, notes). Set shared true when the
file is a group writeup or a template that only partly contains his prose.
not_max: syllabus, guidelines, manuals, datasheets, another author, a blank
form, even if the hint says candidate.
abstain: the extract is too thin to tell (cover sheet only, or almost no text).
Do not guess those from the filename. Do not add paths. Do not omit paths.
""".strip()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _picklist_dir(root: Path) -> Path:
    d = root / ".cache" / "picklist"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _batches_dir(root: Path) -> Path:
    d = _picklist_dir(root) / "batches"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _latest_path(root: Path) -> Path:
    return _picklist_dir(root) / "latest.json"


def _urgency(kind: RowKind, prior_tier: str, shared: bool) -> Urgency | None:
    """Sole map from (verdict, prior, shared) to convert order."""
    if kind is not RowKind.BATCH:
        return None
    if shared:
        return Urgency.MIXED
    if prior_tier == "candidate":
        return Urgency.CONFIRM
    return Urgency.RESCUE


def _batch_id(cards: tuple[_SourceCard, ...]) -> str:
    """Stable id from rubric + card identity (path, size, mtime, extract, prior)."""
    parts: list[str] = [_RUBRIC_VERSION]
    for card in cards:
        parts.append(
            "|".join(
                [
                    str(card.path.resolve()),
                    str(card.size),
                    str(card.mtime_ns),
                    card.extract.sha256,
                    card.prior.rule_id,
                ]
            )
        )
    return _sha256_text("\n".join(parts))


def _partition(cards: list[_SourceCard]) -> list[_Batch]:
    """Group by parent directory, sort by name, cut disjoint windows of _BATCH_SIZE.

    A one-file directory is its own batch. Directories are not packed together.
    """
    by_parent: dict[Path, list[_SourceCard]] = {}
    for card in cards:
        by_parent.setdefault(card.path.parent, []).append(card)
    batches: list[_Batch] = []
    for parent in sorted(by_parent.keys(), key=lambda p: str(p)):
        ordered = sorted(by_parent[parent], key=lambda c: c.path.name.lower())
        for i in range(0, len(ordered), _BATCH_SIZE):
            window = tuple(ordered[i : i + _BATCH_SIZE])
            batches.append(_Batch(batch_id=_batch_id(window), cards=window))
    return batches


def _cached_excerpt_or_local(path: Path, voice_root: Path) -> _CheapExtract:
    """Cheap text for one file. Never calls convert_file.

    Order: ok Marker excerpt → pdftotext pages 1–2 → DOCX document.xml → NONE.
    """
    excerpt = marker_runtime.cached_excerpt(voice_root, path, _EXTRACT_CHARS)
    if excerpt:
        return _CheapExtract(
            kind=_ExtractKind.MARKER_CACHE,
            text=excerpt,
            sha256=_sha256_text(excerpt),
        )
    suf = path.suffix.lower()
    if suf == ".pdf":
        text = _pdftotext_head(path)
        if text:
            return _CheapExtract(
                kind=_ExtractKind.PDFTOTEXT,
                text=text[:_EXTRACT_CHARS],
                sha256=_sha256_text(text[:_EXTRACT_CHARS]),
            )
    elif suf == ".docx":
        text = _docx_xml_head(path)
        if text:
            return _CheapExtract(
                kind=_ExtractKind.DOCX_XML,
                text=text[:_EXTRACT_CHARS],
                sha256=_sha256_text(text[:_EXTRACT_CHARS]),
            )
    return _CheapExtract(kind=_ExtractKind.NONE, text="", sha256=_sha256_text(""))


def _pdftotext_head(path: Path) -> str:
    """Pages 1–2 via pdftotext; empty on missing binary or failure."""
    bin_ = os.environ.get("PDFTOTEXT_BIN") or "pdftotext"
    try:
        proc = subprocess.run(
            [bin_, "-f", "1", "-l", "2", "-layout", "-enc", "UTF-8", str(path), "-"],
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
    """Plain text from word/document.xml; empty on failure."""
    try:
        with zipfile.ZipFile(path) as zf:
            raw = zf.read("word/document.xml")
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


def _parse_judgments(
    data: dict[str, Any], allowed: set[Path]
) -> dict[Path, _JudgeFact]:
    """Parse judge JSON into facts; drop paths outside the batch."""
    raw = data.get("judgments")
    if not isinstance(raw, list):
        raise RuntimeError("judge JSON missing judgments list")
    allowed_by_str = {str(p.resolve()): p for p in allowed}
    facts: dict[Path, _JudgeFact] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        path_s = str(item.get("path") or "")
        if not path_s:
            continue
        try:
            resolved = str(Path(path_s).resolve())
        except OSError:
            resolved = path_s
        path = allowed_by_str.get(resolved) or allowed_by_str.get(path_s)
        if path is None:
            continue
        disp = str(item.get("disposition") or "").strip().lower()
        if disp == "batch":
            kind = RowKind.BATCH
        elif disp in ("not_max", "not-max", "not_authored"):
            kind = RowKind.NOT_MAX
        elif disp == "abstain":
            kind = RowKind.ABSTAIN
        else:
            continue
        shared = bool(item.get("shared")) if kind is RowKind.BATCH else False
        reason = str(item.get("reason") or "").strip()[:_REASON_MAX]
        facts[path] = _JudgeFact(path=path, kind=kind, shared=shared, reason=reason)
    return facts


def _load_or_judge(
    batch: _Batch, voice_root: Path, cfg: dict[str, Any]
) -> list[_JudgeFact]:
    """Return facts for every card in the batch.

    Cache hit: parse the batch file and re-check the path set. Cache miss:
    voice_core.cursor_json once (Cursor agent ask mode). Omitted cards become
    ABSTAIN. Judge errors raise to the caller (caller records ABSTAIN and does
    not write the file).
    """
    batch_path = _batches_dir(voice_root) / f"{batch.batch_id}.json"
    allowed = {c.path for c in batch.cards}
    if batch_path.is_file():
        try:
            cached = json.loads(batch_path.read_text(encoding="utf-8"))
            facts = _parse_judgments(cached, allowed)
            cached_paths = {str(Path(p).resolve()) for p in (cached.get("paths") or [])}
            expected = {str(c.path.resolve()) for c in batch.cards}
            if cached_paths == expected and len(facts) == len(batch.cards):
                return [facts[c.path] for c in batch.cards]
            batch_path.unlink(missing_ok=True)
        except (json.JSONDecodeError, OSError, RuntimeError, KeyError, TypeError):
            batch_path.unlink(missing_ok=True)

    # Build user payload: one card per file.
    card_blocks: list[str] = []
    for card in batch.cards:
        card_blocks.append(
            "\n".join(
                [
                    f"path: {card.path}",
                    f"prior_tier: {card.prior.suggested_tier}",
                    f"prior_rule: {card.prior.rule_id}",
                    f"extract:\n{card.extract.text}",
                ]
            )
        )
    prompt = (
        'Judge each file below. Return JSON {"judgments": [...]}.\n\n'
        + "\n\n---\n\n".join(card_blocks)
    )
    # Trace input lists paths and priors. Extracts stay on the generation,
    # which is the prompt the Cursor agent received.
    trace_input = {
        "batch_id": batch.batch_id,
        "cards": [
            {
                "path": str(card.path),
                "prior_tier": card.prior.suggested_tier,
                "prior_rule": card.prior.rule_id,
                "extract_chars": len(card.extract.text),
            }
            for card in batch.cards
        ],
    }
    with tracing.operation(
        name="judge-picklist",
        feature="picklist-judge",
        input=trace_input,
        version=_RUBRIC_VERSION,
        metadata={"provider": "cursor-agent"},
    ) as span:
        data = voice_core.cursor_json(
            prompt,
            cfg,
            _RUBRIC,
            workspace=voice_root,
            agent_name="judge-authorship",
        )
        facts = _parse_judgments(data, allowed)
        out: list[_JudgeFact] = []
        for card in batch.cards:
            fact = facts.get(card.path)
            if fact is None:
                fact = _JudgeFact(
                    path=card.path,
                    kind=RowKind.ABSTAIN,
                    shared=False,
                    reason="omitted by judge",
                )
            out.append(fact)
        payload = {
            "batch_id": batch.batch_id,
            "paths": [str(c.path.resolve()) for c in batch.cards],
            "judgments": [
                {
                    "path": str(f.path),
                    "disposition": f.kind.value,
                    "shared": f.shared,
                    "reason": f.reason,
                }
                for f in out
            ],
        }
        span.update(output={"judgments": payload["judgments"]})
        voice_core.atomic_write_json(batch_path, payload)
        return out


def _merge(cards: list[_SourceCard], facts_by_path: dict[Path, _JudgeFact]) -> Picklist:
    """Pure. Every eligible card appears once. Urgency via _urgency."""
    # Agent note: BATCH rows need rank at construction; collect drafts first.
    drafts: list[tuple[Path, RowKind, Urgency | None, str, str, str, str]] = []
    seen: set[Path] = set()
    for card in cards:
        key = card.path.resolve()
        if key in seen:
            raise ValueError(f"duplicate path in merge: {card.path}")
        seen.add(key)
        prior_tier = card.prior.suggested_tier
        prior_rule = card.prior.rule_id
        extract_kind = card.extract.kind.value
        if card.extract.kind is _ExtractKind.MARKER_CACHE:
            drafts.append(
                (
                    card.path,
                    RowKind.CONVERTED,
                    None,
                    "extraction cache hit",
                    prior_tier,
                    prior_rule,
                    extract_kind,
                )
            )
            continue
        if card.extract.kind is _ExtractKind.NONE:
            drafts.append(
                (
                    card.path,
                    RowKind.ABSTAIN,
                    None,
                    "empty extract",
                    prior_tier,
                    prior_rule,
                    extract_kind,
                )
            )
            continue
        fact = facts_by_path.get(card.path)
        if fact is None:
            drafts.append(
                (
                    card.path,
                    RowKind.ABSTAIN,
                    None,
                    "missing judge fact",
                    prior_tier,
                    prior_rule,
                    extract_kind,
                )
            )
            continue
        urg = _urgency(fact.kind, prior_tier, fact.shared)
        drafts.append(
            (
                card.path,
                fact.kind,
                urg,
                fact.reason or "",
                prior_tier,
                prior_rule,
                extract_kind,
            )
        )

    batch_drafts = [d for d in drafts if d[1] is RowKind.BATCH]
    batch_drafts.sort(
        key=lambda d: (
            int(d[2]) if d[2] is not None else 99,
            str(d[0]).lower(),
        )
    )
    rank_by_path = {d[0]: i for i, d in enumerate(batch_drafts, start=1)}

    kind_order = {
        RowKind.BATCH: 0,
        RowKind.NOT_MAX: 1,
        RowKind.ABSTAIN: 2,
        RowKind.CONVERTED: 3,
    }
    final: list[PickRow] = []
    for path, kind, urg, reason, prior_tier, prior_rule, extract_kind in drafts:
        rank = rank_by_path.get(path) if kind is RowKind.BATCH else None
        final.append(
            PickRow(
                path=path,
                kind=kind,
                urgency=urg,
                rank=rank,
                reason=reason,
                prior_tier=prior_tier,
                prior_rule=prior_rule,
                extract_kind=extract_kind,
            )
        )
    final.sort(
        key=lambda r: (
            kind_order[r.kind],
            int(r.urgency) if r.urgency is not None else 99,
            str(r.path).lower(),
        )
    )
    return Picklist(rows=tuple(final))


def _row_to_dict(row: PickRow) -> dict[str, Any]:
    return {
        "path": str(row.path),
        "kind": row.kind.value,
        "urgency": row.urgency.name.lower() if row.urgency is not None else None,
        "rank": row.rank,
        "reason": row.reason,
        "prior_tier": row.prior_tier,
        "prior_rule": row.prior_rule,
        "extract_kind": row.extract_kind,
    }


def _row_from_dict(data: dict[str, Any]) -> PickRow:
    kind = RowKind(str(data["kind"]))
    urg_s = data.get("urgency")
    urgency = Urgency[str(urg_s).upper()] if urg_s else None
    return PickRow(
        path=Path(str(data["path"])),
        kind=kind,
        urgency=urgency,
        rank=data.get("rank"),
        reason=str(data.get("reason") or ""),
        prior_tier=str(data.get("prior_tier") or ""),
        prior_rule=str(data.get("prior_rule") or ""),
        extract_kind=str(data.get("extract_kind") or ""),
    )


def build_picklist(roots: list[Path], root: Path | None = None) -> Picklist:
    """Walk dumps, judge directory batches in parallel, merge, write latest.json.

    Does not convert or promote. Holds the picklist lock for the whole call.
    """
    voice_root = root or voice_core.VOICE_ROOT
    cfg = voice_core.load_config(voice_root)
    lock_path = _picklist_dir(voice_root) / "lock"
    with voice_core.FileLock(lock_path, timeout=600.0):
        triage_rows = voice_core.triage_paths(roots, cfg)
        cards: list[_SourceCard] = []
        for row in triage_rows:
            if row.get("suggested_tier") == "skip":
                continue
            ext = str(row.get("ext") or "").lower()
            if ext not in marker_runtime.CONVERT_SUFFIXES:
                continue
            path = Path(str(row["path"]))
            if not path.is_file():
                continue
            try:
                st = path.stat()
            except OSError:
                continue
            extract = _cached_excerpt_or_local(path, voice_root)
            cards.append(
                _SourceCard(
                    path=path,
                    size=int(st.st_size),
                    mtime_ns=int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))),
                    prior=_PathPrior(
                        suggested_tier=str(row.get("suggested_tier") or "review"),
                        rule_id=str(row.get("rule_id") or "default"),
                    ),
                    extract=extract,
                )
            )

        # Already-converted and empty-extract cards skip the judge pool.
        judge_cards = [
            c
            for c in cards
            if c.extract.kind not in (_ExtractKind.MARKER_CACHE, _ExtractKind.NONE)
        ]
        batches = _partition(judge_cards)
        facts_by_path: dict[Path, _JudgeFact] = {}

        def _safe_judge(batch: _Batch) -> list[_JudgeFact]:
            try:
                return _load_or_judge(batch, voice_root, cfg)
            except Exception as exc:
                # Agent note: errors are not cached; next run retries Cursor.
                return [
                    _JudgeFact(
                        path=c.path,
                        kind=RowKind.ABSTAIN,
                        shared=False,
                        reason=f"judge error: {exc}"[:_REASON_MAX],
                    )
                    for c in batch.cards
                ]

        if batches:
            with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
                futs = {pool.submit(_safe_judge, b): b for b in batches}
                for fut in as_completed(futs):
                    for fact in fut.result():
                        facts_by_path[fact.path] = fact

        picklist = _merge(cards, facts_by_path)
        voice_core.atomic_write_json(
            _latest_path(voice_root),
            {
                "rubric_version": _RUBRIC_VERSION,
                "rows": [_row_to_dict(r) for r in picklist.rows],
            },
        )
        return picklist


def load_picklist(root: Path | None = None) -> Picklist:
    """Read latest.json. Does not judge and does not read batch files."""
    voice_root = root or voice_core.VOICE_ROOT
    path = _latest_path(voice_root)
    if not path.is_file():
        raise FileNotFoundError(f"no picklist at {path}; run voicectl picklist")
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = tuple(_row_from_dict(r) for r in (data.get("rows") or []))
    return Picklist(rows=rows)


def render_picklist(picklist: Picklist) -> str:
    """Markdown view of picklist.rows. Derived; not a second store."""
    lines: list[str] = ["# Voice convert picklist", ""]
    sections: list[tuple[str, list[PickRow]]] = [
        (
            "Batch (rescue then confirm)",
            [
                r
                for r in picklist.rows
                if r.kind is RowKind.BATCH
                and r.urgency in (Urgency.RESCUE, Urgency.CONFIRM)
            ],
        ),
        (
            "Mixed (shared / group — review before convert)",
            [
                r
                for r in picklist.rows
                if r.kind is RowKind.BATCH and r.urgency is Urgency.MIXED
            ],
        ),
        (
            "Not Max-authored",
            [r for r in picklist.rows if r.kind is RowKind.NOT_MAX],
        ),
        ("Abstain", [r for r in picklist.rows if r.kind is RowKind.ABSTAIN]),
        (
            "Already converted",
            [r for r in picklist.rows if r.kind is RowKind.CONVERTED],
        ),
    ]
    for title, rows in sections:
        lines.append(f"## {title}")
        lines.append("")
        if not rows:
            lines.append("(none)")
            lines.append("")
            continue
        for row in rows:
            urg = row.urgency.name.lower() if row.urgency is not None else "-"
            rank = row.rank if row.rank is not None else "-"
            lines.append(
                f"- [{rank}] ({urg}) `{row.path}` "
                f"prior={row.prior_tier}/{row.prior_rule} — {row.reason}"
            )
        lines.append("")
    lines.append("## Disagreements (path prior vs body)")
    lines.append("")
    disag = picklist.disagreements()
    if not disag:
        lines.append("(none)")
    else:
        for row in disag:
            lines.append(
                f"- `{row.path}` kind={row.kind.value} "
                f"prior={row.prior_tier}/{row.prior_rule} — {row.reason}"
            )
    lines.append("")
    return "\n".join(lines)


def render_picklist_paths(picklist: Picklist) -> str:
    """One absolute path per line: default convert queue only."""
    return "".join(f"{p}\n" for p in picklist.batch_paths())


def render_picklist_json(picklist: Picklist) -> str:
    """Machine-readable view of the same Picklist (counts + rows)."""
    counts: dict[str, int] = {}
    for row in picklist.rows:
        counts[row.kind.value] = counts.get(row.kind.value, 0) + 1
    payload = {
        "counts": counts,
        "batch_paths": [str(p) for p in picklist.batch_paths()],
        "mixed_paths": [str(p) for p in picklist.mixed_paths()],
        "excluded_paths": [str(p) for p in picklist.excluded_paths()],
        "rows": [_row_to_dict(r) for r in picklist.rows],
    }
    return json.dumps(payload, indent=2) + "\n"
