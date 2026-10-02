#!/opt/venv/bin/python
"""Run a dashboard on its fixed container port without changing host networking."""

import argparse
import os
import runpy
import socket
import sys
from pathlib import Path

PORTS = {"shiny": 3838, "streamlit": 8501, "dash": 8050}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("framework", choices=PORTS)
    parser.add_argument("path", help="Shiny directory or Python application file")
    args = parser.parse_args()
    path = Path(args.path).resolve()
    if not path.exists():
        parser.error(f"Application does not exist: {path}")
    port = PORTS[args.framework]
    try:
        with socket.socket() as probe:
            probe.bind(("0.0.0.0", port))
    except OSError:
        parser.error(f"Port {port} is occupied; leave the existing service alone")
    print(f"{args.framework}: container port {port}, bound to 0.0.0.0; stops with this session.", flush=True)
    print(
        "Host access requires an existing SSH forward or a launcher preview; "
        "this command publishes no host port.",
        flush=True,
    )
    if args.framework == "shiny":
        os.execvp(
            "Rscript",
            [
                "Rscript",
                "-e",
                'shiny::runApp(commandArgs(TRUE)[1], host="0.0.0.0", port=3838, launch.browser=FALSE)',
                str(path),
            ],
        )
    elif args.framework == "streamlit":
        os.execvp(
            "streamlit",
            [
                "streamlit",
                "run",
                str(path),
                "--server.address=0.0.0.0",
                "--server.port=8501",
                "--server.headless=true",
                "--browser.gatherUsageStats=false",
            ],
        )
    else:
        sys.path.insert(0, str(path.parent))
        namespace = runpy.run_path(str(path), run_name="um_codex_dashboard")
        if "app" not in namespace:
            parser.error(
                "Dash file must expose a Dash instance named app; guard standalone app.run with __main__"
            )
        namespace["app"].run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    main()
