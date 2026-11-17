---
name: docstack-help
description: Guides users through docstack setup, /docs-mode, and picking the skill, playbook, or principle for a docs or PDF task. Type /docstack-help with a question.
disable-model-invocation: true
icon: book-open
color: cyan
---

# Docstack help

Answer the user's question about docstack, hand them a prompt they can send, and link the file the answer came from. For a help question, don't start the work. The user asked how, and a docstack run spends real tokens, so let them send the prompt.

A message that asks for work, such as "use docstack to fix this page", is not a help question. Read [`docs-mode`](../docs-mode/SKILL.md), do the work under it, and mention once that a Custom Mode keeps it on.

This file maps questions to the skills that hold the answers. Those files own the details. Read the file you route to before you quote it, and trust it when it disagrees with this map.

## Find out what they need

Infer the need from the message and the conversation. A named situation goes straight to its section. If the need is still unclear, ask one choice question with these options, then answer the section they pick:

- Get set up
- Start a task with `/docs-mode`
- Pick a skill for a situation
- Fix a run that went wrong
- Make docstack my own

Check the state that changes the answer, and mention it when it does:

- No `~/.cursor/rules/docstack-models.mdc` means `/setup-docstack` hasn't run for this user, so every role uses its default model (and may fall back to pstack-models.mdc).
- No `verify-docs-*` skill or docs lint/link/render harness in the project means agents have no scripted way to prove docs. Mention `/create-docs-verify-skill` when the question is about proving a change works.

When the model rule is missing and it matters, ask whether the user wants to pick a model for each role and a reasoning budget now. Ask at most once per chat. Offer two choices:

- Now: give them `/setup-docstack` to type, and answer their question too.
- Later: answer their question, and add one line saying every role keeps its default until they run `/setup-docstack`.

## Get set up

1. Ensure the plugin is available under `~/.cursor/plugins/local/docstack/`.
2. Run [`/setup-docstack`](../setup-docstack/SKILL.md). It asks for a reasoning budget, maps a model to each role, and writes `~/.cursor/rules/docstack-models.mdc`. Then it offers once to generate a docs verification skill unless the project already has one.
3. Start a real task with `/docs-mode`, a goal, and a check that can pass or fail.

Installing changes nothing until the user invokes a skill. Offer to word their first prompt with them, per [`references/prompting.md`](references/prompting.md).

If cost is the worry, say where the tokens go and how to spend fewer. Rerun `/setup-docstack` and pick a smaller budget, cheaper models, or `auto` / `inherit-parent`. Save `/docs-mode` for work that needs rigor.

## Start a task with `/docs-mode`

`/docs-mode` matches the task to a playbook, copies the playbook's steps into the todo list, and runs the other skills as the steps need them. A good prompt states the goal and how to tell it's done. It doesn't list skills. Read [`references/prompting.md`](references/prompting.md) before you help word one.

Whether `/docs-mode` stays on depends on how the user starts it:

- Enter on `/docs-mode` attaches the skill to one message. It fades as the chat moves on.
- Option+Enter on Mac or Alt+Enter on Windows, or Use as Mode from the skill entry, makes it a Custom Mode.

Mid-chat, "new task" makes the mode match a fresh playbook. `/docs-mode` uses `docs-agent` for the subagents its playbook steps spawn when that type is available.

## Pick a skill

The default answer is `/docs-mode`, which runs most of the others when its steps need them. Name a skill directly when the user wants more or less of something than the playbook gives.

| The user wants to | Skill |
|---|---|
| Do any non-trivial docs/PDF task with rigor | [`/docs-mode`](../docs-mode/SKILL.md) |
| Check that the agent understood their goal before it starts | [`/in-your-own-words`](../in-your-own-words/SKILL.md) |
| Get a prompt rewritten deeper before sending it | [`/sharpen`](../sharpen/SKILL.md) |
| Know how a doc corpus works now | [`/how`](../how/SKILL.md) |
| Know why a section is shaped this way | [`/why`](../why/SKILL.md) |
| Understand a docs change, explained plainly | [`/teach`](../teach/SKILL.md) |
| Catch up on their own recent work on a topic | [`/recall`](../recall/SKILL.md) |
| Catch up on what changed in this chat | [`/ketchup`](../ketchup/SKILL.md) |
| Settle information architecture before drafting | [`/architect`](../architect/SKILL.md) |
| Get several attempts at one brief, merged into the best one | [`/arena`](../arena/SKILL.md) |
| Run parallel checks over doc slices | [`/swarm`](../swarm/SKILL.md) |
| Adversarial fact-check or break the claims | [`/interrogate`](../interrogate/SKILL.md) |
| Work with no matching playbook | [`/figure-it-out`](../figure-it-out/SKILL.md) |
| Create or visually review a PDF | [`/pdf`](../pdf/SKILL.md) |
| Apply house prose style | [`/technical-writing`](../technical-writing/SKILL.md), [`/unslop`](../unslop/SKILL.md) |
| Generate a project docs verifier | [`/create-docs-verify-skill`](../create-docs-verify-skill/SKILL.md) |
| Audit that verifier later | [`/maintain-docs-verify-skill`](../maintain-docs-verify-skill/SKILL.md) |
| Capture their own working style | [`/automate-me`](../automate-me/SKILL.md) |
| Mine this transcript for skill edits | [`/reflect`](../reflect/SKILL.md) |
| Encode repeated mistakes | [`/correct`](../correct/SKILL.md) |

Copy-ready prompts live in [`references/recipes.md`](references/recipes.md).

## Fix a run that went wrong

- Wrong playbook → say "new task" and restate the goal with a done check.
- Models too expensive or wrong → `/setup-docstack`.
- Verify gaps → `/create-docs-verify-skill` or fix the project's lint/link/render scripts.
- Repeated agent mistakes → `/correct`.

## Make docstack my own

- `/automate-me` for a personal `-mode` skill.
- `/reflect` to propose edits to docstack skills (edit the local plugin copy under `~/.cursor/plugins/local/docstack/`).
- `/correct` to encode lessons as structure (lint, CI, scripts) rather than more prose.
