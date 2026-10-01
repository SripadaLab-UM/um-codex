"""Where a launch started from the launcher window opens Codex.

An `Opener` starts `um-codex launch --setup <id>` somewhere the person can
use Codex's screen. For now that's a new terminal window (`TerminalOpener`);
Codex's desktop app is being tried on another branch, and plugs in here as
another Opener (`CodexAppOpener` is its placeholder).

Nothing here goes through a shell with the setup's id or the program's path
spliced in unquoted:
- Mac: Terminal opens a small `.command` file (made for this one start, in
  UM-Codex's data folder; it removes itself when it runs) holding one shell
  line, built with `shlex.quote` for every part. Opening a file in Terminal
  needs no permission to control Terminal, and a Terminal that wasn't running
  opens just that one window.
- Windows: PowerShell gets the command as `-EncodedCommand` (base64 of
  UTF-16), with every part in a single-quoted PowerShell string; so neither
  Windows' command-line quoting nor Windows Terminal's own `;` splitting can
  change it.
"""

from __future__ import annotations

import base64
import os
import re
import secrets
import shlex
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Protocol

from umcodex.paths import data_dir

# Development and test settings the launch must keep (the server's own; a new
# terminal window doesn't inherit them). None of them is a secret.
PASSED_ON = (
    "UMCODEX_DATA_DIR",
    "UMCODEX_AGENT_IMAGE",
    "UMCODEX_UPSTREAM",
    "UMCODEX_NO_UPDATE_CHECK",
    "UMCODEX_INSTALL_DIR",
    "UMCODEX_RELEASES_API",
    # keyring's own choice of key store: the launch must read the key from the
    # store the window checked (tests use a stand-in, never the real key).
    "PYTHON_KEYRING_BACKEND",
)

class OpenFailed(RuntimeError):
    """The window couldn't be opened. The message is for the person."""


class Opener(Protocol):
    key: str  # what a setup saves as `open_in`
    label: str

    def available(self) -> bool: ...

    def open(self, setup_id: str) -> None: ...


def own_command() -> list[str]:
    """This very UM-Codex (the server's Python and package), so the launch is
    the same version as the window that started it."""
    return [sys.executable, "-m", "umcodex"]


def passed_on(environ: Mapping[str, str]) -> dict[str, str]:
    return {name: environ[name] for name in PASSED_ON if environ.get(name)}


def launch_args(program: Sequence[str], setup_id: str) -> list[str]:
    return [*program, "launch", "--setup", setup_id]


def mac_shell_line(program: Sequence[str], setup_id: str, env: Mapping[str, str]) -> str:
    """The line Terminal's shell runs: every part quoted."""
    parts = launch_args(program, setup_id)
    if env:
        parts = ["env", *(f"{name}={value}" for name, value in env.items()), *parts]
    return shlex.join(parts)


def mac_script(program: Sequence[str], setup_id: str, env: Mapping[str, str]) -> str:
    """The `.command` file Terminal opens: it removes itself, then runs the launch."""
    return "#!/bin/sh\n" + 'rm -f "$0"\n' + mac_shell_line(program, setup_id, env) + "\n"


def ps_quote(text: str) -> str:
    """A single-quoted PowerShell string: only ' is special (doubled). The
    typographic quotes PowerShell also accepts as quotes are doubled too."""
    for quote in ("'", "‘", "’", "‚", "‛"):
        text = text.replace(quote, quote * 2)
    return f"'{text}'"


def native_arg(text: str) -> str:
    """An argument as Windows PowerShell 5.1 must be given it for a program
    to receive it unchanged. 5.1 puts quotes around an argument with a space
    in it but doesn't escape the double quotes inside (nor the backslashes
    before them, or before its own closing quote), so this does, by the rules
    programs use to split their command line (CommandLineToArgvW)."""
    text = re.sub(r'(\\*)"', lambda m: m.group(1) * 2 + '\\"', text)
    if re.search(r"\s", text):
        text = re.sub(r"(\\+)$", lambda m: m.group(1) * 2, text)
    return text


def powershell_script(program: Sequence[str], setup_id: str, env: Mapping[str, str]) -> str:
    lines = ["$Host.UI.RawUI.WindowTitle = 'UM-Codex'", "$Env:PYTHONUTF8 = '1'"]
    lines += [f"$Env:{name} = {ps_quote(value)}" for name, value in env.items()]
    first, *rest = launch_args(program, setup_id)
    lines.append("& " + " ".join(ps_quote(native_arg(part)) for part in [first, *rest]))
    return "\n".join(lines)


def encoded(script: str) -> str:
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def windows_terminal(environ: Mapping[str, str] = os.environ) -> Path | None:
    """Windows Terminal's own command (an app execution alias), if it's there."""
    local = environ.get("LOCALAPPDATA")
    if not local:
        return None
    found = Path(local) / "Microsoft" / "WindowsApps" / "wt.exe"
    return found if found.exists() else None


def windows_command(
    program: Sequence[str], setup_id: str, env: Mapping[str, str], *, terminal: Path | None, powershell: str
) -> list[str]:
    """Windows Terminal if it's installed, else Windows PowerShell (in a new
    console). The window stays open afterwards (-NoExit), to read what it said."""
    script = encoded(powershell_script(program, setup_id, env))
    ps = [powershell, "-NoProfile", "-NoExit", "-EncodedCommand", script]
    if terminal is not None:
        # "--" ends Windows Terminal's own options; base64 has no ";" for it to split at.
        return [str(terminal), "-w", "new", "new-tab", "--title", "UM-Codex", "--", *ps]
    return ps


class TerminalOpener:
    key = "terminal"
    label = "Terminal"

    def __init__(
        self,
        *,
        program: Sequence[str] | None = None,
        platform: str = sys.platform,
        environ: Mapping[str, str] = os.environ,
        popen: Callable[..., object] = subprocess.Popen,
        run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        folder: Path | None = None,
    ) -> None:
        self._program = list(program) if program is not None else own_command()
        self._platform = platform
        self._environ = environ
        self._popen = popen
        self._run = run
        self._folder = folder  # where the Mac's .command files go (default: the data folder's ui/)

    def available(self) -> bool:
        return self._platform in ("darwin", "win32")

    def command(self, setup_id: str) -> list[str]:
        """Windows: the command that opens the window."""
        env = passed_on(self._environ)
        from umcodex.windows_vm import powershell

        return windows_command(
            self._program, setup_id, env, terminal=windows_terminal(self._environ), powershell=powershell()
        )

    def open(self, setup_id: str) -> None:
        if self._platform == "darwin":
            self._open_mac(setup_id)
        elif self._platform == "win32":
            self._open_windows(setup_id)
        else:
            raise OpenFailed("Opening a terminal window needs UM-Codex on a Mac or Windows computer.")

    def _open_mac(self, setup_id: str) -> None:
        folder = self._folder or data_dir() / "ui"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"start-{secrets.token_hex(6)}.command"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as file:
            file.write(mac_script(self._program, setup_id, passed_on(self._environ)))
        try:
            done = self._run(["open", "-a", "Terminal", str(path)], capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as error:
            path.unlink(missing_ok=True)
            raise OpenFailed("Terminal couldn't be opened.") from error
        if done.returncode != 0:
            path.unlink(missing_ok=True)
            raise OpenFailed("Terminal couldn't be opened.")

    def _open_windows(self, setup_id: str) -> None:
        command = self.command(setup_id)
        flags = 0
        if not command[0].lower().endswith("wt.exe"):
            flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0x10)
        try:
            self._popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
                close_fds=True,
            )
        except OSError as error:
            raise OpenFailed("The terminal window couldn't be opened.") from error


class CodexAppOpener:
    """Placeholder: Codex's desktop app (being tried on branch spike-codex-app)."""

    key = "codex-app"
    label = "Codex app"

    def available(self) -> bool:
        return False

    def open(self, setup_id: str) -> None:
        raise OpenFailed("Opening in the Codex app isn't ready yet: choose Terminal.")


def openers() -> dict[str, Opener]:
    return {opener.key: opener for opener in (TerminalOpener(), CodexAppOpener())}
