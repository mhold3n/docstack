"""Shared stdio JSON-RPC framing for voice MCP servers.

Agent note: Cursor currently speaks newline-delimited JSON (one object + ``\\n``).
Older clients and our acceptance tests still use MCP Content-Length headers.
Detect the inbound framing from the first byte and answer in the same mode for
the rest of the process lifetime. Never write diagnostics to stdout.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Literal

# Set on first successful read; drives matching write framing.
_Framing = Literal["ndjson", "content-length"]
_framing: _Framing | None = None


def framing() -> _Framing | None:
    """Return the negotiated framing mode after the first inbound message."""
    return _framing


def read_message() -> dict[str, Any] | None:
    """Read one JSON-RPC message from stdin (NDJSON or Content-Length)."""
    global _framing
    first = sys.stdin.buffer.read(1)
    if not first:
        return None

    # Cursor / NDJSON: payload starts with '{' (or whitespace then '{').
    if first in b"{ \t\r\n":
        _framing = "ndjson"
        buf = first
        # Skip leading whitespace / blank lines until object start.
        while buf in b" \t\r\n":
            nxt = sys.stdin.buffer.read(1)
            if not nxt:
                return None
            buf = nxt
        if buf != b"{":
            raise ValueError(f"ndjson expected '{{', got {buf!r}")
        rest = sys.stdin.buffer.readline()
        return json.loads(buf + rest)

    # Classic MCP: headers begin with a letter (Content-Length: ...).
    _framing = "content-length"
    header = first
    while not header.endswith(b"\r\n\r\n"):
        chunk = sys.stdin.buffer.read(1)
        if not chunk:
            return None
        header += chunk
    length = 0
    for line in header.decode().split("\r\n"):
        if line.lower().startswith("content-length:"):
            length = int(line.split(":", 1)[1].strip())
    body = sys.stdin.buffer.read(length)
    return json.loads(body.decode())


def write_message(msg: dict[str, Any]) -> None:
    """Write one JSON-RPC message using the framing negotiated on read."""
    data = json.dumps(msg, separators=(",", ":")).encode()
    mode = _framing or "content-length"
    if mode == "ndjson":
        sys.stdout.buffer.write(data + b"\n")
    else:
        sys.stdout.buffer.write(f"Content-Length: {len(data)}\r\n\r\n".encode() + data)
    sys.stdout.buffer.flush()
