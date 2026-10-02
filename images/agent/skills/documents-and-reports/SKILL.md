---
name: documents-and-reports
description: Create or edit reproducible Quarto reports, Markdown, Word, PDF, PowerPoint or spreadsheet deliverables using the bundled authoring tools.
---

# Reports and office artifacts

Inspect the person's template and existing document before editing. Preserve
required sections, styles, comments and content; clarify only gaps that
materially block a correct deliverable. Keep calculations in scripts or
notebooks and show data provenance, units and denominators in the report.

Quarto is preinstalled for executable `.qmd` reports. Use project-relative
paths; choose Jupyter/Python or knitr/R intentionally. For offline HTML set
`format: {html: {embed-resources: true}}` and avoid CDN assets and web fonts.
Embedding resources does not supply missing fonts or math libraries; check
equations and resource loading in an offline browser. Render with
`quarto render report.qmd --to html` or `--to docx`; execute code
from a clean session. Jupyter kernels must point to the chosen environment.
PDF via LaTeX needs a separately installed TeX distribution; do not run
`quarto install tinytex` with internet off. For ordinary HTML-to-PDF,
bundled Chromium can print local HTML; test pagination and fonts. Pandoc,
poppler, qpdf and Ghostscript support conversion and inspection.

Office tools already available: python-docx/officer/flextable for Word,
python-pptx for PowerPoint, openpyxl/xlsxwriter for XLSX, pypdf/pdfplumber
for PDF, and Tesseract for OCR. OCR is fallible: check identifiers, numbers
and tables against page images. openpyxl writes formulas but does not
calculate them; supply verified cached values or explain recalculation.
LibreOffice is optional for Office rendering; see the software guide.

Inspect HTML locally, render PDF pages to images, and verify output text,
page count, tables, margins and overflow. Structural ZIP/XML checks alone
do not establish visual Office QA. If no renderer is installed, report
that limit precisely. Deliver editable source alongside final files and
include exact rerun commands. See [optional software](references/software.md)
only when the requested output needs an additional stack.
