# Prompts worth copying

Swap in the real paths, skills, and done checks. Informal wording works.

## Understand

- `/docs-mode read <thread>. restate the underlying issue in your own words, in plain english.`
- `/in-your-own-words <long or messy ask>`
- `/sharpen <the prompt you're about to send>`
- `/docs-mode investigate why <section> is structured this way. don't change any docs yet.`
- `use /how to understand <docs root>. then use /why to find out why it changed recently.`
- `/recall my work on <topic> from last week, then read <doc>.`
- `/teach me why you structured it this way and not <other way>. what did you trade off?`

## Build

- Fact fix: `/docs-mode <wrong claim or broken example>. repro against the source of truth, then fix and verify.`
- Chapter: `/docs-mode add <page or chapter>. done when it renders, links resolve, and the outline matches <brief>.`
- Restructure: `/docs-mode move <pages> into one section, zero claim change. pin wording first and prove claims unchanged after.`
- PDF: `/docs-mode produce <pdf> from <source>. render every page and show me the PNGs.`
- PDF review: `/docs-mode review <pdf> visually. report only.`

## Design and plan

- `/docs-mode prototype a few outlines for <chapter>. let me compare.`
- `/docs-mode we need <docs>. /architect it first, and answer open questions with prototypes. let me review before proceeding.`
- `ask /arena for a second opinion on this outline.`
- `/docs-mode turn this design into a plan. small verifiable PRs, each with its own verification steps.`

## Review and ship

- `/interrogate the whole docs branch, but skeptically. don't change anything yet.`
- `/swarm check every page under <dir> for broken links. one worker per slice. one report.`
- `/docs-mode open the pr. small ordered commits, evidence in the description.`
- `/docs-mode babysit this pr. get it green.`
- `/create-docs-verify-skill` then agents run that skill to prove docs changes.

## Meta

- `/setup-docstack`
- `/automate-me`
- `/reflect`
- `/correct`
