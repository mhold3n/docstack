---
name: setup-docstack
description: Configure which models docstack uses per role and at what reasoning budget. Detects your available models and writes an always-applied rule that overrides the skill defaults. Use for /setup-docstack, "configure docstack models", "docstack budget", or changing docstack's model choices.
disable-model-invocation: true
icon: book-open
color: blue
---

# Setup docstack

Write `~/.cursor/rules/docstack-models.mdc`, an always-applied rule that sets docstack's model per role. This file is separate from `pstack-models.mdc`. Docs roles do not overwrite code roles.

## Steps

### 1. Detect available models

List the model slugs you can pass to a `Task` subagent in this session. That is the dependable source. If Cursor also exposes a models API or CLI that lists the user's entitled models, prefer it for completeness. If you cannot detect any, ask the user to paste the slugs they have access to. Never write a real slug you have not confirmed is available. The aliases `inherit-parent` and `auto` are always valid even though they are not detected slugs.

### 2. Load current state

The default role-to-model mapping is the rule shape shown in step 5 below. If `~/.cursor/rules/docstack-models.mdc` already exists, read it and treat its `# budget` line and its role values as the current choices. Otherwise start from those defaults. Drop a line whose role is not in step 5; that role no longer applies.

If `docstack-models.mdc` is missing but `~/.cursor/rules/pstack-models.mdc` exists, offer to seed panel roles from matching pstack lines. Seed `arena runners`, `arena cross-judge pool`, `swarm workers`, `interrogate reviewers`, and `judgment and prose`. Map pstack `feature, refactoring` → `chapter, page` and `bug-fix` → `fact-fix`. Do not edit the pstack file.

### 3. Budget, map, and confirm

**(a) Ask for a budget.** Prefer AskQuestion over free text. Offer these three options with these exact labels, and name the current budget when the rule records one. With no rule, say that `large` matches the skill defaults.

- `large — xhigh reasoning`
- `medium — high reasoning`
- `small — medium reasoning`

**(b) Apply it.** Build the working table from the skill defaults, and on a re-run keep any role you changed by family, list, or alias (`inherit-parent`, `auto`). Each role has a target effort, which is its default's effort moved by the budget. `large` keeps it, `medium` lowers it one step, and `small` lowers it two steps, on the ladder `xhigh` > `high` > `medium` > `low`. No role runs above `xhigh`. Set the effort token of every real slug in the role, panel entries included, to the role's target. If the result is not a detected slug, use the same family's detected slug with the highest effort at or below the target, else mark the role as needing a choice. `inherit-parent` and `auto` do not change.

**(c) Show the roles and confirm.** Show every role with its model, marking any real slug not in the detected set as needing a choice. Ask whether to accept as-is or change specific roles, offering the detected models at `xhigh` or below plus `inherit-parent` and `auto`. Prefer AskQuestion over free text. For panel roles the value is a list, and one subagent runs per entry, so the list length sets the count. `arena cross-judge pool` is also a list, but Arena runs one judge from a vendor other than the parent's, in list order.

### 4. Validate

Every real slug written must be in the detected set and at `xhigh` or below. `inherit-parent` and `auto` always pass. If a chosen real slug is not available, stop and ask again.

### 5. Write the rule

Write `~/.cursor/rules/docstack-models.mdc` with `alwaysApply: true`, the `# defaults: 1` line, a `# budget` line with the chosen label and the effort that label names, and one line per role. Overwrite the whole file so re-runs stay idempotent. Shape (replace slugs with detected ones the user confirmed):

```
---
description: docstack per-role model choices (overrides skill defaults)
alwaysApply: true
---
# docstack model configuration. One line per role. Delete a line to fall back to the skill default.
# `inherit-parent` or `auto` as a value: the role runs on the parent chat model (omit Task `model` and spawn `generalPurpose`). Alias entries in a panel list still count toward its fan-out.
# defaults: 1
# budget: large (xhigh)
chapter, page: inherit-parent
fact-fix: inherit-parent
edit: inherit-parent
judgment and prose: inherit-parent
arena runners: inherit-parent
arena cross-judge pool: inherit-parent
swarm workers: inherit-parent
interrogate reviewers: inherit-parent
```

When the user picks real slugs, write those instead of `inherit-parent`. Prefer the user's detected high-quality models for `chapter, page`, `fact-fix`, and `judgment and prose`, and a cheaper or faster slug for `edit` and `swarm workers` when available.

### 6. Confirm

Tell the user you wrote the rule and that it applies to new sessions. Re-running this skill updates it.

### 7. Offer a docs verification skill (optional)

Check whether the project has a way to prove docs on the real artifact (a `verify-docs-*` skill, or lint/link/render scripts). If not, offer once: "want a project-local docs verification skill? Agents can then lint and link-check. They can also render and snapshot docs/PDFs. I can generate one with /create-docs-verify-skill." On yes, invoke `/create-docs-verify-skill`. On no, move on without pushing.
