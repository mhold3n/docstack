# Word the prompt

A prompt states the intent and the check for done. The playbook supplies the steps. Short plain sentences beat a spec.

## Put in

- The goal. Say what is wrong or what the user wants in the docs or PDF.
- The done check. It can pass or fail. "Make it better" and a duration are not checks.
- The proof to show. Ask for render output, link-check logs, PDF page PNGs, or a before and after.
- What the user already knows. A symptom, a bad page, a stale claim, or a link saves the agent a search.
- The real constraints. "don't change claims", "PDF alone", "zero nav change", and "let me review before proceeding" each change what the agent does.

## Leave out

- The how. Say what to achieve, and leave the agent room to find a better way.
- A list of skills or steps. A hand-written order drops or reorders steps the playbook keeps. Name a skill to override one choice.
- The user's theory of the cause, until the agent restates the problem.

## Load the context first

- For a noisy report, ask the agent to restate the underlying issue in its own words before it edits.
- In a fresh chat, `/document-recall` earlier work on the topic.
- Before a change to unfamiliar docs, ask `/document-how` for the structure and `/document-why` for the reasons.
- Ask `/document-teach` to make the case for a structural choice.

## Design before the plan

- Never take the first outline. Ask for prototypes of 2-3 options and pick from the evidence.
- For a new chapter or PDF, ask for the outline or sample pages first, then draft.
- Ask for the plan after the information architecture settles. Each step of the plan ends in a check.

## Follow up short

- "do it", "continue", and "keep going until done" are whole prompts once the chat holds the task.
- Start with "new task" when the subject changes.

## Before stepping away

- Say "im going to bed" or "im stepping away" so the agent stops asking.
- Name the done check again if it can finish without you.
