### Chapter

**You own the design. Plan, review, verify.** Delegate drafting. Stay in the lead.

1. Trace the affected corpus (nav, sibling pages, Diátaxis mode, cross-links).
2. `architect` for the information architecture.
3. Write the throughput checkpoint as four todo items. A dimension that does not apply (single file, no fan-out) keeps its item with `n/a: <reason>` instead of dropping it:
   - **Blocking first steps.** Gates run before fan-out (IA, glossary, shared frontmatter).
   - **Independent workstreams.** Disjoint pages or sections parallelize. Shared nav or claim ownership serializes.
   - **Shared mutable state.** Default to splitting ownership of a claim across pages. Serialize for real invariants (single source of truth).
   - **Smallest safe decomposition.** If one worker is best, name why.
4. Delegate drafting to a subagent using your configured `chapter, page` model with a specific scope (paths, Diátaxis mode, heading outline, success criteria). Pick each subagent's reasoning level for the job, per the Subagents section. When the structure admits more than one valid shape, delegate via the **arena** skill instead. Surgical edits, re-ground against the source for upstream-derived docs. Port shared phrasing improvements to all consumers and verify each. Commit liberally.
5. Verify on the matching surface: rendered page or site, link check, style lint when present. PDF chapters also run the **pdf** skill's page-PNG review. "Inconclusive" or wrong-surface is not a pass. Flag it.
6. Rebase into small, ordered commits. Stack follow-ups.
   Use the **sequence-verifiable-units** principle skill, building, verifying, and committing each small unit before the next.
7. If design or claims draw disagreement, `interrogate` before shipping.
8. Run **Opening a PR**.

Corpus-coupled work (one chapter, one migration) goes to a single owner with the checkpoint inline. That owner fans out internally after the blocking phase. Parent-level fan-out is for slices that produce independent artifacts. Rewrite the checkpoint at phase boundaries. Spawn a fresh owner rather than chaining interrupts.

**Reply:** what you wrote, what you chose and why, the throughput checkpoint, open decisions. Tables for design alternatives.
