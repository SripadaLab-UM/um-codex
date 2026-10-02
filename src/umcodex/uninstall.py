# Adapted from DataLab's backend/src/datalab/setup.py (uninstall), storage.py (size_of,
# human) and repos/git.py (remove_tree, the read-only retry) at 6b6fdca, with the #36 fixes.
"""`um-codex uninstall`: remove what UM-Codex put on this computer, except
its program files (the uninstaller scripts remove those after this returns)
and the person's own folders, which are never touched.

Its scope is its data folder (`UMCODEX_DATA_DIR`, or the default one).
Containers, networks and volumes go by that data folder's instance label, so
another data folder's (a development or test copy's) are never removed. Only
the installed copy's data folder (paths.default_data_dir) also takes what
every copy shares: the Toolkit key (there's one, in the keychain) and the
Docker images, and those only when no other data folder's containers are
here. Another data folder's uninstall keeps both and says so.

It first asks "Uninstall UM-Codex? [y/N]" (not with --yes); nothing is
removed before that's answered yes. Then, found by label only:
- UM-Codex's containers and networks;
- with --delete-data, each setup's Codex home volume (its Codex history);
- the Toolkit key, from the keychain;
- the Codex app's ssh entries: the `Include ~/.ssh/um-codex/config` line at
  the top of ~/.ssh/config (its backup too, if the file is now the same as
  it) and ~/.ssh/um-codex;
- the agent image and, if no container uses it, the gateway image (asked first);
- with --delete-data, the data folder's contents (saved setups, logs, the
  Codex app copy's settings and chats in `codex-app`), but never its `app`
  folder.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import stat
import subprocess
from collections.abc import Callable
from pathlib import Path

from umcodex import credentials
from umcodex.containers import APP, APP_LABEL, INSTANCE_LABEL, images, instance_of
from umcodex.launch import LaunchLock, launch_is_live, launches_dir
from umcodex.paths import app_dir, data_dir, default_data_dir

Say = Callable[[str], None]
Ask = Callable[[str], str]
Run = Callable[..., subprocess.CompletedProcess]

AGENT_REPOSITORIES = ("um-codex-agent", "ghcr.io/sripadalab-um/um-codex-agent")


def uninstall(
    *,
    delete_data: bool | None,
    yes: bool = False,
    say: Say = print,
    ask: Ask = input,
    run: Run = subprocess.run,
) -> int:
    """0 when done (even if something was left, which is reported); 1 if
    UM-Codex is running or the person says no (EOFError, with no terminal
    to answer, is left to the caller: `um-codex` takes it as no)."""
    data = data_dir()
    if _running(data):
        say("UM-Codex is running (a launch is open). Quit Codex first, then run the uninstaller again.")
        return 1
    if _updating():
        say(
            "UM-Codex is updating (from its window or a terminal). Wait for it to finish, then run the "
            "uninstaller again."
        )
        return 1

    def confirm(question: str) -> bool:
        if yes:
            return True
        return ask(f"{question} [y/N] ").strip().lower() in ("y", "yes")

    if not confirm("Uninstall UM-Codex?"):
        say("Nothing was removed.")
        return 1

    # The launcher window's server, if it's open: its files are about to go.
    from umcodex.ui.server import close_running

    close_running(data)

    docker_ok = shutil.which("docker") is not None and _docker(run, "info", "--format", "x") is not None
    installed = is_installed_copy(data)
    if not installed:
        say(
            f"This uninstalls the UM-Codex data folder {data}, which isn't the installed one "
            f"({default_data_dir()}): only its own containers, ssh entries and data go."
        )
    if docker_ok:
        say("Removing UM-Codex's containers and networks...")
        _remove_owned(run, ["ps", "-a"], ["rm", "-f"], data)
        _remove_owned(run, ["network", "ls"], ["network", "rm"], data)
        if _others(run, data):
            say(
                "Left the containers of another UM-Codex data folder on this computer (a development "
                "or test copy): that copy's own uninstall removes them."
            )
    else:
        say("Docker isn't running, so UM-Codex's containers, volumes and images (if any) were left.")

    if installed:
        say("Removing the Toolkit key from the keychain...")
        credentials.delete_api_key()
    else:
        say("Kept the Toolkit key in the keychain: there's one, and the installed UM-Codex uses it.")

    # The Codex app's ssh entries (M6): this data folder's in ~/.ssh/um-codex,
    # and the Include line in ~/.ssh/config with the folder itself unless
    # another data folder on this computer still uses them.
    from umcodex import codex_app

    for line in codex_app.uninstall_ssh(data=data):
        say(line)

    if docker_ok:
        _remove_images(run, say, confirm)

    # The data folder: saved setups, logs. The program files (`app`) stay for
    # the uninstaller script; the person's own folders are never in here.
    skip = {_key(data / "app"), _key(app_dir())}
    entries = [e for e in _entries(data) if _key(e) not in skip]
    if entries:
        size = sum(size_of(e) for e in entries)
        say("")
        say(f"UM-Codex's data (saved setups, logs) in {data}: {human(size)}")
        say("Each setup's Codex history is in Docker, and goes with the data.")
        if delete_data is None:
            delete_data = (not yes) and confirm("Delete them? This can't be undone.")
        if delete_data:
            if docker_ok:
                _remove_owned(run, ["volume", "ls"], ["volume", "rm"], data)
            for entry in entries:
                remove_tree(entry)
            left = [e for e in entries if e.exists() or e.is_symlink()]
            if left:
                say("Deleted, except what couldn't be removed (a file still in use?):")
                for entry in left:
                    say(f"  {entry}  ({human(size_of(entry))} left). Delete it yourself.")
            else:
                say("Deleted.")
        else:
            say("Kept. You can delete them yourself later.")
    elif delete_data and docker_ok:
        _remove_owned(run, ["volume", "ls"], ["volume", "rm"], data)
    say("Your own folders were not touched.")
    return 0


def _updating() -> bool:
    """Whether an update (or rollback) holds its lock: the launcher's runs on
    its own, and its files must not go from under it."""
    from umcodex.update import Layout, install_root

    lock = LaunchLock(Layout(install_root()).root / "update.lock")
    if not lock.path.exists():
        return False
    if lock.acquire():
        lock.release()
        return False
    return True


def _running(data: Path) -> bool:
    folder = launches_dir(data)
    if not folder.is_dir():
        return False
    return any(launch_is_live(data, entry.name) for entry in folder.iterdir() if entry.is_dir())


def is_installed_copy(data: Path) -> bool:
    """Whether `data` is the installed UM-Codex's data folder (the default
    one), not a development or test copy's (`UMCODEX_DATA_DIR`)."""
    return _key(data.resolve()) == _key(default_data_dir().resolve())


def _owned(run: Run, kind: list[str], data: Path) -> tuple[list[str], list[str]]:
    """UM-Codex's containers, networks or volumes (`kind`: ["ps", "-a"],
    ["network", "ls"], ["volume", "ls"]): this data folder's, and other
    data folders'. By label only."""
    field = "{{.Name}}" if kind[0] == "volume" else "{{.ID}}"
    shape = f'{field}|{{{{.Label "{INSTANCE_LABEL}"}}}}'
    listing = _docker(run, *kind, "--filter", f"label={APP_LABEL}={APP}", "--format", shape)
    instance = instance_of(data)
    mine: list[str] = []
    others: list[str] = []
    for line in (listing or "").splitlines():
        name, owner = ([*line.split("|"), ""])[:2]
        if name.strip():
            (mine if owner.strip() == instance else others).append(name.strip())
    return mine, others


def _remove_owned(run: Run, kind: list[str], then: list[str], data: Path) -> None:
    mine, _ = _owned(run, kind, data)
    if mine:
        _docker(run, *then, *mine)


def _others(run: Run, data: Path) -> bool:
    """Whether another data folder has containers here (running or not)."""
    return bool(_owned(run, ["ps", "-a"], data)[1])


def _remove_images(run: Run, say: Say, confirm: Callable[[str], bool]) -> None:
    # The images are shared by every data folder on this computer.
    data = data_dir()
    if not is_installed_copy(data):
        say("Kept UM-Codex's Docker images: the installed UM-Codex uses them too.")
        return
    if _others(run, data):
        say("Kept UM-Codex's Docker images: another UM-Codex data folder's containers use them.")
        return
    agent_ids: list[str] = []
    for repository in AGENT_REPOSITORIES:
        listed = _docker(run, "images", "-q", repository)
        agent_ids += [i for i in (listed or "").split() if i not in agent_ids]
    gateway = images()["gateway"]
    gateway_here = _docker(run, "image", "inspect", "--format", "{{.Id}}", gateway) is not None
    if not agent_ids and not gateway_here:
        return
    if not confirm("Remove UM-Codex's Docker images too? They're downloaded again if you reinstall."):
        say("The images were kept.")
        return
    if agent_ids:
        _docker(run, "rmi", "-f", *agent_ids)
        say("Removed the agent image.")
    if gateway_here:
        users = _docker(run, "ps", "-aq", "--filter", f"ancestor={gateway}")
        if users and users.strip():
            say("The gateway image (nginx) was kept: another container uses it.")
        elif _docker(run, "rmi", gateway) is None:
            say("The gateway image (nginx) was kept: Docker says something still uses it.")
        else:
            say("Removed the gateway image.")


def _docker(run: Run, *args: str) -> str | None:
    """Output of a docker command, or None if it failed. A stuck Docker
    engine can leave `docker` waiting for ever; uninstalling carries on."""
    try:
        done = run(["docker", *args], capture_output=True, encoding="utf-8", errors="replace", timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def _entries(folder: Path) -> list[Path]:
    try:
        return list(folder.iterdir())
    except OSError:
        return []


def _key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))


def size_of(path: Path) -> int:
    """Bytes used by a file, or a folder and everything in it. Links aren't
    followed, and what can't be read is skipped: a Codex home can hold Linux
    symlinks that are WSL reparse points on Windows, and opening one raised
    WinError 1920, which stopped DataLab's uninstaller (#36)."""
    try:
        info = path.lstat()
    except OSError:
        return 0
    if not stat.S_ISDIR(info.st_mode):
        return info.st_size
    total = 0
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        else:
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def human(size: int) -> str:
    value = float(size)
    for unit in ("bytes", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "bytes" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} bytes"


def remove_tree(path: Path) -> None:
    """Delete a file or folder as far as it can be deleted. Links aren't
    followed (a link is removed, never its target). On Windows a read-only
    file can't be deleted, so each is made writable and tried once more.
    Whatever still can't go (a file something has open) is left: callers
    check what's still there."""
    if path.is_symlink() or not path.is_dir():
        with contextlib.suppress(OSError):
            path.unlink()
        return
    shutil.rmtree(path, onexc=_retry_read_only)


_WINDOWS = os.name == "nt"


def _retry_read_only(function: Callable[..., object], path: str, error: BaseException) -> None:
    """remove_tree's second try at a read-only file (Windows only)."""
    # Access denied (5) only: a file in use (32) won't go on a second try.
    if not _WINDOWS or getattr(error, "winerror", None) != 5:
        return
    if function not in (os.unlink, os.rmdir):
        return
    with contextlib.suppress(OSError, NotImplementedError):
        os.chmod(path, stat.S_IWRITE, follow_symlinks=False)
        function(path)
