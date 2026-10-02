#!/opt/venv/bin/python
"""Offline execution checks for the bundled authoring and dashboard stack."""

import json
import os
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path


def run(*args, cwd):
    subprocess.run(args, cwd=cwd, check=True, stdout=subprocess.DEVNULL)


def main():
    with tempfile.TemporaryDirectory(prefix="um-codex-capabilities-") as directory:
        root = Path(directory)
        run("um-codex-env", str(root / ".venv"), "--image-packages", cwd=root)
        run(str(root / ".venv/bin/python"), "-c", "import pandas,streamlit,dash,ipykernel", cwd=root)
        # Both bundled JS build tools must compile, not only print a version.
        (root / "build.ts").write_text("const answer: number = 42; console.log(answer);\n")
        run("tsc", "--strict", "--target", "ES2022", "--outDir", "compiled", "build.ts", cwd=root)
        assert subprocess.check_output(["node", "compiled/build.js"], cwd=root, text=True).strip() == "42"
        run("esbuild", "build.ts", "--bundle", "--platform=node", "--outfile=bundled.js", cwd=root)
        assert subprocess.check_output(["node", "bundled.js"], cwd=root, text=True).strip() == "42"
        notebook = {
            "nbformat": 4,
            "nbformat_minor": 5,
            "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"}},
            "cells": [
                {
                    "cell_type": "code",
                    "id": "smoke",
                    "metadata": {},
                    "source": "print(6 * 7)",
                    "execution_count": None,
                    "outputs": [],
                }
            ],
        }
        (root / "smoke.ipynb").write_text(json.dumps(notebook))
        run(
            "jupyter",
            "nbconvert",
            "--execute",
            "--to",
            "notebook",
            "--output",
            "executed.ipynb",
            "--ExecutePreprocessor.timeout=60",
            "smoke.ipynb",
            cwd=root,
        )
        assert "42" in (root / "executed.ipynb").read_text()
        (root / "report.qmd").write_text(
            "---\ntitle: Offline smoke\nformat:\n  html:\n    embed-resources: true\n---\n"
            "\n```{python}\nprint(6 * 7)\n```\n"
        )
        run("quarto", "render", "report.qmd", cwd=root)
        assert "42" in (root / "report.html").read_text()
        run("quarto", "render", "report.qmd", "--to", "docx", cwd=root)
        assert (root / "report.docx").stat().st_size > 1000
        # Copy the installed R packages into the project library; no cache
        # symlinks or network are needed. Validate in a second R process.
        run(
            "Rscript",
            "-e",
            "image_libraries <- .libPaths(); renv::init(bare=TRUE, settings=list(use.cache=FALSE)); "
            'renv::hydrate(packages="shiny", sources=image_libraries); '
            'renv::snapshot(packages=c("renv", "shiny"), prompt=FALSE)',
            cwd=root,
        )
        run(
            "Rscript",
            "-e",
            'stopifnot(requireNamespace("shiny")); stopifnot(startsWith(find.package("shiny"), getwd()))',
            cwd=root,
        )
        (root / "streamlit-app.py").write_text(
            'import streamlit as st\nst.title("Smoke")\n'
            'if st.button("Run check"): st.write("Interaction passed")\n'
        )
        (root / "dash-app.py").write_text(
            "from dash import Dash, html, Input, Output\napp = Dash(__name__)\n"
            'app.layout = html.Div([html.H1("Smoke"), html.Button("Run check", id="run"), '
            'html.Div(id="result")])\n'
            '@app.callback(Output("result", "children"), Input("run", "n_clicks"))\n'
            'def check(n): return "Interaction passed" if n else "Ready"\n'
        )
        shiny = root / "shiny"
        shiny.mkdir()
        (shiny / "app.R").write_text(
            'shiny::shinyApp(shiny::fluidPage(shiny::h1("Smoke"), '
            'shiny::actionButton("run", "Run check"), shiny::textOutput("result")), '
            "function(input, output, session) { shiny::observeEvent(input$run, "
            '{ output$result <- shiny::renderText("Interaction passed") }) })\n'
        )
        for framework, port, route, app in [
            ("shiny", 3838, "/", shiny),
            ("streamlit", 8501, "/_stcore/health", root / "streamlit-app.py"),
            ("dash", 8050, "/_dash-layout", root / "dash-app.py"),
        ]:
            with (root / f"{framework}.log").open("w+") as log:
                proc = subprocess.Popen(
                    ["um-codex-dashboard", framework, str(app)],
                    cwd=root,
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                )
                try:
                    deadline = time.monotonic() + 45
                    while True:
                        try:
                            with urllib.request.urlopen(
                                f"http://127.0.0.1:{port}{route}", timeout=2
                            ) as response:
                                assert response.status == 200
                            run("um-codex-dashboard-check", f"http://127.0.0.1:{port}", cwd=root)
                            break
                        except OSError:
                            if proc.poll() is not None or time.monotonic() > deadline:
                                log.seek(0)
                                raise RuntimeError(f"{framework} did not start: {log.read()}") from None
                            time.sleep(0.25)
                finally:
                    os.killpg(proc.pid, 15) if proc.poll() is None else None
                    try:
                        proc.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        os.killpg(proc.pid, 9)
                        proc.wait(timeout=5)
        print("offline environment, R library, notebook, Quarto HTML/DOCX and three dashboards passed")


if __name__ == "__main__":
    main()
