"""M4, "On this computer" (spike: docs/spikes/2026-10-02-this-computer.md).

Codex's desktop app working directly on the Mac, not in the sandbox: a
second UM-Codex copy of the app, separate from the sandbox copy (M6,
codex_app.py), with its own CODEX_HOME and Electron profile in
`<data>/codex-app-local/`, so local chats and sandbox chats are never in
the same window. Its provider is the Toolkit through a relay on this
computer, on a port fixed per data folder (the copy keeps the config it
started with while it runs), with a token the relay writes at each start
into a file only the person can read; Codex reads it with `auth.command`
and re-reads it every few minutes. The key stays in the keychain, read only
by the relay.

A launch of such a setup (`run_local`, `um-codex launch --setup <id>
--open local`, which the launcher window starts in the background) holds
the relay while the copy is open: it writes the copy's settings, seeds its
state (the project, the welcome flow, the model announcements) while it
isn't running, opens it, and ends when the copy quits. Stop in the launcher
quits the copy (`stop_local`). No Docker.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import socket
import subprocess
import time
import tomllib
import uuid
from collections.abc import Callable, Iterable
from pathlib import Path

import tomli_w

from umcodex.codex_app import ATOMS, GLOBAL_STATE, StateUnknown, _private_write, _replace, read_state
from umcodex.paths import data_dir
from umcodex.relay import Relay, RelayServer, new_token

log = logging.getLogger(__name__)

LOCAL_FOLDER = "codex-app-local"  # in the data folder: this copy's CODEX_HOME, profile, relay files
PORT_FILE = "relay-port"
TOKEN_FILE = "relay-token"
PROVIDER = "toolkit"

# "Full access" (the default) or "this folder only": Codex's own sandbox on
# macOS (Seatbelt), writes limited to the project's folders.
ACCESS = {
    "full": {"sandbox_mode": "danger-full-access"},
    "folder": {"sandbox_mode": "workspace-write"},
}

# The caution dialog's text (the launcher window shows it when the choice is made).
WARNING = (
    "Codex will run on your Mac, not in the sandbox. It can read, change and delete any of "
    "your files, use your apps and browser, and act with your accounts. While it runs, it may "
    "also be able to reach UM-Codex's own Toolkit key (it runs as you). Use it only when you "
    "need computer or browser control."
)

# The bundled plugins behind "computer and browser control" (the app's
# `openai-bundled` marketplace): Computer Use, the in-app browser, Chrome.
CONTROL_PLUGINS = ("computer-use", "browser", "chrome")
MARKETPLACE = "openai-bundled"

NOTES = (
    "This window runs Codex on your Mac, not in the sandbox: it can do anything you can do here.",
    'Computer Use asks macOS once for Screen Recording and Accessibility, for "Codex Computer Use". '
    "Grant them in System Settings only if you want Codex to see and use your apps.",
    "Chrome control needs the ChatGPT extension in Chrome (Settings > Computer Use in this window).",
    "Quit this window (or Stop in UM-Codex) when you're done: the relay to the Toolkit ends with it.",
)


def local_folder(data: Path | None = None) -> Path:
    return (data or data_dir()) / LOCAL_FOLDER


def copy_paths(data: Path | None = None) -> tuple[Path, Path]:
    """This copy's CODEX_HOME and Electron profile (never the sandbox copy's)."""
    folder = local_folder(data)
    return folder / "codex-home", folder / "user-data"


def open_command(app: Path, data: Path | None = None, link: str | None = None) -> list[str]:
    """A separate copy of the app, as codex_app.open_command, in this folder."""
    home, user_data = copy_paths(data)
    return [
        "/usr/bin/open", "-n",
        "--env", f"CODEX_HOME={home}",
        "--env", f"CODEX_ELECTRON_USER_DATA_PATH={user_data}",
        str(app),
        "--args", f"--user-data-dir={user_data}",
        *([link] if link else []),
    ]  # fmt: skip


def running_copy(data: Path | None = None, run: Callable[..., subprocess.CompletedProcess] = subprocess.run):
    """The PID of this copy's main process, if it's running."""
    _, user_data = copy_paths(data)
    marker = f"--user-data-dir={user_data}"
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        done = run(["/bin/ps", "-axww", "-o", "pid=,args="], capture_output=True, text=True, timeout=10)
        for line in (done.stdout or "").splitlines():
            pid, _, args = line.strip().partition(" ")
            program = args.split(" --", 1)[0]
            helper = "/Contents/Frameworks/" in program or " --type=" in args
            if marker in args and "/Contents/MacOS/" in program and not helper and pid.isdigit():
                return int(pid)
    return None


# --- The copy's config.toml ----------------------------------------------------------


def local_config(
    existing: str,
    *,
    port: int,
    token_file: Path,
    model: str,
    folders: Iterable[Path],
    access: str = "full",
    approval_policy: str = "on-request",
    internet: bool = True,
    catalog: Path | None = None,
    computer_use: bool | None = None,
) -> str:
    """The local copy's config.toml: the Toolkit through this computer's relay
    (no `requires_openai_auth`, so no sign-in), the default access and
    approvals, the working folders trusted. The app's other settings are kept.
    These are defaults: the person can change them in the app (nothing on a
    Mac enforces settings for one copy only)."""
    if access not in ACCESS:
        raise ValueError(f"unknown access {access!r}")
    config = tomllib.loads(existing) if existing.strip() else {}
    providers = config.get("model_providers")
    providers = providers if isinstance(providers, dict) else {}
    providers[PROVIDER] = {
        "name": "U-M GPT Toolkit (through UM-Codex)",
        "base_url": f"http://127.0.0.1:{port}/relay/v1",
        "wire_api": "responses",
        "request_max_retries": 1,
        "stream_max_retries": 2,
        "stream_idle_timeout_ms": 300000,
        # Re-read every 5 minutes: the relay writes a new token when it restarts.
        "auth": {"command": "/bin/cat", "args": [str(token_file)], "refresh_interval_ms": 300000},
    }
    projects = config.get("projects")
    projects = projects if isinstance(projects, dict) else {}
    for folder in folders:
        projects[str(folder)] = {"trust_level": "trusted"}
    config.update(
        {
            "model_provider": PROVIDER,
            "forced_login_method": "api",
            "check_for_update_on_startup": False,
            "analytics": {"enabled": False},
            "feedback": {"enabled": False},
            "model_providers": providers,
            "projects": projects,
            "approval_policy": approval_policy,
            # The person reviews; "Approve for me" would need a reviewer model the Toolkit doesn't have.
            "approvals_reviewer": "user",
            **ACCESS[access],
        }
    )
    if access == "folder":
        config["sandbox_workspace_write"] = {"network_access": internet}
    else:
        config.pop("sandbox_workspace_write", None)
    if computer_use is not None:
        plugins = config.get("plugins")
        plugins = plugins if isinstance(plugins, dict) else {}
        for name in CONTROL_PLUGINS:
            key = f"{name}@{MARKETPLACE}"
            entry = plugins.get(key)
            if not computer_use:
                plugins[key] = {**(entry if isinstance(entry, dict) else {}), "enabled": False}
            elif isinstance(entry, dict) and entry.get("enabled") is False:
                plugins[key] = {**entry, "enabled": True}  # switched back on: the app's choice again
        if plugins:
            config["plugins"] = plugins
    config["model"] = model
    if catalog is not None:
        config["model_catalog_json"] = str(catalog)
    head = "# UM-Codex sets the provider and defaults here (On this computer); the rest is the app's.\n"
    return head + tomli_w.dumps(config)


# --- The copy's state: the local project, pop-ups seen ---------------------------------


def project_id(folder: Path) -> str:
    """Stable per working folder."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"um-codex-local:{folder}"))


def seeded_state(
    state: dict,
    *,
    name: str,
    folders: Iterable[Path],
    seen_models: Iterable[str] = (),
    now: float | None = None,
) -> dict:
    """`state` with a local project for `folders` (the first is the working
    folder; named `name`) made, or brought up to date, and
    selected, and the welcome flow and the given models' announcements
    marked as seen. Shapes from the app's own schema (26.928: `local-projects`
    entries are {id, name, rootPaths, createdAt, updatedAt}). Raises
    StateUnknown for a shape it doesn't know."""
    now = time.time() if now is None else now
    state = json.loads(json.dumps(state))
    for key, kind in (
        ("local-projects", dict),
        ("project-order", list),
        ("selected-project", dict),
        (ATOMS, dict),
    ):
        value = state.get(key)
        if value is not None and not isinstance(value, kind):
            raise StateUnknown(key)
    roots = [str(f) for f in folders]
    if not roots:
        raise ValueError("a project needs a folder")
    projects = state.setdefault("local-projects", {})
    ms = int(now * 1000)
    pid = project_id(Path(roots[0]))
    mine = projects.get(pid)
    if not isinstance(mine, dict):
        mine = next(
            (
                p
                for p in projects.values()
                if isinstance(p, dict) and (p.get("rootPaths") or [None])[0] == roots[0]
            ),
            None,
        )
    if mine is None:
        mine = {"id": pid, "name": name, "rootPaths": roots, "createdAt": ms, "updatedAt": ms}
        projects[pid] = mine
    elif mine.get("rootPaths") != roots or mine.get("name") != name:
        mine.update({"name": name, "rootPaths": roots, "updatedAt": ms})
    order = state.setdefault("project-order", [])
    if mine["id"] not in order:
        order.insert(0, mine["id"])
    state["selected-project"] = {"type": "local", "projectId": mine["id"]}
    state.setdefault("desktop-first-seen-at-ms", int(now * 1000))
    atoms = state.setdefault(ATOMS, {})
    atoms["electron:onboarding-projectless-completed"] = True
    atoms.setdefault("electron:onboarding-hide-first-new-thread-promos", True)
    atoms.setdefault("chatgpt-migration-announcement-completed-v1", True)
    seen = atoms.setdefault("seen-model-upgrade-list", [])
    if not isinstance(seen, list):
        raise StateUnknown("seen-model-upgrade-list")
    seen.extend(m for m in seen_models if m not in seen)
    sidebar = atoms.setdefault("unified-sidebar-project-order-v1", [])
    if isinstance(sidebar, list) and f"codex:project:{mine['id']}" not in sidebar:
        sidebar.insert(0, f"codex:project:{mine['id']}")
    return state


def seed_copy(home: Path, *, name: str, folders: Iterable[Path], seen_models: Iterable[str] = ()) -> None:
    """Only while the copy isn't running (the app reads the file once at start)."""
    text = json.dumps(seeded_state(read_state(home), name=name, folders=folders, seen_models=seen_models))
    for path in (home / GLOBAL_STATE, home / f"{GLOBAL_STATE}.bak"):
        _replace(path, text.encode("utf-8"), mode=0o644)


# --- The relay for this copy -------------------------------------------------------------


def relay_port(data: Path | None = None) -> int:
    """This data folder's port for the local copy's relay, chosen once and kept."""
    path = local_folder(data) / PORT_FILE
    with contextlib.suppress(OSError, ValueError):
        port = int(path.read_text(encoding="ascii").strip())
        if 1024 < port < 65536:
            return port
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _private_write(path, f"{port}\n")
    return port


class FixedPortRelayServer(RelayServer):
    """RelayServer on a given port (the copy's config points at it)."""

    def __init__(self, relay: Relay, port: int) -> None:
        super().__init__(relay)
        self._fixed = port

    async def _start(self) -> int:
        import httpx
        from aiohttp import web

        self.relay._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=20, read=900, write=120, pool=20), follow_redirects=False
        )
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", self._fixed))
        self._runner = web.AppRunner(self.relay.app(), access_log=None)
        await self._runner.setup()
        await web.SockSite(self._runner, sock).start()
        return self._fixed


class LocalRelay:
    """The local copy's relay, held while the copy runs. Its token is written
    to `relay-token` (0600) for Codex's `auth.command`. `keep_token` (the copy
    is still open, the relay restarted): the token already there is kept, so
    the open copy's chats don't need a new one. The holder removes the file
    (`stop(forget=True)`) when the copy quits."""

    def __init__(
        self, api_key: Callable[[], str], base_url: str, data: Path | None = None, *, keep_token: bool = False
    ) -> None:
        self.data = data or data_dir()
        self.port = relay_port(self.data)
        self.token_file = local_folder(self.data) / TOKEN_FILE
        kept = None
        if keep_token:
            with contextlib.suppress(OSError, UnicodeDecodeError):
                kept = self.token_file.read_text(encoding="utf-8").strip() or None
        self.token = kept or new_token()
        self._server = FixedPortRelayServer(Relay(self.token, api_key, base_url), self.port)

    def start(self) -> int:
        self._server.start()  # OSError if the port is taken (another UM-Codex holds it)
        _private_write(self.token_file, self.token)
        log.info("local copy's relay on 127.0.0.1:%d", self.port)
        return self.port

    def stop(self, *, forget: bool = True) -> None:
        if forget:
            with contextlib.suppress(OSError):
                if self.token_file.read_text(encoding="utf-8") == self.token:
                    self.token_file.unlink()
        self._server.stop()


def wait_while_running(pid: int, poll: float = 2.0, sleep: Callable[[float], None] = time.sleep) -> None:
    """Return when the copy's main process has ended."""
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        except PermissionError:
            pass
        sleep(poll)


# --- The launch: held while the copy is open ------------------------------------------

Say = Callable[[str], None]
Runner = Callable[..., subprocess.CompletedProcess]

UNAVAILABLE_WINDOWS = "On this computer works with the Codex app on a Mac only, for now."


def unavailable_reason(platform: str | None = None, app: Path | None = None) -> str | None:
    """Why "On this computer" can't be used here (None: it can)."""
    import sys

    from umcodex import codex_app

    platform = platform or sys.platform
    if platform != "darwin":
        return UNAVAILABLE_WINDOWS
    return codex_app.unavailable_reason(platform, app)


def project_folders(setup, layout) -> list[Path]:
    """The copy's project: the working folder and the other write folders."""
    return [Path(layout.working), *(Path(host) for host, _ in layout.writes)]


def _open_wait(data: Path, run: Runner, sleep: Callable[[float], None], seconds: float = 30) -> int | None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        pid = running_copy(data, run)
        if pid is not None:
            return pid
        sleep(1)
    return None


def write_copy_files(
    setup, layout, *, data: Path, app: Path | None, port: int, token_file: Path, run: Runner, seed: bool
) -> bool:
    """The copy's config.toml (and model catalog), and, when `seed` (the
    copy isn't running), its state. Returns whether the state was seeded."""
    from umcodex.codex_app import bundled_catalog

    home, user_data = copy_paths(data)
    for folder in (local_folder(data), home, user_data):
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    catalog_path, announced = None, []
    if app is not None:
        catalog, announced = bundled_catalog(app, home, setup.model, run=run)
        if catalog is not None:
            catalog_path = local_folder(data) / "models.json"
            _private_write(catalog_path, catalog)
    config = home / "config.toml"
    existing = ""
    if config.exists():
        try:
            existing = config.read_text(encoding="utf-8")
            tomllib.loads(existing)
        except (UnicodeDecodeError, tomllib.TOMLDecodeError):
            aside = config.with_name(f"config.toml.bad-{time.strftime('%Y%m%d-%H%M%S')}")
            os.replace(config, aside)
            log.warning("the local Codex app copy's config.toml didn't parse; moved it to %s", aside)
            existing = ""
    folders = project_folders(setup, layout)
    _private_write(
        config,
        local_config(
            existing,
            port=port,
            token_file=token_file,
            model=setup.model,
            folders=folders,
            access=setup.local_access,
            approval_policy=setup.approvals,
            internet=setup.internet,
            catalog=catalog_path,
            computer_use=setup.computer_use,
        ),
    )
    if not seed:
        return False
    try:
        seed_copy(home, name=setup.name, folders=folders, seen_models=announced)
    except (StateUnknown, OSError) as error:
        log.warning("the local Codex app copy's state couldn't be set up (%s)", error)
        return False
    return True


def run_local(
    setup,
    layout,
    *,
    say: Say = print,
    app: Path | None,
    data: Path | None = None,
    api_key: Callable[[], str] | None = None,
    base_url: str | None = None,
    run: Runner = subprocess.run,
    sleep: Callable[[float], None] = time.sleep,
    poll: float = 2.0,
) -> int:
    """One launch "On this computer": relay, the copy's files, the copy
    opened (or brought forward), held until the copy quits. 0 when it ended
    normally, 1 when it couldn't start."""
    import secrets
    import shutil

    from umcodex import codex_app, credentials, toolkit
    from umcodex.launch import LaunchLock, launches_dir, running_launches, write_launch_info
    from umcodex.relay import upstream_base_url

    data = data or data_dir()
    if setup.reads:
        say("Read-only folders aren't available on this computer: edit the setup and remove them.")
        return 1
    others = [r for r in running_launches(data) if r.app and r.app.get("local")]
    if others:
        say(f"“{others[0].setup_name}” is running on this computer now. Stop it first.")
        return 1
    launch_id = secrets.token_hex(4)
    folder = launches_dir(data) / launch_id
    folder.mkdir(parents=True)
    lock = LaunchLock(folder / "lock")
    if not lock.acquire(tries=40):
        raise RuntimeError("couldn't lock the launch folder")
    state: dict = {"local": True, "copy": "not-opened", "pid": None, "seeded": False, "notes": list(NOTES)}
    write_launch_info(folder, setup, app=state)
    relay = None
    try:
        pid = running_copy(data, run)
        key = api_key or credentials.api_key
        upstream = base_url or upstream_base_url(toolkit.BASE_URL)
        relay = LocalRelay(key, upstream, data, keep_token=pid is not None)
        try:
            port = relay.start()
        except OSError:
            relay.stop(forget=False)  # its thread; the open copy's token stays
            relay = None
            if pid is not None:
                say(
                    "The relay's port is taken by another program. Quit UM-Codex's local Codex window, "
                    "then Start again."
                )
                return 1
            (local_folder(data) / PORT_FILE).unlink(missing_ok=True)  # another program has it: a new one
            relay = LocalRelay(key, upstream, data)
            port = relay.start()
        log.info("launch %s: on this computer, relay on 127.0.0.1:%d", launch_id, port)
        seeded = write_copy_files(
            setup,
            layout,
            data=data,
            app=app,
            port=port,
            token_file=relay.token_file,
            run=run,
            seed=pid is None,
        )
        if pid is not None:
            state["copy"] = "brought-forward" if codex_app.bring_forward(pid, run) else "already-open"
            say(
                "UM-Codex's local Codex window was already open: it keeps the project and settings "
                "it opened with."
            )
        elif app is None:
            state["copy"] = "not-opened"
        else:
            done = run(open_command(app, data), capture_output=True, timeout=60, check=False)
            pid = _open_wait(data, run, sleep) if done.returncode == 0 else None
            state["copy"] = "opened" if pid is not None else "failed"
        state.update({"pid": pid, "seeded": seeded})
        write_launch_info(folder, setup, app=state)
        if pid is None:
            if state["copy"] == "failed":
                say("UM-Codex's local Codex window couldn't be opened.")
                return 1
            return 0
        say(f"Running on this computer, in UM-Codex's local Codex window ({setup.name}).")
        for line in NOTES:
            say(line)
        wait_while_running(pid, poll, sleep)
        say("UM-Codex's local Codex window was closed.")
        return 0
    except KeyboardInterrupt:
        say("")
        say("Ending the launch (the relay stops; Start again in UM-Codex to carry on).")
        if relay is not None:
            relay.stop(forget=False)
            relay = None
        return 0
    finally:
        if relay is not None:
            relay.stop(forget=running_copy(data, run) is None)
        lock.release()
        shutil.rmtree(folder, ignore_errors=True)


# JavaScript for Automation, through AppKit: ask the copy to quit, as its Quit
# menu does (it may ask the person first). No permission to control other apps.
_TERMINATE = (
    'ObjC.import("AppKit"); function run(argv) { '
    "var app = $.NSRunningApplication.runningApplicationWithProcessIdentifier(parseInt(argv[0])); "
    'if (!app || app.isNil()) return "gone"; '
    'return app.terminate() ? "ok" : "refused"; }'
)


def stop_local(data: Path, launch, run: Runner = subprocess.run) -> bool:
    """Stop a launch on this computer: quit UM-Codex's local copy (only that
    copy, found by its profile folder), and its launch then ends. False when
    there's nothing to stop."""
    pid = launch.app.get("pid") if launch.app else None
    current = running_copy(data, run)
    if current is None or (isinstance(pid, int) and pid != current):
        return False
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        done = run(
            ["/usr/bin/osascript", "-l", "JavaScript", "-e", _TERMINATE, str(current)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if done.returncode == 0 and done.stdout.strip() in ("ok", "gone"):
            return True
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.kill(current, 15)
    return True


def chrome_manifests(home: Path | None = None) -> list[Path]:
    """The Chrome extension's native messaging manifests (the app's Chrome
    plugin writes them for the whole macOS user)."""
    home = home or Path.home()
    support = home / "Library" / "Application Support"
    folders = ("Google/Chrome", "Chromium", "Google/ChromeForTesting", "Google/Chrome for Testing")
    return [support / f / "NativeMessagingHosts" / "com.openai.codexextension.json" for f in folders]


def forget_chrome_manifests(data: Path, home: Path | None = None) -> list[str]:
    """Remove the manifests that lead into the local copy's folder (which
    uninstall removes): left, they'd point Chrome at a program that's gone.
    A manifest of the person's own ChatGPT app is left alone."""
    ours = local_folder(data).resolve()
    removed = []
    for path in chrome_manifests(home):
        try:
            target = Path(json.loads(path.read_text(encoding="utf-8"))["path"]).resolve()
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if target == ours or ours in target.parents:
            with contextlib.suppress(OSError):
                path.unlink()
                removed.append(
                    f"Removed Chrome's link to UM-Codex's local Codex window ({path.parent.parent.name})."
                )
    return removed
