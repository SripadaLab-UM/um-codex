"""One launch: relay, networks, gateway, agent, Codex in the terminal, cleanup.

1. Leftovers from a launch whose `um-codex` was killed are removed (by label).
2. The relay starts on 127.0.0.1, on a free port, with a new token.
3. The launch's files are written in its own folder in UM-Codex's data
   folder: gateway.conf, config.toml, launch.md (all mounted read-only) and a
   private env file with the token (deleted as soon as the agent has started).
4. The networks, the gateway and the agent start.
5. `docker exec -it <agent> codex` runs in the person's terminal.
6. When it ends (or anything fails), the containers, networks, launch folder
   and relay go. The setup's Codex home volume stays, so `codex resume` works.

A launch holds a lock file while it runs, so another launch's cleanup can
tell a live launch from a leftover one.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import secrets
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import IO

from umcodex import codex_config, credentials, toolkit
from umcodex.containers import (
    BindMount,
    Docker,
    DockerError,
    LaunchSpec,
    agent_image,
    exec_command,
    images,
    instance_of,
    remove_leftovers,
    render_gateway_conf,
)
from umcodex.folders import Layout
from umcodex.paths import data_dir
from umcodex.relay import Relay, RelayServer, new_token, upstream_base_url
from umcodex.setups import Setup

log = logging.getLogger(__name__)

Say = Callable[[str], None]


# --- Launch locks -----------------------------------------------------------


class LaunchLock:
    """An OS file lock held while a launch runs; the OS lets go if the process dies."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._file: IO[bytes] | None = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            _lock(handle)
        except OSError:
            handle.close()
            return False
        self._file = handle
        return True

    def release(self) -> None:
        if self._file is not None:
            with contextlib.suppress(OSError):
                _unlock(self._file)
            self._file.close()
            self._file = None


def _lock(handle: IO[bytes]) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(handle: IO[bytes]) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def launches_dir(data: Path) -> Path:
    return data / "launches"


def launch_is_live(data: Path, launch_id: str) -> bool:
    """Whether a launch's `um-codex` is still running (it holds its lock)."""
    lock_file = launches_dir(data) / launch_id / "lock"
    if not lock_file.exists():
        return False
    probe = LaunchLock(lock_file)
    if probe.acquire():
        probe.release()
        return False
    return True


# A launch folder younger than this is never removed as stale: its launch may
# have made the folder and not yet taken its lock.
STALE_AFTER_SECONDS = 120


def remove_stale_launch_folders(data: Path, now: float | None = None) -> None:
    folder = launches_dir(data)
    if not folder.is_dir():
        return
    now = time.time() if now is None else now
    for entry in folder.iterdir():
        try:
            young = now - entry.lstat().st_mtime < STALE_AFTER_SECONDS
        except OSError:
            continue
        if entry.is_dir() and not entry.is_symlink() and not young and not launch_is_live(data, entry.name):
            shutil.rmtree(entry, ignore_errors=True)


def image_command(docker: Docker, image: str) -> tuple[str, ...]:
    """The agent image's own command, for the watchdog to run (containers.WATCHDOG).
    Empty when the image has an entrypoint or its command can't be read: then
    it runs as it is, without the watchdog."""
    code, out, _ = docker.status(
        "image", "inspect", "--format", "{{json .Config.Entrypoint}}|{{json .Config.Cmd}}", image
    )
    if code != 0 or "|" not in out:
        return ()
    entrypoint, cmd = out.strip().split("|", 1)
    try:
        parsed = json.loads(cmd)
    except ValueError:
        return ()
    if json.loads(entrypoint or "null") or not isinstance(parsed, list) or not parsed:
        return ()
    return tuple(str(part) for part in parsed)


# --- The launch's files -----------------------------------------------------


def launch_note(setup: Setup, layout: Layout) -> str:
    """launch.md: what this launch shares, for Codex to read first (the
    image's AGENTS.md says so). Plain text."""
    lines = [
        "# This launch",
        "",
        f"Setup: {setup.name}",
        "",
        "## Folders",
        "",
        f"- /work (read, write, delete; Codex starts here) is {layout.working} on the person's computer.",
    ]
    for host, target in layout.writes:
        lines.append(f"- {target} (read, write, delete) is {host} on the person's computer.")
    for host, target in layout.reads:
        lines.append(f"- {target} (read only) is {host} on the person's computer.")
    lines += [f"- Note: {note}" for note in layout.notes]
    lines += [
        "",
        "Changes in the read-write folders happen on the person's computer straight away.",
        "Nothing else on their computer is visible here.",
        "",
        "## Internet",
        "",
        (
            "On: the whole internet is reachable (pip, npm, git, curl work)."
            if setup.internet
            else "Off: only the model is reachable. pip, npm, git clone and curl to the internet will fail."
        ),
        "",
        "## Browser tool",
        "",
        *browser_note(setup),
        "",
        "## Approvals",
        "",
        (
            "never: commands run without asking the person."
            if setup.approvals == "never"
            else "on-request: the person is asked before commands run."
        ),
        "",
    ]
    return "\n".join(lines)


def browser_note(setup: Setup) -> list[str]:
    if not (setup.internet and setup.browser):
        return ["Off: there's no browser tool in this launch."]
    return [
        "On: the `browser` MCP tools (Playwright) drive a headless Chromium inside this",
        "container, with a fresh profile and none of the person's logins.",
        (
            "The person approves each browser action (opening pages, clicking, typing);"
            " reading the page (snapshot, screenshot, find) runs without asking."
            if setup.browser_asks
            else "Browser actions run without asking the person."
        ),
        "Take a screenshot into /work (with a file name) only when the person asks for one;",
        "unnamed screenshots and page snapshots go in /tmp/um-codex-browser.",
    ]


def _write(path: Path, text: str, mode: int = 0o644) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, mode)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as file:
        file.write(text)


def folder_mounts(layout: Layout) -> tuple[BindMount, ...]:
    mounts = [BindMount(layout.working, "/work", readonly=False)]
    mounts += [BindMount(host, target, readonly=False) for host, target in layout.writes]
    mounts += [BindMount(host, target, readonly=True) for host, target in layout.reads]
    return tuple(mounts)


# --- The launch -------------------------------------------------------------


def run(
    setup: Setup,
    layout: Layout,
    *,
    say: Say = print,
    docker: Docker | None = None,
    codex_args: Sequence[str] = (),
    tty: bool | None = None,
    run_exec: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    api_key: Callable[[], str] = credentials.api_key,
) -> int:
    """Run one launch to the end. Returns Codex's exit code (or 1 if it couldn't start)."""
    docker = docker or Docker()
    data = data_dir()
    instance = instance_of(data)
    if removed := remove_leftovers(docker, instance, lambda launch: launch_is_live(data, launch)):
        log.info("removed %d leftovers of earlier launches", removed)
    remove_stale_launch_folders(data)

    image = agent_image()
    gateway_image = images()["gateway"]
    if not docker.exists("image", image):
        say(f"The agent image {image} isn't on this computer.")
        say("For now (M1) it's built from source: see README.md, 'Run from source'.")
        return 1
    if not docker.exists("image", gateway_image):
        say("Downloading the gateway image (once)...")
        docker("pull", gateway_image, timeout=600)
    if os.environ.get("UMCODEX_UPSTREAM"):
        say("Note: UMCODEX_UPSTREAM is set, so model requests go to a test stub, not the Toolkit.")

    launch_id = secrets.token_hex(4)
    folder = launches_dir(data) / launch_id
    folder.mkdir(parents=True)
    lock = LaunchLock(folder / "lock")
    if not lock.acquire():
        raise RuntimeError("couldn't lock the launch folder")
    server: RelayServer | None = None
    spec: LaunchSpec | None = None

    def remove_containers(timeout: float = 120) -> None:
        if spec is None:
            return
        for command in spec.remove_commands():
            with contextlib.suppress(DockerError):
                docker(*command, check=False, timeout=timeout)

    restore = _exit_on_hangup(remove_containers)
    try:
        token = new_token()
        server = RelayServer(Relay(token, api_key, upstream_base_url(toolkit.BASE_URL)))
        port = server.start()
        log.info("launch %s: relay on 127.0.0.1:%d", launch_id, port)
        spec = LaunchSpec(
            launch_id=launch_id,
            instance=instance,
            setup_id=setup.id,
            agent_image=image,
            gateway_image=gateway_image,
            internet=setup.internet,
            folders=folder_mounts(layout),
            config_file=folder / "config.toml",
            launch_note=folder / "launch.md",
            gateway_conf=folder / "gateway.conf",
            env_file=folder / "agent.env",
            image_cmd=image_command(docker, image),
        )
        # Files the Linux containers read get Unix line ends, on Windows too.
        _write(spec.gateway_conf, render_gateway_conf(port))
        _write(
            spec.config_file,
            codex_config.render(
                model=setup.model,
                approvals=setup.approvals,
                internet=setup.internet,
                browser=setup.browser,
                browser_asks=setup.browser_asks,
            ),
        )
        _write(spec.launch_note, launch_note(setup, layout))
        say("Starting the container...")
        if not docker.exists("volume", spec.volume):
            docker(*spec.volume_command())
        for command in spec.network_commands():
            docker(*command)
        for command in spec.gateway_commands():
            docker(*command)
        env = [
            f"{codex_config.TOKEN_ENV}={token}",
            f"UMCODEX_INTERNET={'on' if setup.internet else 'off'}",
        ]
        _write(spec.env_file, "\n".join(env) + "\n", mode=0o600)
        try:
            for command in spec.agent_commands():
                docker(*command)
        finally:
            spec.env_file.unlink(missing_ok=True)
        if not docker.wait_running(spec.agent) or not docker.wait_running(spec.gateway):
            raise DockerError("the container stopped as soon as it started")
        interactive = sys.stdin.isatty() and sys.stdout.isatty() if tty is None else tty
        command = exec_command(
            spec.agent, tty=interactive, term=os.environ.get("TERM") or "xterm-256color", args=codex_args
        )
        say("Opening Codex. Quit it (Ctrl-C twice, or /quit) to end this launch.")
        say("")
        sys.stdout.flush()
        with _codex_owns_ctrl_c():
            done = run_exec(command)
        return done.returncode
    finally:
        remove_containers()
        if server is not None:
            server.stop()
        restore()
        lock.release()
        shutil.rmtree(folder, ignore_errors=True)
        say("Launch ended; the container was removed. Your setup's Codex history was kept.")


@contextlib.contextmanager
def _codex_owns_ctrl_c():
    """While Codex runs, Ctrl-C is Codex's (the terminal is in raw mode, but a
    stray SIGINT must not end um-codex before it has cleaned up)."""
    previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)


# Windows console events that end the process: Close, Logoff, Shutdown.
_WINDOWS_ENDING_EVENTS = (2, 5, 6)


def on_console_event(event: int, cleanup: Callable[[float], None]) -> bool:
    """Windows: the terminal window is being closed (or the person logs off).
    Windows ends the process about 5 s after this handler starts, so the
    containers are removed with short Docker timeouts. The agent's watchdog
    (containers.WATCHDOG) is the backstop if even that doesn't finish."""
    if event not in _WINDOWS_ENDING_EVENTS:
        return False  # Ctrl-C and Ctrl-Break: Codex's
    with contextlib.suppress(Exception):
        cleanup(2)
    return True


def _exit_on_hangup(cleanup: Callable[[float], None]) -> Callable[[], None]:
    """A closed terminal window (SIGHUP, or Windows' console Close event) or
    SIGTERM still cleans up."""
    if sys.platform == "win32":
        import ctypes

        handler_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)  # type: ignore[attr-defined]
        handler = handler_type(lambda event: 1 if on_console_event(event, cleanup) else 0)
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        kernel32.SetConsoleCtrlHandler(handler, True)

        def restore_windows() -> None:
            kernel32.SetConsoleCtrlHandler(handler, False)  # also keeps `handler` alive until then

        return restore_windows

    def leave(signum, frame):
        raise SystemExit(128 + signum)

    saved = {s: signal.signal(s, leave) for s in (signal.SIGHUP, signal.SIGTERM)}

    def restore() -> None:
        for s, handler in saved.items():
            signal.signal(s, handler)

    return restore
