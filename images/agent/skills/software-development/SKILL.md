---
name: software-development
description: Build, debug or review Python, R, Node or web projects in UM-Codex, with targeted tests, offline build tools and maintainable handoffs.
---

# Development in this image

Inspect repository guidance, status, manifests and actual failing behavior
first. Preserve the person's changes. Use the existing architecture and
build/test commands; choose the smallest patch that addresses the task.
For unfamiliar APIs with internet off inspect installed versions and local
help rather than inventing current behavior.

Python: pytest and ruff; R: testthat and lintr; Node: node/npm, tsc and
esbuild. TypeScript can type-check and esbuild can bundle local JS offline.
Frameworks such as React/Vite are not preinstalled: npm ci needs internet
or a prepared project cache. Do not use npx as if it were an offline binary.
Keep package.json/package-lock.json and project node_modules under `/work`
when persistence matters. Never commit node_modules/venvs by default.

For web apps verify actual browser interaction and small-screen layout,
using enabled Playwright MCP or the installed headless Chromium locally.
Keep static assets local for offline use. Test error paths and one realistic
end-to-end flow; do not substitute source inspection for rendered QA.

For fixes add tests that would fail on the original bug, run the relevant
checks, and report commands/results and anything unverified. Review diffs
for accidental data/secret inclusion and scope. Do not commit, push,
deploy, message collaborators or alter remote settings without user
instructions. Long tasks benefit from a concise project progress/handoff
file when requested; write concrete next steps and unresolved decisions.
