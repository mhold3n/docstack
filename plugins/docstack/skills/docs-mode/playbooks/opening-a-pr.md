### Opening a PR

Invoked at the end of every other playbook.

Work from a git worktree off trunk, and keep unrelated work out of it. Rebase into small, landable commits. Run `/deslop` from `cursor-team-kit` over the diff before commit.

Title: `type(scope): subject`, naming a real page, section, or heading when one carries the change.

Body: a one-minute briefing under 40 lines. Use these `##` headings in order and drop empty ones.

- `## Why`
- `## What changed`
- `## Scope`
- `## Tradeoffs` (rejected alternatives a reviewer would otherwise ask about)
- `## Blast Radius`
- `## Verification`

Run **voice-write** on the PR body before opening so the corpus scores the briefing.

Stack follow-ups by base branch. Open PRs ready, through the run's PR tool with `draft: false`. Without one, use `gh pr create` without `--draft`, or `origin pr create --status open` when Origin's CLI resolves the repository. Opening a PR does not start a babysit.
