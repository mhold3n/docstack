#!/usr/bin/env python3
"""Minimal stdio MCP server for dynamic voice corpus (voicectl wrappers).

Agent note: framing lives in ``stdio_rpc`` (NDJSON for Cursor + Content-Length
for acceptance). Never print diagnostics on stdout.

Corpus root is ``CURSOR_VOICE_ROOT`` (default ``~/.cursor/voice``), not the
plugin install path beside this file. Runtime code lives under the plugin;
user references/caches stay at VoiceRoot.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Agent note: VoiceRuntime = parents[1] (…/voice). Corpus = voice_core.VOICE_ROOT.
VOICE_RUNTIME = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(VOICE_RUNTIME / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import stdio_rpc  # noqa: E402
import voice_core  # noqa: E402

# Env-backed corpus home. Never Path(__file__).parents[1] after the plugin move.
ROOT = voice_core.VOICE_ROOT

TOOLS = [
    {
        "name": "get_voice_profile",
        "description": "Return the current cached voice profile (ensures freshness).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "ensure_voice_corpus",
        "description": "Rebuild voice profile if the reference corpus changed.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "review_file",
        "description": "Review a prose file against the voice profile.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "review_text",
        "description": "Review raw text against the voice profile.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": ["text"],
        },
    },
]


def handle_tool(name: str, args: dict) -> Any:
    if name == "get_voice_profile":
        return voice_core.ensure_profile(ROOT)
    if name == "ensure_voice_corpus":
        p = voice_core.ensure_profile(ROOT)
        return {"corpus_version": p.get("corpus_version"), "empty": p.get("empty")}
    if name == "review_file":
        return voice_core.review_file(Path(args["path"]), ROOT)
    if name == "review_text":
        return voice_core.review_text(
            args["text"], path=args.get("path") or "<stdin>", root=ROOT
        )
    raise ValueError(f"unknown tool {name}")


def main() -> None:
    while True:
        msg = stdio_rpc.read_message()
        if msg is None:
            break
        mid = msg.get("id")
        method = msg.get("method")
        if method == "initialize":
            # Echo client's protocolVersion when present so Cursor's 2025-11-25
            # handshake matches; fall back to the classic MCP date.
            params = msg.get("params") or {}
            protocol = params.get("protocolVersion") or "2024-11-05"
            stdio_rpc.write_message(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {
                        "protocolVersion": protocol,
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "voice", "version": "1.0.0"},
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
