---
name: scientific-figures
description: Create publication figures and exploratory plots with labeled units, uncertainty, accessible colors and export verification.
---

# Scientific figures

Match chart choice to the question and observation unit. Show denominators,
units, uncertainty and relevant sample sizes; distinguish repeated records
from independent observations. Verify plotted values against the result
table and flag missing/imputed measurements. Prefer direct labels and
colorblind-friendly palettes; do not communicate categories by color alone.

Use matplotlib/seaborn/plotnine, ggplot2 or Plotly/Altair as appropriate.
Export vector SVG/PDF for publication and PNG at the requested physical size
and resolution; embed fonts or choose installed DejaVu/Liberation fonts.
Plotly HTML and Altair HTML can use inline resources for offline viewing;
external tile maps/CDN scripts require internet and need disclosure.

Inspect the rendered output for clipped labels, unreadable text, misleading
axes, legends and layout. Headless Chromium can screenshot a local HTML
plot; static PNGs can be inspected with the image tool if available.
`pdftoppm` can render a PDF for inspection. Preserve plotting code and the
source table, record export settings, and report any format not visually
verified. Scientific plots should be data-derived, not AI-generated raster
illustrations.
