"""The `um-codex` command. With no command, it launches.

um-codex            choose a setup and open Codex in a container
um-codex setups     list, edit and delete saved setups
um-codex key        save or replace the Toolkit API key
um-codex doctor     check Docker, the images, the key and the Toolkit
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import sys
from pathlib import Path

from umcodex import __version__, credentials, doctor, toolkit
from umcodex.containers import Docker, DockerError, volume_name
from umcodex.paths import data_dir
from umcodex.secret_prompt import ask_secret
from umcodex.setups import Setup, SetupStore, choose, manage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="um-codex",
        description="Codex on U-M GPT Toolkit, in a Docker container. With no command, it launches.",
    )
    parser.add_argument("--version", action="version", version=f"UM-Codex {__version__}")
    commands = parser.add_subparsers(dest="command")
    launch = commands.add_parser("launch", help="choose a setup and open Codex (the default)")
    launch.add_argument("codex_args", nargs=argparse.REMAINDER, help="passed to codex (after --)")
    commands.add_parser("setups", help="list, edit and delete saved setups")
    commands.add_parser("key", help="save or replace the Toolkit API key")
    commands.add_parser("doctor", help="check Docker, the images, the key and the Toolkit")
    args = parser.parse_args(argv)
    _log_to_file()
    try:
        if args.command == "setups":
            return _setups()
        if args.command == "key":
            return 0 if _ask_key() else 1
        if args.command == "doctor":
            return 0 if doctor.report() else 1
        codex_args = [a for a in getattr(args, "codex_args", []) if a != "--"]
        return _launch(codex_args)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130
    except DockerError as error:
        print(f"\nDocker problem: {error}")
        print("Run `um-codex doctor` for details.")
        return 1


def _log_to_file() -> None:
    """Logs go to a file: the terminal belongs to Codex. Nothing secret is logged."""
    folder = data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        folder / "um-codex.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    # httpx logs every request URL at INFO; keep it quiet.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _ask_key() -> bool:
    print("Paste your U-M GPT Toolkit API key. It's saved in this computer's keychain and")
    print("never goes into the container.")
    key = ask_secret("Toolkit API key", what="key")
    if not key:
        return False
    result = toolkit.check_key(key)
    if result == "refused":
        print("The Toolkit refused that key, so it wasn't saved. Check it and try again.")
        return False
    if result in ("unreachable", "error"):
        print("Couldn't check the key with the Toolkit right now (network or VPN?). Saving it anyway.")
    credentials.save_api_key(key)
    print("Saved.")
    return True


def _models() -> list[str]:
    try:
        return toolkit.list_models(credentials.api_key())
    except credentials.MissingCredential:
        return []


def _remove_volume(setup: Setup) -> None:
    try:
        Docker()("volume", "rm", volume_name(setup.id), check=False)
    except DockerError:
        print("Couldn't remove its Codex history from Docker (is Docker running?).")


def _setups() -> int:
    manage(SetupStore(), input, print, models=_models, remove_volume=_remove_volume)
    return 0


def _launch(codex_args: list[str]) -> int:
    from umcodex import launch

    print(f"UM-Codex {__version__}")
    if not doctor.ensure_docker():
        return 1
    if not credentials.has_api_key():
        print("First, UM-Codex needs your Toolkit API key.")
        if not _ask_key():
            return 1
    chosen = choose(SetupStore(), input, print, start_folder=Path.cwd(), models=_models)
    if chosen is None:
        print("Not started.")
        return 0
    setup, layout = chosen
    return launch.run(setup, layout, codex_args=codex_args)


if __name__ == "__main__":
    sys.exit(main())
