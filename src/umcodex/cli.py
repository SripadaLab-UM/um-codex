"""The `um-codex` command. With no command, it launches.

um-codex            choose a setup and open Codex in a container
um-codex ui         the launcher window (what the UM-Codex app and shortcuts open)
um-codex launch --setup <id>   start a saved setup without asking (the launcher window's way)
um-codex launch --open app     open Codex in the Codex desktop app instead of this terminal (Mac)
um-codex setups     list, edit and delete saved setups
um-codex key        save or replace the Toolkit API key
um-codex doctor     check Docker, the images, the key and the Toolkit
um-codex update     install a newer signed release (--rollback: back to the one before)
um-codex launchers --refresh   bring the UM-Codex app or shortcuts up to date (update does this)
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import sys
from pathlib import Path

from keyring.errors import KeyringError

from umcodex import __version__, credentials, doctor, toolkit
from umcodex.containers import Docker, DockerError, pull_images, volume_name
from umcodex.folders import FolderRefused, Layout
from umcodex.paths import data_dir
from umcodex.relay import UpstreamRefused
from umcodex.secret_prompt import ask_secret
from umcodex.setups import Setup, SetupStore, check, choose, manage, moved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="um-codex",
        description="Codex on U-M GPT Toolkit, in a Docker container. With no command, it launches.",
    )
    parser.add_argument("--version", action="version", version=f"UM-Codex {__version__}")
    # The metavar leaves out ssh-proxy, which only ssh runs.
    commands = parser.add_subparsers(
        dest="command", metavar="{launch,ui,setups,key,pull,doctor,update,launchers,uninstall}"
    )
    launch = commands.add_parser("launch", help="choose a setup and open Codex (the default)")
    launch.add_argument(
        "--from-app",
        action="store_true",
        help="opened from the UM-Codex app or shortcut: the current folder isn't offered as the working "
        "folder (the last setup's is, or ~/Documents/UM-Codex)",
    )
    launch.add_argument(
        "--setup",
        metavar="SETUP",
        help="start this saved setup (its id or name) without asking anything: what the launcher window runs",
    )
    launch.add_argument(
        "--open",
        choices=["terminal", "app"],
        default="terminal",
        help="where Codex opens: this terminal (the default), or the Codex desktop app (Mac)",
    )
    launch.add_argument("codex_args", nargs=argparse.REMAINDER, help="passed to codex (after --)")
    window = commands.add_parser("ui", help="open the launcher window (in your browser)")
    window.add_argument(
        "--detach", action="store_true", help="run it in the background, with no window (the app's way)"
    )
    window.add_argument(
        "--no-browser", action="store_true", help="don't open the browser: print the sign-in link instead"
    )
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
    update = commands.add_parser("update", help="install a newer signed release beside this one")
    update.add_argument(
        "--rollback", action="store_true", help="switch back to the version in use before the last update"
    )
    links = commands.add_parser(
        "launchers", help="bring the UM-Codex app (Mac) or shortcuts (Windows) up to date"
    )
    which = links.add_mutually_exclusive_group(required=True)
    which.add_argument(
        "--refresh",
        action="store_true",
        help="rewrite UM-Codex's own app or shortcuts, where they are, if they're out of date "
        "(um-codex update does this)",
    )
    which.add_argument(
        "--write",
        nargs="+",
        type=Path,
        metavar="PATH",
        help="for the installers: write the app (a .app folder) or shortcuts (.lnk files) at PATH",
    )
    links.add_argument("--dry-run", action="store_true", help="with --refresh: only say what would change")
    remove = commands.add_parser("uninstall", help="remove UM-Codex's containers, key, images and data")
    data = remove.add_mutually_exclusive_group()
    data.add_argument("--delete-data", action="store_true", help="also delete saved setups and Codex history")
    data.add_argument("--keep-data", action="store_true", help="keep saved setups and Codex history")
    remove.add_argument(
        "--yes", action="store_true", help="don't ask (images are removed; data is kept unless --delete-data)"
    )
    # ssh's ProxyCommand for the Codex app (codex_app.py): not in the help.
    proxy = commands.add_parser("ssh-proxy")
    proxy.add_argument("setup")
    proxy.add_argument("--docker", default="docker")
    proxy.add_argument("--data-dir", type=Path)
    args = parser.parse_args(argv)
    if args.command == "ssh-proxy":
        # stdout is the ssh connection: no log setup, nothing printed.
        from umcodex.codex_app import ssh_proxy

        return ssh_proxy(args.setup, args.docker, args.data_dir)
    if args.command != "uninstall":  # it may delete the data folder the log is in
        _log_to_file()
    try:
        if args.command == "ui":
            from umcodex.ui import server

            _refresh_launchers()
            if args.detach:
                return server.detach(open_browser=not args.no_browser)
            return server.main(open_browser=not args.no_browser)
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
        if args.command == "update":
            from umcodex.update import Updater

            updater = Updater()
            return updater.rollback() if args.rollback else updater.update()
        if args.command == "launchers":
            from umcodex.launchers import Launchers

            if args.dry_run and not args.refresh:
                parser.error("--dry-run goes with --refresh")
            launchers = Launchers()
            report = launchers.write(args.write) if args.write else launchers.refresh(dry_run=args.dry_run)
            return 0 if report.ok else 1
        if args.command == "uninstall":
            from umcodex.uninstall import uninstall

            choice = True if args.delete_data else False if args.keep_data else None
            return uninstall(delete_data=choice, yes=args.yes)
        codex_args = list(getattr(args, "codex_args", []))
        if codex_args[:1] == ["--"]:
            codex_args = codex_args[1:]
        return _launch(
            codex_args,
            from_app=getattr(args, "from_app", False),
            setup_name=getattr(args, "setup", None),
            in_app=getattr(args, "open", "terminal") == "app",
        )
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
_KEY_SHAPE = credentials.KEY_SHAPE


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
    from umcodex import codex_app

    codex_app.forget_setup(setup.id)  # its ssh host for the Codex app, if it had one
    try:
        Docker()("volume", "rm", volume_name(setup.id), check=False)
    except DockerError:
        print("Couldn't remove its Codex history from Docker (is Docker running?).")


def _setups() -> int:
    manage(SetupStore(), input, print, models=_models, remove_volume=_remove_volume)
    return 0


def _update_notice() -> None:
    """One line if a newer release is out (GitHub asked at most once a day, 3 s
    at most). Nothing about it, not even importing it, may stop a launch."""
    try:
        from umcodex.update import launch_notice

        launch_notice()
    except Exception:
        logging.getLogger(__name__).warning("the update check at launch failed", exc_info=True)


def _refresh_launchers() -> None:
    """The app or shortcuts, brought up to date once if an older installer
    wrote them (an update by alpha.1's own updater didn't). Nothing about it
    may stop a launch."""
    try:
        from umcodex.launchers import refresh_if_differs

        refresh_if_differs()
    except Exception:
        logging.getLogger(__name__).warning("refreshing the launchers failed", exc_info=True)


def _launch(
    codex_args: list[str], *, from_app: bool = False, setup_name: str | None = None, in_app: bool = False
) -> int:
    from umcodex import launch

    print(f"UM-Codex {__version__}")
    _refresh_launchers()
    _update_notice()
    app = None
    if in_app:
        from umcodex import codex_app

        app = codex_app.find_app()
        reason = codex_app.unavailable_reason(app=app)
        if reason is not None:
            print(reason)
            return 1
    elif sys.platform == "win32" and not codex_args and not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("This window can't run Codex's screen (Git Bash and mintty can't).")
        print("Use Windows Terminal or PowerShell, then run um-codex again.")
        return 1
    if not doctor.ensure_docker():
        return 1
    if not credentials.has_api_key():
        print("First, UM-Codex needs your Toolkit API key.")
        if _key_command() != KEY_SAVED:
            return 1
    if setup_name is not None:
        chosen = _chosen_without_asking(SetupStore(), setup_name)
        if chosen is None:
            return 1
        if in_app:
            return _launch_in_app(*chosen, app=app)
        return launch.run(*chosen, codex_args=codex_args)
    # From the app, the current folder is wherever Terminal opened (home):
    # not a choice the person made, so it isn't offered.
    start_folder = None if from_app else Path.cwd()
    chosen = choose(SetupStore(), input, print, start_folder=start_folder, models=_models)
    if chosen is None:
        print("Not started.")
        return 0
    setup, layout = chosen
    if in_app:
        return _launch_in_app(setup, layout, app=app)
    return launch.run(setup, layout, codex_args=codex_args)


def _launch_in_app(setup: Setup, layout: Layout, *, app: Path | None) -> int:
    """`launch --open app`: the launch runs here (it holds the relay) while the
    Codex app works in the sandbox. From the launcher window it has no
    terminal: what it says goes to the log too."""
    from umcodex import codex_app, launch

    log = logging.getLogger("umcodex.launch")

    def say(text: str) -> None:
        print(text, flush=True)
        if text.strip():
            log.info("%s", text)

    if not codex_app.include_present():
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            say("The Codex app needs one line in ~/.ssh/config first: open UM-Codex and choose Allow.")
            return 1
        if not codex_app.ask_for_include(input, say):
            return 1
    docker = Docker()
    if codex_app.app_launch_running(docker, setup.id):
        say(f"“{setup.name}” is already running in the Codex app. Stop it in UM-Codex first.")
        return 1
    hold = codex_app.AppHold(setup.id, say=say, app=app, docker=docker)
    return launch.run(setup, layout, say=say, docker=docker, hold=hold)


def _chosen_without_asking(store: SetupStore, wanted: str) -> tuple[Setup, Layout] | None:
    """`launch --setup`: the saved setup (by id, else by name), its folders
    checked again. The launcher window already showed the summary and, for a
    folder that now leads somewhere else, had the person confirm it (and saved
    the setup with the folder as it resolves), so nothing is asked here: a
    refused or moved folder stops the launch."""
    setups = store.all()
    setup = next((s for s in setups if s.id == wanted), None) or next(
        (s for s in setups if s.name == wanted), None
    )
    if setup is None:
        print(f"There's no saved setup called “{wanted}”. Open UM-Codex to choose one.")
        return None
    print(f"Setup: {setup.name}")
    try:
        layout = check(setup)
        changed = moved(setup)
    except FolderRefused as refused:
        print(f"This setup can't be used as it is: {refused}")
        print("Open UM-Codex and edit the setup.")
        return None
    if changed:
        print("A saved folder now leads somewhere else (a link was put in its path):")
        for saved, now in changed:
            print(f"  {saved}")
            print(f"    now goes to {now}")
        print("Not started. Open UM-Codex and start the setup there to check and confirm it.")
        return None
    store.mark_used(setup.id)
    return setup, layout


if __name__ == "__main__":
    sys.exit(main())
