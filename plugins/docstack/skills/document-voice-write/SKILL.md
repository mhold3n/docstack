---
name: document-voice-write
description: "Gate authored prose through plugin-docstack-voice. Call before drafting and before finishing docs, chat prose, PR bodies, or commit messages. Fail closed when the voice MCP is missing or the corpus is empty."
disable-model-invocation: true
---

# Voice write

Own the voice MCP gate for writing. Callers name this skill. They do not restate tool names or the fail-closed rule.

Namespace: `plugin-docstack-voice`.

## Before you draft

1. Call `get_voice_profile` on `plugin-docstack-voice`.
2. If the namespace is missing, or the profile reports `empty: true`, or the call errors, stop. Point the user at `/document-setup-voice`. Do not draft.
3. Apply `conditioning_brief` (and note `corpus_version`) for the rest of the write. Do not skip this step because `sessionStart` already injected a brief.

Do not call `ensure_voice_corpus` unless the profile is empty and the user asked to rebuild.

## After you have an artifact

- When you have a file path, call `review_file` on that path so the corpus can score the saved prose.
- When the artifact is a chat reply, a PR body, or a commit message with no path, call `review_text` on the final text.

If the review returns block-severity findings, fix them and review again, or stop and report. Soft-skip is not allowed.

## Scope

Use this gate for authored prose under document-mode, document-technical-writing, and document-unslop. Skip it for code cleanup passes such as `/deslop`, which change source rather than house prose.
