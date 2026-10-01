"""The `um-codex` command. With no command, it launches.

um-codex            choose a setup and open Codex in a container
um-codex launch --from-app   the same, from the UM-Codex app or shortcut
um-codex setups     list, edit and delete saved setups
um-codex key        save or replace the Toolkit API key
um-codex doctor     check Docker, the images, the key and the Toolkit
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import re
import sys
from pathlib import Path

from keyring.errors import KeyringError

from umcodex import __version__, credentials, doctor, toolkit
from umcodex.containers import Docker, DockerError, pull_images, volume_name
from umcodex.paths import data_dir
from umcodex.relay import UpstreamRefused
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
    launch.add_argument(
        "--from-app",
        action="store_true",
        help="opened from the UM-Codex app or shortcut: the current folder isn't offered as the working "
        "folder (the last setup's is, or ~/Documents/UM-Codex)",
    )
    launch.add_argument("codex_args", nargs=argparse.REMAINDER, help="passed to codex (after --)")
    commands.add_parser("setups", help="list, edit and delete saved setups")
    key = commands.add_parser("key", help="save or replace the Toolkit API key")
    key.add_argument(
        "--from-stdin", action="store_true", help="read the key from standard input (for the installers)"
    )
    commands.add_parser("pull", help="pull the pinned images (agent and gateway)")
    check = commands.add_parser("doctor", help="check Docker, the images, the key and the Toolkit")
    check.add_argument("--quiet", action="store_true", help="exit code only, and one line on failure")
    check.add_argument(
        "--fix-docker", action="store_true", help="open Docker Desktop; on Windows, offer the logon-right fix"
    )
    remove = commands.add_parser("uninstall", help="remove UM-Codex's containers, key, images and data")
    data = remove.add_mutually_exclusive_group()
    data.add_argument("--delete-data", action="store_true", help="also delete saved setups and Codex history")
    data.add_argument("--keep-data", action="store_true", help="keep saved setups and Codex history")
    remove.add_argument(
        "--yes", action="store_true", help="don't ask (images are removed; data is kept unless --delete-data)"
    )
    args = parser.parse_args(argv)
    if args.command != "uninstall":  # it may delete the data folder the log is in
        _log_to_file()
    try:
        if args.command == "setups":
            return _setups()
        if args.command == "key":
            return _key_command(from_stdin=args.from_stdin)
        if args.command == "pull":
            return 0 if pull_images() else 1
        if args.command == "doctor":
            if args.fix_docker:
                return 0 if doctor.fix_docker() else 1
            return 0 if doctor.report(quiet=args.quiet) else 1
        if args.command == "uninstall":
            from umcodex.uninstall import uninstall

            choice = True if args.delete_data else False if args.keep_data else None
            return uninstall(delete_data=choice, yes=args.yes)
        codex_args = list(getattr(args, "codex_args", []))
        if codex_args[:1] == ["--"]:
            codex_args = codex_args[1:]
        return _launch(codex_args, from_app=getattr(args, "from_app", False))
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130
    except EOFError:
        # A question with nothing to answer it (no terminal): taken as no.
        print("\nNo answer (there's no terminal to type in), so nothing more was done.")
        return 1
    except UpstreamRefused as error:
        print(error)
        return 1
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


KEY_SAVED, KEY_REFUSED, KEY_CANCELLED = 0, 1, 2
_KEY_SHAPE = re.compile(r"[\x21-\x7e]{8,512}")


def _key_command(*, from_stdin: bool = False) -> int:
    """`um-codex key`: 0 saved, 1 refused or invalid (or the keychain failed), 2 cancelled."""
    try:
        return _key_steps(from_stdin=from_stdin)
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled: nothing was saved.")
        return KEY_CANCELLED


def _key_steps(*, from_stdin: bool) -> int:
    if from_stdin:
        # One line; a Windows pipe may start with a UTF-8 byte order mark.
        key = sys.stdin.readline().lstrip("\ufeff").strip()
    else:
        print("Paste your U-M GPT Toolkit API key. It's saved in this computer's keychain and")
        print("never goes into the container.")
        key = ask_secret("Toolkit API key", what="key")
    if not key:
        if from_stdin:
            print("No key was given, so nothing was saved.")
        return KEY_CANCELLED
    if not _KEY_SHAPE.fullmatch(key):
        print("That doesn't look like an API key (it has spaces or unusual characters), so it wasn't saved.")
        return KEY_REFUSED
    result = toolkit.check_key(key)
    if result == "refused":
        print("The Toolkit refused that key, so it wasn't saved. Check it and try again.")
        return KEY_REFUSED
    try:
        credentials.save_api_key(key)
    except KeyringError:
        print("The key couldn't be saved: this computer's keychain refused it or isn't available.")
        print("Unlock the keychain (or sign in to Windows normally) and try again.")
        return KEY_REFUSED
    if result == "unreachable":
        print(
            "Couldn't reach the Toolkit to check the key (no network, or off the VPN?). It was saved anyway."
        )
    elif result == "error":
        print("The Toolkit couldn't check the key just now (it answered with an error). It was saved anyway.")
    else:
        print("The Toolkit accepted the key.")
    print("Saved in the keychain.")
    return KEY_SAVED


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


def _launch(codex_args: list[str], *, from_app: bool = False) -> int:
    from umcodex import launch

    print(f"UM-Codex {__version__}")
    if sys.platform == "win32" and not codex_args and not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("This window can't run Codex's screen (Git Bash and mintty can't).")
        print("Use Windows Terminal or PowerShell, then run um-codex again.")
        return 1
    if not doctor.ensure_docker():
        return 1
    if not credentials.has_api_key():
        print("First, UM-Codex needs your Toolkit API key.")
        if _key_command() != KEY_SAVED:
            return 1
    # From the app, the current folder is wherever Terminal opened (home):
    # not a choice the person made, so it isn't offered.
    start_folder = None if from_app else Path.cwd()
    chosen = choose(SetupStore(), input, print, start_folder=start_folder, models=_models)
    if chosen is None:
        print("Not started.")
        return 0
    setup, layout = chosen
    return launch.run(setup, layout, codex_args=codex_args)


if __name__ == "__main__":
    sys.exit(main())
