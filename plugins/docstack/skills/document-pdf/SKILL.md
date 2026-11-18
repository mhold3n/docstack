---
name: document-pdf
description: Read, create, and review PDF files where rendering and layout matter. Prefer visual checks by rendering pages (Poppler). Use reportlab, pdfplumber, and pypdf for generation and extraction. Use for /document-pdf, PDF produce, PDF review, or when layout fidelity matters.
disable-model-invocation: true
---

# PDF

## When to use

- Read or review PDF content where layout and visuals matter.
- Create PDFs programmatically with reliable formatting.
- Check final rendering before delivery.

## Workflow

1. Prefer visual review: render PDF pages to PNGs and inspect them.
   - Use `pdftoppm` if available.
   - If unavailable, install Poppler or ask the user to review the output locally.
2. Use `reportlab` to generate PDFs when creating new documents (or the project's generator when one exists).
3. Use `pdfplumber` (or `pypdf`) for text extraction and quick checks; do not rely on it for layout fidelity.
4. After each meaningful update, re-render pages and verify alignment, spacing, and legibility.

## Temp and output conventions

- Use `tmp/document-pdfs/` for intermediate files; delete when done.
- Write final artifacts under `output/document-pdf/` when the project has no stronger convention.
- Keep filenames stable and descriptive.

## Dependencies (install if missing)

Prefer `uv` for dependency management.

Python packages:

```
uv pip install reportlab pdfplumber pypdf
```

If `uv` is unavailable:

```
python3 -m pip install reportlab pdfplumber pypdf
```

System tools (for rendering):

```
# macOS (Homebrew)
brew install poppler

# Ubuntu/Debian
sudo apt-get install -y poppler-utils
```

If installation is not possible, tell the user which dependency is missing and how to install it locally.

## Rendering command

```
pdftoppm -png $INPUT_PDF $OUTPUT_PREFIX
```

## Quality expectations

- Consistent typography, spacing, margins, and section hierarchy.
- No clipped text, overlapping elements, broken tables, black squares, or unreadable glyphs.
- Charts, tables, and images sharp, aligned, and labeled.
- Use ASCII hyphens. Avoid U+2011 and other Unicode dashes.
- Citations human-readable; never leave tool tokens or placeholder strings.

## Final checks

- Do not deliver until the latest PNG inspection shows zero visual or formatting defects worth fixing.
- Confirm headers/footers, page numbering, and section transitions look polished.
- Keep intermediate files organized or remove them after final approval.
