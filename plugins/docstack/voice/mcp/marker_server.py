#!/usr/bin/env python3
"""Stdio MCP server for Marker conversion (shares marker_runtime with voicectl).

Agent note: optional agent-facing interface. Routine corpus ingest uses
`voicectl convert` and does not require this process. Framing lives in
``stdio_rpc`` (NDJSON for Cursor + Content-Length for acceptance). Never write
diagnostics to stdout.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import marker_runtime  # noqa: E402
import stdio_rpc  # noqa: E402
import voice_core  # noqa: E402

TOOLS = [
    {
        "name": "marker_convert",
        "description": (
            "Convert a local PDF/DOCX to Markdown via Marker and materialize "
            "into the voice references folder when quality checks pass."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "marker_convert_batch",
        "description": "Convert a list of local PDF/DOCX paths via Marker.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                }
            },
            "required": ["paths"],
        },
    },
    {
        "name": "marker_status",
        "description": "Marker runtime version, mode, and extraction cache stats.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "marker_doctor",
        "description": "Marker install health check.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def handle_tool(name: str, args: dict) -> Any:
    cfg = voice_core.load_config(ROOT)
    if name == "marker_convert":
        return marker_runtime.convert_file(Path(args["path"]), ROOT, cfg)
    if name == "marker_convert_batch":
        paths = [Path(p) for p in (args.get("paths") or [])]
        return marker_runtime.convert_paths(paths, ROOT, cfg)
    if name == "marker_status":
        mcfg = marker_runtime.marker_settings(cfg)
        doc = marker_runtime.doctor(ROOT, cfg)
        return {
            "mode": mcfg.get("mode"),
            "use_llm": bool(mcfg.get("use_llm")),
            "marker_version": doc.get("marker_version"),
            "extracted_cache_entries": doc.get("extracted_cache_entries"),
            "records": marker_runtime.list_status(ROOT),
        }
    if name == "marker_doctor":
        return marker_runtime.doctor(ROOT, cfg)
    raise ValueError(f"unknown tool {name}")


def main() -> None:
    while True:
        msg = stdio_rpc.read_message()
        if msg is None:
            break
        mid = msg.get("id")
        method = msg.get("method")
        if method == "initialize":
            params = msg.get("params") or {}
            protocol = params.get("protocolVersion") or "2024-11-05"
            stdio_rpc.write_message(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {
                        "protocolVersion": protocol,
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "marker", "version": "1.0.0"},
                    },
                }
            )
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            stdio_rpc.write_message(
                {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
            )
        elif method == "tools/call":
            params = msg.get("params") or {}
            name = params.get("name")
            args = params.get("arguments") or {}
            try:
                result = handle_tool(name, args)
                stdio_rpc.write_message(
                    {
                        "jsonrpc": "2.0",
                        "id": mid,
                        "result": {
                            "content": [
                                {"type": "text", "text": json.dumps(result, indent=2)}
                            ]
                        },
                    }
                )
            except Exception as exc:
                print(f"marker_mcp error: {exc}", file=sys.stderr)
                stdio_rpc.write_message(
                    {
                        "jsonrpc": "2.0",
                        "id": mid,
                        "result": {
                            "isError": True,
                            "content": [{"type": "text", "text": str(exc)}],
                        },
                    }
                )
        elif method == "ping":
            stdio_rpc.write_message({"jsonrpc": "2.0", "id": mid, "result": {}})
        else:
            if mid is not None:
                stdio_rpc.write_message(
                    {
                        "jsonrpc": "2.0",
                        "id": mid,
                        "error": {"code": -32601, "message": f"unknown {method}"},
                    }
                )


if __name__ == "__main__":
    main()
