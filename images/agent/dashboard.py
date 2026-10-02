#!/opt/venv/bin/python
"""Run a dashboard on its fixed container port without changing host networking.

It listens on the container's loopback (127.0.0.1) by default: the Codex
app's SSH connection forwards to that, and nothing else in the container's
network can reach it. --host 0.0.0.0 listens on every container interface."""

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
    parser.add_argument(
        "--host", default="127.0.0.1", help="address to listen on in the container (default: 127.0.0.1)"
    )
    args = parser.parse_args()
    path = Path(args.path).resolve()
    if not path.exists():
        parser.error(f"Application does not exist: {path}")
    port = PORTS[args.framework]
    host = args.host
    try:
        with socket.socket() as probe:
            # As the servers do: a port left in TIME_WAIT by a stopped server
            # is free, a listening one is not. (On Windows SO_REUSEADDR would
            # let the probe share a listening port; this runs in Linux.)
            if os.name == "posix":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind((host, port))
    except OSError:
        parser.error(f"Port {port} is occupied; leave the existing service alone")
    print(f"{args.framework}: container port {port}, bound to {host}; stops with this session.", flush=True)
    print(
        "To open it on the computer, forward the port over the Codex app's SSH "
        "connection; this command publishes no host port.",
        flush=True,
    )
    if args.framework == "shiny":
        os.execvp(
            "Rscript",
            [
                "Rscript",
                "-e",
                "a <- commandArgs(TRUE); shiny::runApp(a[1], host=a[2], port=3838, launch.browser=FALSE)",
                str(path),
                host,
            ],
        )
    elif args.framework == "streamlit":
        os.execvp(
            "streamlit",
            [
                "streamlit",
                "run",
                str(path),
                f"--server.address={host}",
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
        namespace["app"].run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
