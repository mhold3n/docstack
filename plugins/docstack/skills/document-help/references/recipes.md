# Prompts worth copying

Swap in the real paths, skills, and done checks. Informal wording works.

## Understand

- `/document-mode read <thread>. restate the underlying issue in your own words, in plain english.`
- `/document-in-your-own-words <long or messy ask>`
- `/document-sharpen <the prompt you're about to send>`
- `/document-mode investigate why <section> is structured this way. don't change any docs yet.`
- `use /document-how to understand <docs root>. then use /document-why to find out why it changed recently.`
- `/document-recall my work on <topic> from last week, then read <doc>.`
- `/document-teach me why you structured it this way and not <other way>. what did you trade off?`

## Build

- Fact fix: `/document-mode <wrong claim or broken example>. repro against the source of truth, then fix and verify.`
- Chapter: `/document-mode add <page or chapter>. done when it renders, links resolve, and the outline matches <brief>.`
- Restructure: `/document-mode move <pages> into one section, zero claim change. pin wording first and prove claims unchanged after.`
- PDF: `/document-mode produce <pdf> from <source>. render every page and show me the PNGs.`
- PDF review: `/document-mode review <pdf> visually. report only.`

## Design and plan

- `/document-mode prototype a few outlines for <chapter>. let me compare.`
- `/document-mode we need <docs>. /document-architect it first, and answer open questions with prototypes. let me review before proceeding.`
- `ask /document-arena for a second opinion on this outline.`
- `/document-mode turn this design into a plan. small verifiable PRs, each with its own verification steps.`

## Review and ship

- `/document-interrogate the whole docs branch, but skeptically. don't change anything yet.`
- `/document-swarm check every page under <dir> for broken links. one worker per slice. one report.`
- `/document-mode open the pr. small ordered commits, evidence in the description.`
- `/document-mode babysit this pr. get it green.`
- `/document-create-verify-skill` then agents run that skill to prove docs changes.

## Meta

- `/document-setup`
- `/document-automate-me`
- `/document-reflect`
- `/document-correct`
