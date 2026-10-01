"""Checks before a launch, and `um-codex doctor`.

`ensure_docker` makes sure Docker answers, opening Docker Desktop if it's
closed (and, on Windows, offering DataLab's fix for the virtual machine's
logon right). `report` checks Docker, the images, the key and the Toolkit,
and prints diagnostics with no secrets in them: it says whether a key is
saved and whether the Toolkit accepts it, never any of the key itself.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time
from collections.abc import Callable

from umcodex import __version__, credentials, toolkit, windows_vm
from umcodex.containers import Docker, DockerError, images, instance_of, owned_leftovers
from umcodex.docker_path import ensure_docker_on_path
from umcodex.paths import data_dir
from umcodex.setups import SetupStore

Say = Callable[[str], None]
Ask = Callable[[str], str]


def ensure_docker(
    say: Say = print,
    ask: Ask = input,
    *,
    wait_seconds: float = 180,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """True once Docker's engine answers."""
    ensure_docker_on_path()
    if shutil.which("docker") is None and sys.platform != "win32":
        say("Docker Desktop isn't installed (or its `docker` command can't be found).")
        say("Install it from https://www.docker.com/products/docker-desktop/ and try again.")
        return False
    if sys.platform == "win32":
        state = windows_vm.check_before_launch(windows_vm.DockerDoctor(), ask=ask, say=say)
        if state == "ready":
            return True
        say(_WINDOWS_STATES.get(state, "Docker isn't ready."))
        return False
    if windows_vm.docker_answers(run):
        return True
    if sys.platform == "darwin":
        say("Opening Docker Desktop (this can take a minute)...")
        run(["open", "-g", "-a", "Docker"], capture_output=True)
        waited = 0.0
        while waited < wait_seconds:
            sleep(3)
            waited += 3
            if windows_vm.docker_answers(run):
                say("Docker is ready.")
                return True
        say("Docker Desktop didn't become ready. Open it yourself, wait until it says it's running,")
        say("then try again.")
        return False
    say("Docker isn't answering. Start Docker and try again.")
    return False


_WINDOWS_STATES = {
    "not-installed": "Docker Desktop isn't installed. Install it, then try again.",
    "stopped": "Docker Desktop didn't open. Open it yourself, then try again.",
    "starting": "Docker Desktop is still starting. Wait until it says it's running, then try again.",
    "vm-refused": "Docker can't start until Windows' policy is fixed (or Windows is restarted).",
    "unknown": "Docker isn't answering, and WSL couldn't say why. Restart Docker Desktop.",
}


def report(say: Say = print, docker: Docker | None = None) -> bool:
    """`um-codex doctor`. True when everything needed for a launch is there."""
    docker = docker or Docker()
    ok = True

    def line(good: bool | None, text: str) -> None:
        mark = {True: "ok     ", False: "PROBLEM", None: "note   "}[good]
        say(f"  {mark}  {text}")

    say(f"UM-Codex {__version__} on {platform.system()} {platform.release()} ({platform.machine()}),")
    say(f"Python {platform.python_version()}")
    say(f"Data folder: {data_dir()}")
    say("")
    ensure_docker_on_path()
    found = shutil.which("docker")
    line(found is not None, f"Docker command: {found or 'not found'}")
    engine = None
    if found:
        try:
            code, out, _ = docker.status("version", "--format", "{{.Server.Version}}", timeout=15)
            engine = out.strip() if code == 0 else None
        except DockerError:
            engine = None
    line(engine is not None, f"Docker engine: {engine or 'not answering (is Docker Desktop running?)'}")
    ok = ok and engine is not None
    if engine:
        for role, image in images().items():
            override = os.environ.get("UMCODEX_AGENT_IMAGE") if role == "agent" else None
            image = override or image
            present = docker.status("image", "inspect", "--format", "{{.Id}}", image, timeout=30)[0] == 0
            hint = "" if present else (
                " (build it: see README, 'Run from source')" if role == "agent" else " (will be pulled)"
            )  # fmt: skip
            state = "present" if present else "missing"
            line(present or role == "gateway", f"{role} image {image}: {state}{hint}")
            ok = ok and (present or role == "gateway")
        try:
            containers, networks = owned_leftovers(
                docker, instance_of(data_dir()), lambda launch: _launch_live(launch)
            )
            if containers or networks:
                line(None, f"{len(containers)} container(s) and {len(networks)} network(s) left by an "
                           "earlier launch: the next launch removes them")  # fmt: skip
        except DockerError:
            pass
    saved = credentials.has_api_key()
    where = "saved in the keychain" if saved else "not saved (run: um-codex key)"
    line(saved, f"Toolkit API key: {where}")
    ok = ok and saved
    if os.environ.get("UMCODEX_UPSTREAM"):
        line(None, "UMCODEX_UPSTREAM is set: model requests go to a test stub, not the Toolkit")
    if saved:
        result = toolkit.check_key(credentials.api_key())
        words = {
            "ok": "the Toolkit accepts the key",
            "refused": "the Toolkit refused the key (replace it: um-codex key)",
            "unreachable": "couldn't reach the Toolkit (check your network or VPN)",
            "error": "the Toolkit answered with an error",
        }
        line(result == "ok", f"Toolkit ({toolkit.base_url()}): {words[result]}")
        ok = ok and result == "ok"
    setups = SetupStore().all()
    line(None, f"{len(setups)} saved setup(s)")
    say("")
    say("Everything needed for a launch is there." if ok else "Some things need fixing before a launch.")
    return ok


def _launch_live(launch_id: str) -> bool:
    from umcodex.launch import launch_is_live

    return launch_is_live(data_dir(), launch_id)
