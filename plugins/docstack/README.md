# docstack

If you want to go fast, go deep first.

docstack is a docs/PDF twin of [pstack](https://github.com/cursor/plugins/tree/main/pstack): playbook-driven agent workflows for markdown, documentation sites, and PDFs. Throughput without quality is not the goal. One rigorous agent makes N agents safe.

## Icons

`assets/logo.png` is the plugin logo (`logo` in `.cursor-plugin/plugin.json`).

- **Customize card** — works for local installs (`~/.cursor/plugins/local/docstack`).
- **`/` slash skill rows** — Cursor resolves relative logos to `raw.githubusercontent.com` (repo + commit). That needs a GitHub / marketplace install, not a local folder. Local installs keep the generic cube.
- **Custom Mode badge** — skill `icon` / `color` (`book-open` / `blue` on docs-mode, setup, help).

To get the book on `/`, import this repo as a team marketplace (or install after marketplace listing), then prefer that install over the local copy (same name: marketplace wins).

## Front door

```
/docs-mode <goal> — done when <checkable predicate>
```

`/docs-mode` matches a playbook and copies its steps into todos. It routes skills as steps need them. Core routes include `architect`, `arena`, `swarm`, and `interrogate`. Prose and PDF routes include `voice-write`, `unslop`, `technical-writing`, and `pdf`. Large or unattended work with no fit falls through to `/figure-it-out`.

## Setup

```
/setup-docstack
```

Detects available Task models, picks a reasoning budget, and writes `~/.cursor/rules/docstack-models.mdc`. Every docs role (chapter, fact-fix, edit, arena panel) then has an explicit model.


## Voice MCP

Dynamic voice review ships in this plugin (`voice/` + root `mcp.json`).

| Piece | Location |
|-------|----------|
| Runtime (MCP, `voicectl`, lib) | plugin `voice/` |
| Corpus / cache / config | `~/.cursor/voice` (`CURSOR_VOICE_ROOT`) |

After install, run `/setup-voice` (or `scripts/run-voice-mcp.sh` once) so the plugin venv exists. Remove any user-level `voice` entry from `~/.cursor/mcp.json` to avoid a duplicate `user-voice` server. Marker convert stays on the user `marker` MCP for now.

Authored prose under docs-mode, technical-writing, and unslop must call `/voice-write`, which gates on `plugin-docstack-voice` (`get_voice_profile` before draft, `review_file` / `review_text` before done). Fail closed if that namespace is missing.

## Help

```
/docstack-help
```

Routing map for humans. Does not start expensive work.

## What “done” means

Prove it on the real artifact:

- **Markdown / docs site** — render or preview, link check, style lint, examples that run when the project has them
- **PDF** — generate, then visually review pages (`pdftoppm` / Poppler), not text extraction alone

## Make it yours

`/automate-me` drafts a personal `-mode` skill from how you actually work. `/reflect` proposes skill edits from this transcript. `/correct` encodes repeated mistakes so they cannot recur.

## License

MIT. Adapted from pstack (Lauren Tan / poteto).
