# docstack

If you want to go fast, go deep first.

docstack is a docs/PDF twin of [pstack](https://github.com/cursor/plugins/tree/main/pstack): playbook-driven agent workflows for markdown, documentation sites, and PDFs. Throughput without quality is not the goal. One rigorous agent makes N agents safe.

## Icons

`assets/logo.png` is the plugin logo (`logo` in `.cursor-plugin/plugin.json`).

- **Customize card** — works for local installs (`~/.cursor/plugins/local/docstack`).
- **`/` slash skill rows** — Cursor resolves relative logos to `raw.githubusercontent.com` (repo + commit). That needs a GitHub / marketplace install, not a local folder. Local installs keep the generic cube.
- **Custom Mode badge** — skill `icon` / `color` (`book-open` / `blue` on document-mode, document-setup, document-help).

To get the book on `/`, import this repo as a team marketplace (or install after marketplace listing), then prefer that install over the local copy (same name: marketplace wins).

## Front door

```
/document-mode <goal> — done when <checkable predicate>
```

`/document-mode` matches a playbook and copies its steps into todos. It routes skills as steps need them. Core routes include `document-architect`, `document-arena`, `document-swarm`, and `document-interrogate`. Prose and PDF routes include `document-voice-write`, `document-unslop`, `document-technical-writing`, and `document-pdf`. Large or unattended work with no fit falls through to `/document-figure-it-out`.

## Setup

```
/document-setup
```

Detects available Task models, picks a reasoning budget, and writes `~/.cursor/rules/docstack-models.mdc`. Every docs role (chapter, fact-fix, edit, arena panel) then has an explicit model.


## Voice MCP

Dynamic voice review ships in this plugin (`voice/` + root `mcp.json`).

| Piece | Location |
|-------|----------|
| Runtime (MCP, `voicectl`, lib) | plugin `voice/` |
| Corpus / cache / config | `~/.cursor/voice` (`CURSOR_VOICE_ROOT`) |

After install, run `/document-setup-voice` (or `scripts/run-voice-mcp.sh` once) so the plugin venv exists. Remove any user-level `voice` entry from `~/.cursor/mcp.json` to avoid a duplicate `user-voice` server. Marker convert stays on the user `marker` MCP for now.

Authored prose under document-mode, document-technical-writing, and document-unslop must call `/document-voice-write`, which gates on `plugin-docstack-voice` (`get_voice_profile` before draft, `review_file` / `review_text` before done). Fail closed if that namespace is missing.

## Help

```
/document-help
```

Routing map for humans. Does not start expensive work.

## What “done” means

Prove it on the real artifact:

- **Markdown / docs site** — render or preview, link check, style lint, examples that run when the project has them
- **PDF** — generate, then visually review pages (`pdftoppm` / Poppler), not text extraction alone

## Make it yours

`/document-automate-me` drafts a personal `-mode` skill from how you actually work. `/document-reflect` proposes skill edits from this transcript. `/document-correct` encodes repeated mistakes so they cannot recur.

## License

MIT. Adapted from pstack (Lauren Tan / poteto).
