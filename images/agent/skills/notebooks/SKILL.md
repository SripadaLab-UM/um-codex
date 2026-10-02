---
name: notebooks
description: Create, execute or repair Jupyter notebooks and their kernels, including reproducible offline execution and HTML exports (headless; no Jupyter server installed).
---

# Executable notebooks

Inspect existing kernels and project dependencies. Use nbformat rather than
hand-assembled notebook JSON for authoring, with small purposeful cells,
explicit inputs/outputs and no reliance on hidden execution state. Keep raw
data out of committed cell outputs when it contains personal information.

For a project Python environment register a persistent kernelspec:
`.venv/bin/python -m ipykernel install --prefix /work/.jupyter --name project --display-name "Project Python"`.
For this session set `JUPYTER_PATH=/work/.jupyter/share/jupyter` and verify
`jupyter kernelspec list`; the selected kernel must execute the intended
Python. This avoids kernelspecs disappearing in the ephemeral home.
Use project-relative paths so relocation is possible.

Execute a copy from a clean kernel with
`jupyter nbconvert --execute --to notebook --output executed.ipynb --ExecutePreprocessor.timeout=300 analysis.ipynb`.
Verify results, warnings and execution order; export HTML when requested.
Do not silently overwrite the original notebook or erase its outputs.
An execution timeout is not an instruction to skip failing cells.

The image has the kernel (ipykernel), nbformat, nbclient and nbconvert:
notebooks are authored, executed and exported headless. No Jupyter server,
JupyterLab or Notebook is installed; the person can open the `.ipynb` in
their own editor or VS Code. If they need a server here, it needs
internet to install (`uv pip install jupyterlab` into the project's
environment); keep token authentication on, listen on `127.0.0.1`, and use
the Codex app's SSH port forward for host access. Never print its token
into a shared handoff. New kernels and libraries may require internet.
Large outputs belong in data files, not embedded notebook blobs.
