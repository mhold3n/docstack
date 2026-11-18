---
name: document-principle-prove-it-works
description: "Apply after completing a task, before declaring done. Verify against the real artifact (rendered markdown or site, working link, PDF page PNGs), not a proxy, self-report, or 'the markdown looks right.'"
disable-model-invocation: true
---

# Prove It Works

Verify every output by checking the real thing directly: render the markdown or site, follow the link, inspect PDF page PNGs. Proxies (file mtimes, self-reports, cached output, "the markdown looks right") do not count. When a check fails, suspect the observation method before the system.

Script the check when you can. A deterministic script that reruns the comparison beats a one-time look. Keep its output where the human can see it, and commit it only when the trail must be auditable later.
