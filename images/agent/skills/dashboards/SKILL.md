---
name: dashboards
description: Build, run and verify local Shiny, Streamlit or Dash dashboards on fixed container ports, with offline assets and honest host access instructions.
---

# Local dashboards

Inspect the target audience, dataset and existing app. Use synthetic data
when exercising a workflow that would expose private records. Build useful
filters, clear units/denominators, empty/loading/error states and accessible
labels. Keep transformations in testable functions and avoid reading an
entire large dataset on every UI event.

Run from `/work` using the chosen project environment. The bundled helper
runs in the foreground and refuses occupied ports:

| Framework | Command | Container port |
|---|---|---|
| R Shiny | `um-codex-dashboard shiny app-directory` | 3838 |
| Streamlit | `um-codex-dashboard streamlit app.py` | 8501 |
| Dash | `um-codex-dashboard dash app.py` | 8050 |

The helper listens on the container's loopback (`127.0.0.1`), with
debug/reloader/browser launch off; `--host 0.0.0.0` is needed only when
something else in the container network must reach it. Dash files
must expose `app = Dash(...)` and guard direct `app.run()` under `__main__`.
Avoid naming the app `dash.py` or `streamlit.py`: these can shadow the
installed packages. For a custom project venv use that environment's Streamlit or Python and
set the same host/port explicitly; the helper's Python is the image venv.
Shiny uses the active project's renv when started from its root.

Report the framework, **container port**, run command and server lifetime.
Keep process IDs/logs for servers you start; stop only your processes.
A Docker container port is not automatically a host URL. UM-Codex publishes
no dashboard ports. When the person uses the Codex app (a Remote chat on
this container), its SSH connection allows local forwarding to the
container's loopback. On their computer, using the exact Remote host shown
in the app, they may run:
`ssh -N -L 127.0.0.1:8501:127.0.0.1:8501 <remote-host>`
then open `http://127.0.0.1:8501`. Use 3838/8050 for the other frameworks.
Do not run host commands inside the container, invent a remote alias, or
publish ports to the LAN. A terminal-only session has no host forwarding;
offer static HTML exports, or tell the person to open the setup in the
Codex app to preview it. If a host port is occupied use a free host-side
port while retaining the fixed container-side port.

Check health/HTTP from inside the container, then use bundled Chromium or
the enabled browser MCP to verify real interactions, responsive sizing and
console errors. With browser MCP disabled/offline, Chromium can still
render localhost via a local script; do not change the person's browser
setting. HTTP success alone is not UI QA. Keep CDN fonts/scripts/map tiles
out of offline apps. A local server is a preview, not a production deployment;
authentication, TLS and hosting need their own authorized work.
