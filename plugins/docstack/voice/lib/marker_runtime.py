#!/usr/bin/env python3
"""Marker conversion runtime for voice corpus materialization.

Agent note: sole owner of Marker invocation, extraction cache, and quality gates.
Callers (voicectl convert, marker MCP) must not shell to marker_single themselves.
Default conversion never enables --use_llm; fidelity over reconstruction.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any

# Convertible binary references (active corpus stays md/txt after materialize).
CONVERT_SUFFIXES = {".pdf", ".docx"}


def _sha256_bytes(data: bytes) -> str:
    """Content-address key for source bytes and markdown bodies."""
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def marker_settings(cfg: dict[str, Any]) -> dict[str, Any]:
    """Normalize marker config with defaults used for CLI argv and cache keys."""
    m = dict(cfg.get("marker") or {})
    root = Path(os.environ.get("CURSOR_VOICE_ROOT", Path.home() / ".cursor" / "voice"))
    default_py = root / "vendor" / "marker" / ".venv" / "bin" / "python"
    m.setdefault("enabled", True)
    m.setdefault("venv_python", str(default_py))
    m.setdefault("mode", "fast")
    m.setdefault("use_llm", False)
    m.setdefault("timeout_sec", 300)
    m.setdefault("concurrency", 1)
    m.setdefault("output_dir", "references/candidates")
    m.setdefault("disable_image_extraction", True)
    return m


def settings_digest(mcfg: dict[str, Any]) -> str:
    """Stable digest of conversion settings that affect markdown output."""
    relevant = {
        "mode": mcfg.get("mode"),
        "use_llm": bool(mcfg.get("use_llm")),
        "disable_image_extraction": bool(mcfg.get("disable_image_extraction", True)),
    }
    return _sha256_text(json.dumps(relevant, sort_keys=True))


def marker_bin(mcfg: dict[str, Any]) -> Path:
    """Resolve marker_single next to the configured venv python."""
    py = Path(str(mcfg["venv_python"]))
    candidate = py.parent / "marker_single"
    if candidate.is_file():
        return candidate
    raise FileNotFoundError(f"marker_single missing beside {py}")


def marker_version(mcfg: dict[str, Any]) -> str:
    """Installed marker-pdf version string for provenance + cache invalidation."""
    py = Path(str(mcfg["venv_python"]))
    proc = subprocess.run(
        [
            str(py),
            "-c",
            "import importlib.metadata as m; print(m.version('marker-pdf'))",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"marker version probe failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def cache_key(source_sha: str, marker_ver: str, mode: str, settings_dig: str) -> str:
    """Content-addressed extraction cache key (separate from voice corpus_version)."""
    blob = f"{source_sha}|{marker_ver}|{mode}|{settings_dig}"
    return _sha256_text(blob)


def extracted_dir(root: Path) -> Path:
    d = root / ".cache" / "extracted"
    d.mkdir(parents=True, exist_ok=True)
    return d


def quality_check(markdown: str) -> tuple[str, list[str]]:
    """Gate extraction quality. Returns (ok|quarantine, warnings).

    Reject empty/near-empty bodies, extreme repeated lines (headers/footers),
    and duplicated paragraphs. Never invent replacement prose.
    """
    warnings: list[str] = []
    text = markdown.replace("\x00", "").strip()
    if len(text) < 40:
        return "quarantine", ["near_empty_body"]

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if lines:
        counts = Counter(lines)
        most_common, n = counts.most_common(1)[0]
        if n >= 5 and len(most_common) > 3:
            warnings.append("repeated_header_footer_lines")
            if n / max(1, len(lines)) > 0.35:
                return "quarantine", warnings

    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paras) >= 2:
        seen: set[str] = set()
        dup = 0
        for p in paras:
            if p in seen and len(p) > 120:
                dup += 1
            seen.add(p)
        if dup >= 3:
            warnings.append("duplicated_paragraphs")
            return "quarantine", warnings
        if dup >= 1:
            warnings.append("duplicated_paragraphs")

    return "ok", warnings


def _run_marker_single(
    source: Path, mcfg: dict[str, Any], out_dir: Path
) -> tuple[str, dict[str, Any]]:
    """Invoke marker_single; capture markdown. Logs stay on stderr."""
    bin_ = marker_bin(mcfg)
    mode = str(mcfg.get("mode") or "fast")
    argv = [
        str(bin_),
        str(source),
        "--output_dir",
        str(out_dir),
        "--output_format",
        "markdown",
        "--mode",
        mode,
    ]
    if mcfg.get("disable_image_extraction", True):
        argv.append("--disable_image_extraction")
    # Fidelity: never enable LLM rewrite unless explicitly configured.
    if mcfg.get("use_llm"):
        argv.append("--use_llm")

    timeout = int(mcfg.get("timeout_sec") or 300)
    # WeasyPrint (DOCX path) needs Homebrew dylibs on Apple Silicon.
    env = os.environ.copy()
    brew_lib = "/opt/homebrew/lib"
    prev = env.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    if brew_lib not in prev.split(":"):
        env["DYLD_FALLBACK_LIBRARY_PATH"] = f"{brew_lib}:{prev}" if prev else brew_lib
    proc = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
        env=env,
    )
    meta = {
        "argv": argv,
        "returncode": proc.returncode,
        "stderr_tail": (proc.stderr or "")[-2000:],
        "stdout_tail": (proc.stdout or "")[-500:],
    }
    if proc.returncode != 0:
        raise RuntimeError(
            f"marker_single failed ({proc.returncode}): {(proc.stderr or '')[:800]}"
        )

    md_files = sorted(out_dir.rglob("*.md"))
    if not md_files:
        raise RuntimeError(f"marker produced no markdown under {out_dir}")
    # Prefer file matching source stem.
    preferred = [p for p in md_files if p.stem == source.stem]
    md_path = preferred[0] if preferred else md_files[0]
    return md_path.read_text(encoding="utf-8", errors="replace"), meta


def load_record(root: Path, key: str) -> dict[str, Any] | None:
    path = extracted_dir(root) / f"{key}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def save_record(
    root: Path, key: str, record: dict[str, Any], markdown: str
) -> dict[str, Any]:
    """Persist markdown + provenance JSON under .cache/extracted/.

    Mutates and returns record with cache_md / cache_json paths filled.
    """
    ed = extracted_dir(root)
    md_path = ed / f"{key}.md"
    json_path = ed / f"{key}.json"
    md_path.write_text(markdown, encoding="utf-8")
    record["cache_md"] = str(md_path)
    record["cache_json"] = str(json_path)
    tmp = json_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    tmp.replace(json_path)
    return record


def convert_file(
    source: Path,
    root: Path,
    cfg: dict[str, Any],
    *,
    materialize: bool = True,
) -> dict[str, Any]:
    """Convert one PDF/DOCX via Marker; optionally write references/candidates/*.md.

    Returns ExtractionRecord-shaped dict. Quarantine/fail does not materialize.
    """
    source = source.resolve()
    if source.suffix.lower() not in CONVERT_SUFFIXES:
        raise ValueError(f"unsupported convert suffix: {source}")
    if not source.is_file():
        raise FileNotFoundError(str(source))

    mcfg = marker_settings(cfg)
    if not mcfg.get("enabled", True):
        raise RuntimeError("marker.enabled is false")

    raw = source.read_bytes()
    source_sha = _sha256_bytes(raw)
    marker_ver = marker_version(mcfg)
    sdig = settings_digest(mcfg)
    mode = str(mcfg.get("mode") or "fast")
    key = cache_key(source_sha, marker_ver, mode, sdig)

    cached = load_record(root, key)
    if (
        cached
        and cached.get("status") == "ok"
        and Path(cached.get("cache_md") or "").is_file()
    ):
        markdown = Path(cached["cache_md"]).read_text(encoding="utf-8")
        record = dict(cached)
        record["cache_hit"] = True
    else:
        with tempfile.TemporaryDirectory(prefix="marker-voice-") as td:
            out_dir = Path(td)
            try:
                markdown, run_meta = _run_marker_single(source, mcfg, out_dir)
            except Exception as exc:
                record = {
                    "key": key,
                    "source_path": str(source),
                    "source_sha256": source_sha,
                    "marker_version": marker_ver,
                    "mode": mode,
                    "settings_digest": sdig,
                    "status": "failed",
                    "warnings": [str(exc)],
                    "ocr": mode not in ("no_ocr",),
                    "use_llm": bool(mcfg.get("use_llm")),
                    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "cache_hit": False,
                }
                save_record(root, key, record, "")
                return record

        status, warnings = quality_check(markdown)
        record = {
            "key": key,
            "source_path": str(source),
            "source_sha256": source_sha,
            "marker_version": marker_ver,
            "mode": mode,
            "settings_digest": sdig,
            "status": status,
            "warnings": warnings,
            "markdown_sha256": _sha256_text(markdown),
            "ocr": mode not in ("no_ocr",),
            "use_llm": bool(mcfg.get("use_llm")),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "cache_hit": False,
            "run": run_meta,
        }
        save_record(root, key, record, markdown if status == "ok" else markdown)

    if materialize and record.get("status") == "ok":
        out_rel = str(mcfg.get("output_dir") or "references/candidates")
        out_dir = root / out_rel
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = source.stem
        dest = out_dir / f"{stem}.md"
        body = Path(record["cache_md"]).read_text(encoding="utf-8")
        if dest.is_file():
            existing = dest.read_text(encoding="utf-8")
            if _sha256_text(existing) != _sha256_text(body):
                dest = out_dir / f"{stem}-{source_sha[:8]}.md"
        dest.write_text(body, encoding="utf-8")
        record["materialized_path"] = str(dest)

    return record


def convert_paths(
    paths: list[Path], root: Path, cfg: dict[str, Any]
) -> list[dict[str, Any]]:
    """Convert many paths sequentially (concurrency reserved for future)."""
    results = []
    for p in paths:
        results.append(convert_file(p, root, cfg, materialize=True))
    return results


def doctor(root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    """Install health for Marker runtime (used by voicectl doctor / MCP)."""
    mcfg = marker_settings(cfg)
    info: dict[str, Any] = {
        "enabled": bool(mcfg.get("enabled")),
        "mode": mcfg.get("mode"),
        "use_llm": bool(mcfg.get("use_llm")),
        "venv_python": mcfg.get("venv_python"),
    }
    try:
        bin_ = marker_bin(mcfg)
        info["marker_single"] = str(bin_)
        info["marker_version"] = marker_version(mcfg)
        info["ok"] = True
    except Exception as exc:
        info["ok"] = False
        info["error"] = str(exc)
    ed = extracted_dir(root)
    info["extracted_cache_entries"] = len(list(ed.glob("*.json")))
    return info


def list_status(root: Path) -> list[dict[str, Any]]:
    """Summarize extraction cache records (quarantine/fail/ok)."""
    out = []
    for jp in sorted(extracted_dir(root).glob("*.json")):
        try:
            rec = json.loads(jp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        out.append(
            {
                "key": rec.get("key") or jp.stem,
                "status": rec.get("status"),
                "source_path": rec.get("source_path"),
                "warnings": rec.get("warnings"),
                "materialized_path": rec.get("materialized_path"),
            }
        )
    return out


def cached_excerpt(root: Path, source: Path, limit: int) -> str | None:
    """First `limit` characters of an ok cache record for this source path.

    Agent note: picklist / peek callers only. Does not run marker_single,
    does not materialize, does not change quality_check. Quarantine and
    failed records return None so the caller can fall through to pdftotext.
    When multiple ok records match, prefer the latest generated_at.
    """
    source_key = str(source.resolve())
    best: dict[str, Any] | None = None
    best_at = ""
    for jp in extracted_dir(root).glob("*.json"):
        try:
            rec = json.loads(jp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if rec.get("status") != "ok":
            continue
        rec_path = str(rec.get("source_path") or "")
        if not rec_path:
            continue
        try:
            if str(Path(rec_path).resolve()) != source_key:
                continue
        except OSError:
            if rec_path != source_key:
                continue
        generated = str(rec.get("generated_at") or "")
        if best is None or generated >= best_at:
            best = rec
            best_at = generated
    if best is None:
        return None
    md_path = Path(str(best.get("cache_md") or ""))
    if not md_path.is_file():
        return None
    try:
        text = md_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    text = text.replace("\x00", "").strip()
    if not text:
        return None
    if limit > 0 and len(text) > limit:
        return text[:limit]
    return text


def default_argv_includes_use_llm(mcfg: dict[str, Any]) -> bool:
    """Test helper: default conversion must not pass --use_llm."""
    return bool(mcfg.get("use_llm"))
