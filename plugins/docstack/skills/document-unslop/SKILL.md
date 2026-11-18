---
name: document-unslop
description: Cut AI tells from any writing.
disable-model-invocation: true
---

# Unslop

Edit text to remove AI patterns that make the prose sound generated rather than authored. Before the rewrite pass, run **document-voice-write**. That call sets the corpus profile and scores the finished draft. Scan the numbered catalog below, rewrite the draft, and preserve meaning while matching the intended tone.

Rule numbers are stable ids that other skills cite when they point at a pattern. A removed rule leaves a numbered gap on purpose so older citations still resolve.

3. Drop trailing `-ing` phrases that add no fact, such as "highlighting" or "ensuring" tacked onto a finished claim.
5. Drop vague attributions such as "experts believe" unless you name the source, or delete the claim.
7. Ban these AI vocabulary tokens in ordinary prose: `additionally` `crucial` `delve` `enhance` `foster` `landscape` `pivotal` `showcase` `testament` `underscore` `vibrant`.
8. Prefer "is" or "has" over padded verbs such as "serves as", "stands as", "boasts", or "features".
9. Forbid the `not just X, but Y` pattern and state the point in a single direct claim.
10. Do not force ideas into decorative groups of three when the draft needs a different count.
11. Give each thing one name and repeat that name instead of cycling synonyms for variety.
12. Avoid "from X to Y" spans unless X and Y sit on a real scale the reader can check.
13. Do not use em dashes, en dashes, or hyphens as dashes, and do not swap in parentheses for the same job; prefer a period or a comma.
14. Put a colon before a list or an example, and never use a colon as a mid-sentence connector.
15. Do not bold every proper noun or acronym as if emphasis itself were content.
16. Do not open a line with a bold label and colon that restates the same line; a bold lead-in that ends in a period and adds new detail is fine.
17. Write headings in sentence case so the title reads like a normal claim.
18. Skip decorative emojis that do not carry information the reader needs.
19. Use straight quotes rather than curly ones in plain draft text.
20. Drop chatbot closers such as "I hope this helps" or "Let me know if you need anything".
22. Skip praise or agreement openers and respond to the substance directly.
23. Cut filler such as replacing `In order to` with `to`, and delete openers of the form "important to note that".
24. Keep at most one hedge word, and prefer "may" when you need a hedge.
25. Avoid generic conclusions; state specific plans or facts the reader can act on.
26. Ban abstract metaphor nouns and prefer the concrete word instead of `substrate` `wedge` `vector` `nexus` `primitive` `harness` `surface` `scaffolding` `paradigm` `ratchet` `north star` `flywheel`.
27. Say what the thing does rather than how it feels, name the mechanism or the number, and cut a sentence that could appear unchanged in another project's docs.
28. Keep one idea per sentence, and split any sentence the reader has to reread to parse.
29. Prefer active voice and name the actor when you know who performs the action.
30. Cut weak adverbs or replace them with a stronger verb, and give the number when size matters.
31. Prefer the plain verb `use` over `utilize` or `leverage` in ordinary instructions.
32. Drop metaphor, aphorism, personified code, or figurative verbs when a literal phrase already exists.
33. Write whole sentences with their articles and verbs, and spell out arrows plus abbreviations the reader would say aloud.
