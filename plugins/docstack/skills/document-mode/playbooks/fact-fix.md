### Fact fix

**You own this task. Plan, review, verify.** Delegate investigation and the fix to subagents, stay in the lead.

Be scientific. Every shipped line traces to source evidence (code, API, product, prior doc with authority). A hedge that "might help" is a hypothesis, not a fix. It does not ship. When evidence refutes a hypothesis, revert what it motivated. The smallest change the evidence justifies ships, nothing more.

1. Reproduce the defect yourself against the authority: wrong claim, broken example, stale API, dead link, bad PDF layout. Prefer running the example or checking the source of truth over asking the user.
2. Binary-search the cause. Form candidate hypotheses, then rule them out until one survives. Seed them with a trace of the affected docs and the **document-why** skill for regression history. Confirm the surviving mechanism with evidence before step 3's `document-architect` or an `document-interrogate` fan-out.
3. Plan the fix. If it crosses a page or section boundary, `document-architect` first. Delegate implementation to a subagent using your configured `fact-fix` model with a specific scope.
4. Verify on the same surface. The original defect no longer appears. Examples run when they claim to. PDF pages re-render cleanly when PDF is in scope. "Inconclusive" or wrong-surface is not a pass. Flag it.
5. Stage the commits so the failing repro or citation lands before the fix in git history when practical.
   This is the canonical **sequence-verifiable-units** principle skill.
6. Run **Opening a PR**.

**Reply:** what was wrong, root cause, fix, how you verified. Paste failing-then-passing evidence verbatim.
