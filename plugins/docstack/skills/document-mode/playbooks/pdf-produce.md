### PDF produce

**You own the artifact. Plan, draft, render, verify visually.**

1. Confirm the source of truth (markdown, structured data, or from-scratch). Pick output path under `output/document-pdf/` (or the project's convention).
2. `document-architect` layout when the document is multi-section or contested. Otherwise proceed.
3. Generate with the **document-pdf** skill (`reportlab` or the project's generator). Keep intermediate files under `tmp/document-pdfs/`.
4. After each meaningful update, render pages with `pdftoppm -png` and inspect the PNGs yourself. Fix clipped text, overlaps, broken tables, bad margins, unreadable glyphs.
5. Use text extraction as a secondary check. Layout fidelity requires the PNG pass.
6. When claims draw disagreement, `document-interrogate` the content before delivery.
7. Deliver when the latest PNG inspection shows zero visual or formatting defects worth fixing. Clean up `tmp/document-pdfs/` when done.

**Reply:** output path, page count, what you checked visually, open layout risks.
