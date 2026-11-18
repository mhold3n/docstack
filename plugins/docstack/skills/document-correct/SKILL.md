---
name: document-correct
description: "Find the mistakes agents keep repeating in this docs corpus and make each one impossible. Try information architecture or schema first, then markdownlint or a link check, then snapshot or render tests, and write prose rules last. Prove each check fails on a real past mistake. Repeat this each time the operator corrects you. Use for /document-correct."
disable-model-invocation: true
---

# Correct

The operator keeps correcting agents in this docs corpus for the same mistakes. Change the corpus so the next agent can't make them.

Assume every contributor is an agent that sees only the files it opened, copies the nearest example, and takes the shortest path that still renders. Design the corpus so a change that looks right from one page is right for the whole set.

## Find the mistake classes

First, read recent commits, reverts, review comments, agent instruction files, and comments that explain workarounds. Group the mistakes into classes. A class counts once it has happened twice.

## Fix each class at the highest level that works

1. **Eliminate it with information architecture or schema.** Give each topic one owner page and each reader task one path. Encode the domain in a taxonomy, glossary, Diátaxis map, or typed frontmatter. Hide internals so the wrong nav entry fails. Replace hand-synced lists with one source of truth. Delete old pages and dead stubs an agent would copy.
2. **Enforce it with markdownlint or a link check so the bad state can't be published.** If bad markdown still renders, add a lint or CI check whose error names the file, heading, or page to use instead. If the pattern is already common, fail only when a change adds more.
3. **Test the render.** Fix or delete any snapshot or render test that still passes when the page or PDF it checks breaks, or that fails when only internals change.
4. **Write prose rules or agent instructions last, only for judgment calls.** Nothing fails when an agent skips them.

## Fix and prove

Then fix the most frequent classes now, one commit each. Prove each new check fails on a real past mistake. Run the same command locally and in CI. Exceptions go on the offending line with a reason, an expiry date, and a human's approval.

## Keep the rule table

Last, keep a table in the agent instruction file that pairs each rule with what enforces it. When the operator corrects you, fix the mistake and add the rule. If the rule was already there and nothing enforces it, that's a repeat, so fix it at the highest level in the same change. Drop a rule once its mistake can't happen.

**Reply:** each class with its evidence, the level you picked, and why a higher level didn't work.
