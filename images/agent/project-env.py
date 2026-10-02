#!/opt/venv/bin/python
"""Create a persistent Python environment without downloads or overwrites."""

import argparse
import shlex
import shutil
import subprocess
import sysconfig
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default=".venv")
    parser.add_argument(
        "--image-packages", action="store_true", help="use bundled packages as an offline fallback"
    )
    args = parser.parse_args()
    requested = Path(args.path).expanduser().absolute()
    if requested.exists() or requested.is_symlink():
        parser.error(f"{requested} already exists; inspect and reuse it rather than replacing it")
    target = requested.resolve()
    subprocess.run(["uv", "venv", "--offline", "--python", "/usr/bin/python3", str(target)], check=True)
    if args.image_packages:
        purelib = subprocess.check_output(
            [str(target / "bin/python"), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
            text=True,
        ).strip()
        # The image's /opt/venv is itself a venv, so --system-site-packages
        # alone would NOT expose its packages. A .pth adds a fallback after
        # the project library, and is transparent about the dependency.
        (Path(purelib) / "um-codex-image.pth").write_text(sysconfig.get_path("purelib") + "\n")
        shutil.copyfile("/opt/um-codex/python-requirements.txt", target / "um-codex-image-requirements.txt")
    print(f"Environment: {target}\nActivate: . {shlex.quote(str(target / 'bin/activate'))}")
    if args.image_packages:
        print("Uses image packages as a fallback. Persists here, but needs the same image to reproduce them.")
    else:
        print("Isolated environment. Installing new dependencies requires internet or a project wheelhouse.")


if __name__ == "__main__":
    main()
