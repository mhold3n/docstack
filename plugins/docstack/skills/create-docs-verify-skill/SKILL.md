---
name: create-docs-verify-skill
description: Generate a project-local docs verification skill that proves markdown/docs/PDF changes on the real artifact (lint, links, render, optional example compile, PDF/HTML snapshots). Use for /create-docs-verify-skill or when agents need a scripted way to prove docs work.
disable-model-invocation: true
---

# Create a docs verification skill

Generate a project-local skill under `.cursor/skills/verify-docs-<project>/` (or a name the user chooses) so agents can prove docs and PDF changes without guessing.

## Outcomes

Ship one skill directory with:

- `SKILL.md` — how to launch checks, what "pass" means, where evidence lands
- `checks/` or inline scripts — executable helpers the skill documents
- Optional `features/` map — one file per docs surface (site section, chapter, PDF) when the corpus is large

## Pass

1. **Detect what the project already has.** Look for markdownlint, lychee or markdown-link-check, and Vale. Look for docs build scripts (`npm run docs`, `mkdocs`, `docusaurus`, `sphinx`, Pandoc). Look for Playwright or snapshot tests and Poppler. Prefer wiring existing tools over inventing new ones.

2. **Interview once if needed.** Ask what you cannot infer: primary docs root, whether PDF is in scope, where evidence should land (`tmp/docs-verify/`).

3. **Write the skill.** Required sections in `SKILL.md`:
   - **Launch** — exact commands, cwd, env
   - **Surfaces** — markdown site, single pages, PDF paths
   - **Pass bar** — lint clean, links clean, build/render succeeds, PDF PNG spot-check when PDF is in scope
   - **Evidence** — where logs and PNGs go; keep them out of git unless the repo already commits golden images
   - **Cleanup** — what to delete after a run

4. **Helpers rule.** Scripts are executable, take explicit paths, and exit non-zero on failure. Name each helper in the skill body. No Windows-style paths.

5. **Smoke once.** Run the verify skill's happy path on the current corpus. Fix until green or document a known baseline failure with a file:line citation.

6. **Hand off.** Tell the user the skill path and the one command agents should run. Offer `/maintain-docs-verify-skill` for later upkeep.

## Anti-patterns

- Driving a product UI as the primary proof (that is pstack's app verify skill)
- Declaring pass from "the markdown looks right" without a command
- Inventing a second link checker when the repo already has one
