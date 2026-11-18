---
name: document-help
description: Guides users through docstack setup, /document-mode, and picking the skill, playbook, or principle for a docs or PDF task. Type /document-help with a question.
disable-model-invocation: true
icon: book-open
color: cyan
---

# Docstack help

Answer the user's question about docstack, hand them a prompt they can send, and link the file the answer came from. For a help question, don't start the work. The user asked how, and a docstack run spends real tokens, so let them send the prompt.

A message that asks for work, such as "use docstack to fix this page", is not a help question. Read [`document-mode`](../document-mode/SKILL.md), do the work under it, and mention once that a Custom Mode keeps it on.

This file maps questions to the skills that hold the answers. Those files own the details. Read the file you route to before you quote it, and trust it when it disagrees with this map.

## Find out what they need

Infer the need from the message and the conversation. A named situation goes straight to its section. If the need is still unclear, ask one choice question with these options, then answer the section they pick:

- Get set up
- Start a task with `/document-mode`
- Pick a skill for a situation
- Fix a run that went wrong
- Make docstack my own

Check the state that changes the answer, and mention it when it does:

- No `~/.cursor/rules/docstack-models.mdc` means `/document-setup` hasn't run for this user, so every role uses its default model (and may fall back to pstack-models.mdc).
- No `verify-docs-*` skill or docs lint/link/render harness in the project means agents have no scripted way to prove docs. Mention `/document-create-verify-skill` when the question is about proving a change works.

When the model rule is missing and it matters, ask whether the user wants to pick a model for each role and a reasoning budget now. Ask at most once per chat. Offer two choices:

- Now: give them `/document-setup` to type, and answer their question too.
- Later: answer their question, and add one line saying every role keeps its default until they run `/document-setup`.

## Get set up

1. Ensure the plugin is available under `~/.cursor/plugins/local/docstack/`.
2. Run [`/document-setup`](../document-setup/SKILL.md). It asks for a reasoning budget, maps a model to each role, and writes `~/.cursor/rules/docstack-models.mdc`. Then it offers once to generate a docs verification skill unless the project already has one.
3. Start a real task with `/document-mode`, a goal, and a check that can pass or fail.

Installing changes nothing until the user invokes a skill. Offer to word their first prompt with them, per [`references/prompting.md`](references/prompting.md).

If cost is the worry, say where the tokens go and how to spend fewer. Rerun `/document-setup` and pick a smaller budget, cheaper models, or `auto` / `inherit-parent`. Save `/document-mode` for work that needs rigor.

## Start a task with `/document-mode`

`/document-mode` matches the task to a playbook, copies the playbook's steps into the todo list, and runs the other skills as the steps need them. A good prompt states the goal and how to tell it's done. It doesn't list skills. Read [`references/prompting.md`](references/prompting.md) before you help word one.

Whether `/document-mode` stays on depends on how the user starts it:

- Enter on `/document-mode` attaches the skill to one message. It fades as the chat moves on.
- Option+Enter on Mac or Alt+Enter on Windows, or Use as Mode from the skill entry, makes it a Custom Mode.

Mid-chat, "new task" makes the mode match a fresh playbook. `/document-mode` uses `document-agent` for the subagents its playbook steps spawn when that type is available.

## Pick a skill

The default answer is `/document-mode`, which runs most of the others when its steps need them. Name a skill directly when the user wants more or less of something than the playbook gives.

| The user wants to | Skill |
|---|---|
| Do any non-trivial docs/PDF task with rigor | [`/document-mode`](../document-mode/SKILL.md) |
| Check that the agent understood their goal before it starts | [`/document-in-your-own-words`](../document-in-your-own-words/SKILL.md) |
| Get a prompt rewritten deeper before sending it | [`/document-sharpen`](../document-sharpen/SKILL.md) |
| Know how a doc corpus works now | [`/document-how`](../document-how/SKILL.md) |
| Know why a section is shaped this way | [`/document-why`](../document-why/SKILL.md) |
| Understand a docs change, explained plainly | [`/document-teach`](../document-teach/SKILL.md) |
| Catch up on their own recent work on a topic | [`/document-recall`](../document-recall/SKILL.md) |
| Catch up on what changed in this chat | [`/document-ketchup`](../document-ketchup/SKILL.md) |
| Settle information architecture before drafting | [`/document-architect`](../document-architect/SKILL.md) |
| Get several attempts at one brief, merged into the best one | [`/document-arena`](../document-arena/SKILL.md) |
| Run parallel checks over doc slices | [`/document-swarm`](../document-swarm/SKILL.md) |
| Adversarial fact-check or break the claims | [`/document-interrogate`](../document-interrogate/SKILL.md) |
| Work with no matching playbook | [`/document-figure-it-out`](../document-figure-it-out/SKILL.md) |
| Create or visually review a PDF | [`/document-pdf`](../document-pdf/SKILL.md) |
| Gate prose through voice MCP, then house style | [`/document-voice-write`](../document-voice-write/SKILL.md), then [`/document-technical-writing`](../document-technical-writing/SKILL.md) / [`/document-unslop`](../document-unslop/SKILL.md) |
| Generate a project docs verifier | [`/document-create-verify-skill`](../document-create-verify-skill/SKILL.md) |
| Audit that verifier later | [`/document-maintain-verify-skill`](../document-maintain-verify-skill/SKILL.md) |
| Capture their own working style | [`/document-automate-me`](../document-automate-me/SKILL.md) |
| Mine this transcript for skill edits | [`/document-reflect`](../document-reflect/SKILL.md) |
| Encode repeated mistakes | [`/document-correct`](../document-correct/SKILL.md) |

Copy-ready prompts live in [`references/recipes.md`](references/recipes.md).

## Fix a run that went wrong

- Wrong playbook → say "new task" and restate the goal with a done check.
- Models too expensive or wrong → `/document-setup`.
- Verify gaps → `/document-create-verify-skill` or fix the project's lint/link/render scripts.
- Repeated agent mistakes → `/document-correct`.

## Make docstack my own

- `/document-automate-me` for a personal `-mode` skill.
- `/document-reflect` to propose edits to docstack skills (edit the local plugin copy under `~/.cursor/plugins/local/docstack/`).
- `/document-correct` to encode lessons as structure (lint, CI, scripts) rather than more prose.
