#!/usr/bin/env bash
# Agent note: plugin-local voice MCP launcher. Corpus stays at VoiceRoot
# (~/.cursor/voice by default). Runtime lives under the plugin install.
set -euo pipefail
PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VOICE_RUNTIME="$PLUGIN_ROOT/voice"
export CURSOR_VOICE_ROOT="${CURSOR_VOICE_ROOT:-$HOME/.cursor/voice}"
export PYTHONUNBUFFERED=1
export PYTHONPATH="$VOICE_RUNTIME/lib${PYTHONPATH:+:$PYTHONPATH}"

PY="$VOICE_RUNTIME/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "run-voice-mcp: creating venv at $VOICE_RUNTIME/.venv" >&2
  python3 -m venv "$VOICE_RUNTIME/.venv"
  "$VOICE_RUNTIME/.venv/bin/pip" install -q -r "$VOICE_RUNTIME/requirements.txt"
  PY="$VOICE_RUNTIME/.venv/bin/python"
fi

exec "$PY" -u "$VOICE_RUNTIME/mcp/server.py"
