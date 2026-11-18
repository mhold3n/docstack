---
name: document-setup-voice
description: Bootstrap the docstack voice MCP runtime and link VoiceRoot (~/.cursor/voice) so stylectl and plugin-docstack-voice share one corpus.
disable-model-invocation: true
---

# Setup voice

Voice **runtime** ships in this plugin under `voice/` and holds the MCP server plus `voicectl`. Voice **corpus** stays at `~/.cursor/voice` under `CURSOR_VOICE_ROOT`, including references, cache, and config that upgrades must not replace.

## Steps

1. Ensure VoiceRoot exists with `references/active/`, `config.yaml`, and (for convert) `vendor/marker`, before you link the runtime or start the MCP server.
2. Create the plugin venv next to the shipped voice runtime:

```bash
VOICE="$(dirname "$(dirname "$0")")/../../voice"  # or resolve CURSOR_PLUGIN_ROOT/voice
# Prefer: find installed docstack plugin cache path, then:
cd "$VOICE" && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

Or run once: `bash "${CURSOR_PLUGIN_ROOT}/scripts/run-voice-mcp.sh"` (creates `.venv` on first MCP start).

3. Point style-enforcement at the plugin lib without moving the corpus off VoiceRoot:

```bash
PLUGIN_VOICE="<path-to-installed-docstack>/voice"
ln -sfn "$PLUGIN_VOICE" "$HOME/.cursor/voice/runtime"
# enforce.py resolves CURSOR_VOICE_LIB or ~/.cursor/voice/runtime/lib
```

4. Remove the user `voice` block from `~/.cursor/mcp.json` so tools come from `plugin-docstack-voice` alone. Keep the `marker` user MCP entry until Marker ships in the plugin.
5. Open a new Agent chat and confirm `plugin-docstack-voice` tools appear, then confirm `stylectl hook sessionStart` injects conditioning from the same corpus.
6. Writing work uses [`/document-voice-write`](../document-voice-write/SKILL.md) for profile before draft and review before done. document-mode, document-technical-writing, and document-unslop route through that skill after this bootstrap.
