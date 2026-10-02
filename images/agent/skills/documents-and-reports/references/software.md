# Optional software by task

Inspect what is installed (`command -v`, package versions) first. Internet-off
sessions cannot fetch missing tools. Give an exact missing capability and a
project-local installation plan; do not repeatedly retry downloads. Preserve
existing environments and ask before introducing substantial downloads/cost.
Pin versions actually verified for the task, record license/runtime needs,
and rerun a representative check. Do not paste secrets into install commands.

| Task | Bundled starting point | Optional addition and limitation |
|---|---|---|
| Quarto PDF via LaTeX | Quarto, Pandoc; HTML/DOCX offline | TinyTeX/TeX Live, downloaded with internet on; save a reusable installation on a writable mount, configure PATH and validate `quarto check` |
| Office visual rendering | python-docx/pptx, officer; PDF inspection tools | LibreOffice headless via apt, internet on, ephemeral install unless included in a future image; verify converted pages visually |
| GPU/deep learning | NumPy/scikit-learn CPU | Pin PyTorch/JAX in project venv for actual platform; this Docker image promises no GPU access, CUDA or Apple Metal |
| Neuroimaging/genomics | Python/R general statistics | Domain-specific tools such as nibabel, MNE, Bioconductor or system pipelines; check data formats, licensing, size and architecture before installing |
| JS frontend frameworks | Node, TypeScript, esbuild | React/Vite/etc in package.json with package-lock.json; npm ci online or prepared cache offline |
| New Python packages | uv and image scientific stack | uv-managed project lock; wheelhouse for offline isolated reuse |
| New R packages | renv, dated CRAN repository | Project renv library/lock; downloads need internet; Bioconductor compatibility follows R version |
| Remote data services | HTTP clients, DBI, SQLite/DuckDB | Separate service authorization and driver/network access; installed software does not grant permissions |

The image already has Chromium for local rendering. A Python Playwright
client is not assumed; Node can use the installed MCP package's Playwright
via `require('/usr/local/lib/node_modules/@playwright/mcp/node_modules/playwright')`.
Use its Chromium executable cache through PLAYWRIGHT_BROWSERS_PATH. Keep
inspection artifacts under the project only when requested/needed.
