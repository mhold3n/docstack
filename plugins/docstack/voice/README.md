# Dynamic Voice corpus

Train Cursor Dynamic Voice on Max-authored prose under `references/active/`.

## Layout

| Tier | Path | Enters profile? |
|------|------|-----------------|
| active | `references/active/` | Yes |
| candidate | `references/candidates/` | No |
| library | `references/library/` | No (kept for reading) |
| dump | `references/Drive/`, `references/Takeout/` | No |

Contribute path: **dump → `voicectl picklist` (plan) → `voicectl convert` → candidates → human `promote` → active**.

Never auto-walk Takeout into `active/`. Convert never writes into `active/`. Picklist never converts or promotes.

### Prose modes (edit vs write)

`sessionStart` appends a fixed operator policy after the style brief (see `voicectl condition`). `ensure` does not regenerate that policy.

- **Edit** (rewrite, tighten, match my voice). Preserve claims and conclusions. Preserve numbers and units. Preserve section and figure references. Preserve equations already in the source. Preserve citations, sources, and named systems. Change wording, grammar, punctuation, and rhythm. Leave document structure alone unless asked to restructure.
- **Write** (draft with no source prose). Search the project workspace and attached paths for sources first. Do not invent sources, opinions, findings, or perspectives. Treat `references/active/` as style material unless that tree is the open workspace.
- **Derived work.** Equations and deterministic transforms of existing information may appear as computation, not as new observational claims.
- **Stop.** If the agent would drop a preserve item or invent content, it must ask you for the missing source or permission instead of emitting that content.

Open a new Agent chat after corpus or policy changes so `sessionStart` reinjects the brief.

## Multi-doc voice banks

Conditioning uses eight archetype docs under `banks/archetypes/` plus mass JSON under `.cache/banks/<corpus_version>/`, not a single distilled excerpt brief. See [`banks/README.md`](banks/README.md).

```bash
voicectl banks rebuild|status|show BANK|verify|scaffold
```

## Commands

```bash
voicectl ensure              # rebuild profile + bank mass from active/
voicectl version             # corpus_version digest
voicectl condition           # session conditioning brief (multi-bank index)
voicectl triage              # CSV over Drive (default); Takeout needs explicit paths
voicectl triage path/to/Takeout/...
voicectl picklist            # Phase-0 Max-authored convert queue (Drive default)
voicectl picklist path/to/Takeout/...
voicectl picklist --format paths   # one path per line (rescue+confirm only)
voicectl picklist --format json
voicectl convert file.pdf    # Marker → references/candidates/
voicectl promote file.md     # candidates (or any prose) → active/
voicectl park path…          # move into library/
```

Authorship for `triage` is path/tier rules in `config.yaml` (`authorship.rules`). First match wins. No prose classifier.

### Picklist (Phase 0)

`voicectl picklist` judges dump PDF/DOCX in directory batches (cheap extract + path-tier prior) via the **Cursor** `agent` CLI (`--mode ask`). Needs `agent login` or `CURSOR_API_KEY`. It writes `.cache/picklist/latest.json` and prints:

- **Batch** — rescue (body Max, path prior missed) then confirm (prior already candidate). This is the default convert queue (`--format paths`).
- **Mixed** — shared/group Max rows; review before convert (not in `--format paths`).
- **Not Max-authored** — manuals, guidelines, other authors (including path-tier false positives).
- **Abstain / Already converted** — thin extract, or ok Marker cache hit.

Copy paths from Batch, then run `voicectl convert` yourself. Picklist does not call convert or promote.

## Config notes

- `marker.output_dir: references/candidates`
- `list_references` reads `references/active/` (sole corpus input)
- Editing `authorship` changes `config_digest` and invalidates a cached profile
