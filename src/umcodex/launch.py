"""One launch: relay, networks, gateway, agent, Codex in the terminal, cleanup.

1. Leftovers from a launch whose `um-codex` was killed are removed (by label).
2. The relay starts on 127.0.0.1, on a free port, with a new token.
3. The launch's files are written in its own folder in UM-Codex's data
   folder: gateway.conf, launch.md, Codex's enforced settings in codex/ (all
   mounted read-only; see codex_config.py) and a private env file with the
   token (deleted as soon as the agent has started).
4. The networks, the gateway and the agent start.
5. `docker exec -it <agent> codex` runs in the person's terminal; or, for a
   setup opened in the Codex app (codex_app.py), a `hold` step prepares the
   container for the app's ssh connection and waits until the launch is
   stopped.
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
import re
import secrets
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Protocol

from umcodex import codex_config, credentials, locks, toolkit
from umcodex.containers import (
    INSTANCE_LABEL,
    LAUNCH_LABEL,
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

    def acquire(self, *, tries: int = 1, wait: float = 0.05) -> bool:
        """Take the lock. `tries` > 1 waits a little between tries: another
        process may be probing it for a moment (launch_is_live)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(tries):
            handle = self.path.open("a+b")
            try:
                _lock(handle)
            except OSError:
                handle.close()
                if attempt + 1 < tries:
                    time.sleep(wait)
                continue
            self._file = handle
            return True
        return False

    def release(self) -> None:
        if self._file is not None:
            with contextlib.suppress(OSError):
                _unlock(self._file)
            self._file.close()
            self._file = None


_lock = locks.lock
_unlock = locks.unlock


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


# --- Running launches (for the launcher window) -----------------------------

LAUNCH_INFO = "launch.json"


@dataclass(frozen=True)
class RunningLaunch:
    launch_id: str
    setup_id: str
    setup_name: str
    started_at: float  # seconds since the epoch
    # A launch in the Codex app: {"alias", "connected", "first_time", "steps",
    # "notes", "copy"} (codex_app.AppHold); None in a terminal.
    app: dict | None = None


def write_launch_info(
    folder: Path, setup: Setup, started_at: float | None = None, *, app: dict | None = None
) -> None:
    """What the launcher window shows about a running launch."""
    info = {
        "setup_id": setup.id,
        "setup_name": setup.name,
        "started_at": time.time() if started_at is None else started_at,
        **({"app": app} if app is not None else {}),
    }
    _write_info(folder, info)


def update_launch_app(folder: Path, app: dict) -> None:
    """Change the Codex app part of a running launch's launch.json."""
    info = json.loads((folder / LAUNCH_INFO).read_text(encoding="utf-8"))
    _write_info(folder, {**info, "app": app})


def _write_info(folder: Path, info: dict) -> None:
    """Whole, through a temporary file, so a reader never sees half of it."""
    temporary = folder / f".{LAUNCH_INFO}.{secrets.token_hex(4)}"
    _write(temporary, json.dumps(info) + "\n")
    os.replace(temporary, folder / LAUNCH_INFO)


def running_launches(data: Path) -> list[RunningLaunch]:
    """The launches of this data folder that are running now (each holds its
    lock), the oldest first. A launch that hasn't written its info yet is left
    out until it has."""
    folder = launches_dir(data)
    if not folder.is_dir():
        return []
    found = []
    for entry in folder.iterdir():
        if entry.is_symlink() or not entry.is_dir() or not (entry / LAUNCH_INFO).is_file():
            continue
        try:
            raw = json.loads((entry / LAUNCH_INFO).read_text(encoding="utf-8"))
            launch = RunningLaunch(
                launch_id=entry.name,
                setup_id=str(raw["setup_id"]),
                setup_name=str(raw["setup_name"]),
                started_at=float(raw["started_at"]),
                app=raw["app"] if isinstance(raw.get("app"), dict) else None,
            )
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if launch_is_live(data, entry.name):
            found.append(launch)
    return sorted(found, key=lambda launch: launch.started_at)


def stop_launch(docker: Docker, data: Path, launch_id: str) -> bool:
    """End a running launch from outside it: remove its containers and
    networks, by label (this data folder's, and that launch's), as cleanup
    does. Codex's `docker exec` then ends, and the launch's own `um-codex`
    removes the rest. False if there's no such running launch."""
    if not any(launch.launch_id == launch_id for launch in running_launches(data)):
        return False
    filters = [
        "--filter", f"label={INSTANCE_LABEL}={instance_of(data)}",
        "--filter", f"label={LAUNCH_LABEL}={launch_id}",
    ]  # fmt: skip
    containers = docker("ps", "-a", "-q", *filters, check=False).split()
    if containers:
        docker("rm", "-f", *containers, check=False)
    networks = docker("network", "ls", "-q", *filters, check=False).split()
    if networks:
        docker("network", "rm", *networks, check=False)
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


def write_codex_settings(
    docker: Docker, spec: LaunchSpec, setup: Setup, api_key: Callable[[], str], *, app: bool = False
) -> None:
    """Codex's enforced settings and model catalog (codex_config.py), in the
    folder mounted read-only at /etc/codex. `app`: the launch is opened in
    the Codex app (the token comes from a command; no ChatGPT sign-in)."""
    spec.codex_etc.mkdir()
    bundled = bundled_models(docker, spec)
    catalog = codex_config.model_catalog(bundled, served_models(api_key), setup.model)
    if catalog is None:
        log.warning("launch %s: no model catalog (Codex's model list couldn't be read)", spec.launch_id)
    else:
        _write(spec.codex_etc / codex_config.CATALOG_FILE, catalog)
    _write(
        spec.codex_etc / codex_config.REQUIREMENTS_FILE,
        codex_config.render_requirements(internet=setup.internet, catalog=catalog is not None, app=app),
    )
    _write(
        spec.codex_etc / codex_config.MANAGED_CONFIG_FILE,
        codex_config.render(
            model=setup.model,
            approvals=setup.approvals,
            internet=setup.internet,
            browser=setup.browser,
            browser_asks=setup.browser_asks,
            app=app,
        ),
    )


_IMAGE_ID = re.compile(r"sha256:([0-9a-f]{64})")


def bundled_models(docker: Docker, spec: LaunchSpec) -> str:
    """The agent image's Codex model list (`codex debug models --bundled`), ""
    if it can't be read. Kept in the data folder per image ID, so it's run
    once per image."""
    code, out, _ = docker.status("image", "inspect", "--format", "{{.Id}}", spec.agent_image)
    image_id = _IMAGE_ID.fullmatch(out.strip()) if code == 0 else None
    cache = data_dir() / "codex-models" / f"{image_id.group(1)}.json" if image_id else None
    if cache is not None and cache.is_file():
        with contextlib.suppress(OSError):
            return cache.read_text(encoding="utf-8")
    try:
        code, out, _ = docker.status(*spec.bundled_models_command(), timeout=120)
    except DockerError:
        return ""
    if code != 0:
        return ""
    if cache is not None and codex_config.model_catalog(out, (), "") is not None:
        with contextlib.suppress(OSError):
            cache.parent.mkdir(parents=True, exist_ok=True)
            _write(cache, out)
    return out


def served_models(api_key: Callable[[], str]) -> list[str]:
    """The Toolkit's models, for the catalog; [] if it can't say."""
    try:
        key = api_key()
    except credentials.MissingCredential:
        return []
    return toolkit.list_models(key, timeout=10)


def folder_mounts(layout: Layout) -> tuple[BindMount, ...]:
    mounts = [BindMount(layout.working, "/work", readonly=False)]
    mounts += [BindMount(host, target, readonly=False) for host, target in layout.writes]
    mounts += [BindMount(host, target, readonly=True) for host, target in layout.reads]
    return tuple(mounts)


# --- The launch -------------------------------------------------------------


@dataclass(frozen=True)
class Running:
    """A launch that's up, for a `hold` step (codex_app.AppHold)."""

    spec: LaunchSpec
    relay_port: int
    token: str
    folder: Path  # the launch's folder in the data folder (launch.json is here)
    setup: Setup


class Hold(Protocol):
    labels: tuple[tuple[str, str], ...]

    def __call__(self, running: Running) -> int: ...


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
    hold: Hold | None = None,
) -> int:
    """Run one launch to the end. Returns Codex's exit code (or 1 if it couldn't start).

    `hold` (a setup opened in the Codex app, codex_app.AppHold): its labels go
    on the containers, Codex's settings are the app's (the token from a
    command), and it's called with the running launch in place of
    `docker exec codex`; the launch ends when it returns."""
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
    if not lock.acquire(tries=40):
        raise RuntimeError("couldn't lock the launch folder")
    write_launch_info(folder, setup)
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
            codex_etc=folder / "codex",
            launch_note=folder / "launch.md",
            gateway_conf=folder / "gateway.conf",
            env_file=folder / "agent.env",
            image_cmd=image_command(docker, image),
            extra_labels=hold.labels if hold is not None else (),
        )
        # Files the Linux containers read get Unix line ends, on Windows too.
        _write(spec.gateway_conf, render_gateway_conf(port))
        write_codex_settings(docker, spec, setup, api_key, app=hold is not None)
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
        if hold is not None:
            code = hold(Running(spec=spec, relay_port=port, token=token, folder=folder, setup=setup))
            log.info("launch %s: ended in the Codex app (code %s)", launch_id, code)
            return code
        interactive = sys.stdin.isatty() and sys.stdout.isatty() if tty is None else tty
        command = exec_command(
            spec.agent, tty=interactive, term=os.environ.get("TERM") or "xterm-256color", args=codex_args
        )
        say("Opening Codex. Quit it (Ctrl-C twice, or /quit) to end this launch.")
        say("")
        sys.stdout.flush()
        with _codex_owns_ctrl_c():
            done = run_exec(command)
        log.info("launch %s: Codex ended (exit code %s)", launch_id, done.returncode)
        return done.returncode
    finally:
        if spec is not None:
            log_agent_state(docker, spec.agent, launch_id)
        remove_containers()
        if server is not None:
            server.stop()
        restore()
        lock.release()
        shutil.rmtree(folder, ignore_errors=True)
        say("Launch ended; the container was removed. Your setup's Codex history was kept.")


def log_agent_state(docker: Docker, agent: str, launch_id: str, *, timeout: float = 10) -> None:
    """Before the containers go: how the agent stands (did it exit, why, when)
    and the last lines it printed (the watchdog says when it ends a launch),
    for the log. The container holds no key, so nothing secret is in either."""
    with contextlib.suppress(DockerError):
        code, out, _ = docker.status(
            "inspect", "--format",
            "status={{.State.Status}} exit_code={{.State.ExitCode}} oom_killed={{.State.OOMKilled}} "
            "finished_at={{.State.FinishedAt}}",
            agent, timeout=timeout,
        )  # fmt: skip
        log.info("launch %s: agent %s", launch_id, out.strip() if code == 0 else "already gone")
        if code == 0:
            code, out, err = docker.status("logs", "--tail", "20", agent, timeout=timeout)
            tail = (out + err).strip() if code == 0 else ""
            if tail:
                log.info("launch %s: the agent's last output:\n%s", launch_id, tail[-4000:])


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
        log.info("the launch's terminal closed or it was asked to end (signal %d)", signum)
        raise SystemExit(128 + signum)

    saved = {s: signal.signal(s, leave) for s in (signal.SIGHUP, signal.SIGTERM)}

    def restore() -> None:
        for s, handler in saved.items():
            signal.signal(s, handler)

    return restore
