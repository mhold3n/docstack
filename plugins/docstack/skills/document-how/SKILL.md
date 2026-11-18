---
name: document-how
description: "Use for \"how does X work\", docs walkthroughs before changing a section, and placement / ownership / layering questions (\"where should this live\", \"which page owns this\", \"is this the right Diátaxis mode\"). Explains corpus structure, nav flow, onboarding mental models. Use why for motivation."
disable-model-invocation: true
---

# How

Explore the doc corpus to answer "how is X structured?" questions.

If the scope is ambiguous, state your interpretation and explore. The user can redirect.

## 1. Explain

Spawn one Task subagent with `subagent_type: generalPurpose` and `readonly: true` that explores and explains in one pass. Give it the user's question and this brief:

> You are writing a structural explanation for a senior writer. Explore the docs and write an explanation that a writer unfamiliar with this area could read and walk away with a solid mental model. They should understand the corpus well enough to start editing it confidently. You have read-only access to the docs.

## 2. Present

Present the subagent's output. Light edits for clarity or context from the conversation are fine. Do not substantially rewrite it.
