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

This is the spike's minimal proof, not the feature: no launcher UI, no
setup field yet. The pieces the feature will reuse are here so the proof
exercises them.
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

WARNING = (
    "Codex will run on your Mac, not in the sandbox. It can read, change and delete any of "
    "your files, use your apps and browser, and act with your accounts. Use it only when you "
    "need computer or browser control."
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
    approval_policy: str = "never",
    internet: bool = True,
    catalog: Path | None = None,
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
            **ACCESS[access],
        }
    )
    if access == "folder":
        config["sandbox_workspace_write"] = {"network_access": internet}
    config.setdefault("model", model)
    if catalog is not None:
        config["model_catalog_json"] = str(catalog)
    head = "# UM-Codex sets the provider and defaults here (On this computer); the rest is the app's.\n"
    return head + tomli_w.dumps(config)


# --- The copy's state: the local project, pop-ups seen ---------------------------------


def project_id(folder: Path) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"um-codex-local:{folder}"))


def seeded_state(
    state: dict, *, name: str, folder: Path, seen_models: Iterable[str] = (), now: float | None = None
) -> dict:
    """`state` with a local project for `folder` (named `name`) made and
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
    projects = state.setdefault("local-projects", {})
    mine = next(
        (p for p in projects.values() if isinstance(p, dict) and p.get("rootPaths") == [str(folder)]),
        None,
    )
    if mine is None:
        pid = project_id(folder)
        ms = int(now * 1000)
        mine = {"id": pid, "name": name, "rootPaths": [str(folder)], "createdAt": ms, "updatedAt": ms}
        projects[pid] = mine
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


def seed_copy(home: Path, *, name: str, folder: Path, seen_models: Iterable[str] = ()) -> None:
    """Only while the copy isn't running (the app reads the file once at start)."""
    text = json.dumps(seeded_state(read_state(home), name=name, folder=folder, seen_models=seen_models))
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
