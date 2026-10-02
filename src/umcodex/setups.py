"""Saved setups: what a launch shares with the container, and how Codex runs.

A setup is a name, a working folder, more folders to write, folders to read
only, internet on or off, the browser tool (only with the internet on), the
model and the approval policy. Setups are kept
in `setups.toml` in UM-Codex's data folder, with the last one used first.

The questions are plain `input()` prompts (no curses), so they work the same
in Terminal, Windows Terminal and PowerShell. Every function that asks takes
`ask` and `say`, so tests drive them without a terminal.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import secrets
import tomllib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

import tomli_w

from umcodex import folders, locks
from umcodex.codex_config import Approvals
from umcodex.folders import FolderRefused
from umcodex.paths import data_dir
from umcodex.toolkit import DEFAULT_MODEL

log = logging.getLogger(__name__)

Ask = Callable[[str], str]
Say = Callable[[str], None]

# Where a launch from the launcher window opens Codex (ui/opener.py).
OPEN_IN = ("terminal", "codex-app")
# Where Codex runs (M4): in the sandbox (the default), or on this computer, in
# UM-Codex's local copy of the Codex app (this_computer.py).
RUNS_ON = ("sandbox", "this-computer")
# On this computer, what Codex's own commands may change (its macOS sandbox).
LOCAL_ACCESS = ("full", "folder")


@dataclass(frozen=True)
class Setup:
    id: str
    name: str
    working: str
    writes: tuple[str, ...] = ()
    reads: tuple[str, ...] = ()
    internet: bool = False
    model: str = DEFAULT_MODEL
    approvals: Approvals = "never"
    # The browser tool (M2b): only with the internet on. Setups saved before
    # it existed have neither key, which means off.
    browser: bool = False
    browser_asks: bool = True  # approve each browser action
    # Where Codex opens when started from the launcher window (M5): only
    # "terminal" for now; "codex-app" is being tried on another branch.
    open_in: str = "terminal"
    # M4, "On this computer": setups saved before it have none of these
    # keys, which means the sandbox.
    runs_on: str = "sandbox"
    local_access: str = "full"  # "folder": Codex's commands change only the setup's folders
    computer_use: bool = True  # Computer Use, the in-app browser and Chrome control

    @property
    def on_this_computer(self) -> bool:
        return self.runs_on == "this-computer"

    def to_toml(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "working": self.working,
            "writes": list(self.writes),
            "reads": list(self.reads),
            "internet": self.internet,
            "model": self.model,
            "approvals": self.approvals,
            "browser": self.browser,
            "browser_asks": self.browser_asks,
            "open_in": self.open_in,
            "runs_on": self.runs_on,
            "local_access": self.local_access,
            "computer_use": self.computer_use,
        }

    @classmethod
    def from_toml(cls, raw: dict) -> Setup:
        """A saved setup. ValueError for an id UM-Codex wouldn't make: it
        names ssh keys, Docker volumes and the Codex app's hosts."""
        if not SETUP_ID.fullmatch(str(raw["id"])):
            raise ValueError(
                f"the saved setup “{raw['id']}” has an id UM-Codex can't use (only letters, digits, "
                "dots and dashes)"
            )
        approvals = raw.get("approvals", "never")
        if approvals not in ("never", "on-request"):
            approvals = "never"
        internet = bool(raw.get("internet", False))
        return cls(
            id=str(raw["id"]),
            name=str(raw.get("name") or raw["id"]),
            working=str(raw["working"]),
            writes=tuple(str(p) for p in raw.get("writes", [])),
            reads=tuple(str(p) for p in raw.get("reads", [])),
            internet=internet,
            model=str(raw.get("model") or DEFAULT_MODEL),
            approvals=approvals,
            browser=internet and raw.get("browser", False) is True,
            browser_asks=raw.get("browser_asks", True) is not False,
            open_in=str(raw["open_in"]) if raw.get("open_in") in OPEN_IN else "terminal",
            runs_on=str(raw["runs_on"]) if raw.get("runs_on") in RUNS_ON else "sandbox",
            local_access=str(raw["local_access"]) if raw.get("local_access") in LOCAL_ACCESS else "full",
            computer_use=raw.get("computer_use", True) is not False,
        )


MAX_NAME = 80


def unique_name(name: str, taken: Iterable[str]) -> str:
    """`name`, or "name 2", "name 3", ... when another setup has it already
    (letter case aside), at most MAX_NAME characters."""
    used = {t.casefold() for t in taken}
    name = name[:MAX_NAME]
    candidate, number = name, 1
    numbered = re.fullmatch(r"(.*\S) ([0-9]{1,4})", name)
    if numbered and name.casefold() in used:  # "thesis 2" taken: "thesis 3" next
        name, number = numbered.group(1), int(numbered.group(2))
    while candidate.casefold() in used:
        number += 1
        suffix = f" {number}"
        candidate = name[: MAX_NAME - len(suffix)].rstrip() + suffix
    return candidate


def default_name(working: str, taken: Iterable[str]) -> str:
    """A new setup's name: its working folder's name (made unique)."""
    base = " ".join((Path(working).name or str(working)).split()) or "Setup"
    return unique_name(base, taken)


# A setup's id: Docker-safe, a file name, and never `_` (the Codex app's host
# names add `_<install id>` for a data folder other than the installed copy's).
SETUP_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]{0,127}")


def new_id(name: str) -> str:
    """A setup's id: also its Codex home volume's name, so Docker-safe."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:32] or "setup"
    return f"{slug}-{secrets.token_hex(3)}"


@dataclass
class SetupStore:
    path: Path = field(default_factory=lambda: data_dir() / "setups.toml")

    def _read(self) -> dict:
        try:
            with self.path.open("rb") as file:
                return tomllib.load(file)
        except FileNotFoundError:
            return {}

    def _write(self, raw: dict) -> None:
        """Write the file whole: a temporary file of this write's own, then
        a rename, so a reader never sees half of it."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
        try:
            temporary.write_text(tomli_w.dumps(raw), encoding="utf-8", newline="\n")
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    @contextlib.contextmanager
    def _changing(self):
        """Read, change and write the setups under one lock, across this
        process's threads and other processes (a launch's mark_used, the
        launcher window's saves): no change is lost to another's."""
        with locks.held(self.path.with_name(self.path.name + ".lock")):
            raw = self._read()
            yield raw
            self._write(raw)

    def all(self) -> list[Setup]:
        """Every setup, the last one used first."""
        raw = self._read()
        setups = []
        for entry in raw.get("setup", []):
            try:
                setups.append(Setup.from_toml(entry))
            except (KeyError, TypeError):
                continue
            except ValueError as why:
                log.warning("%s; it's left out (in %s).", why, self.path)
        last = raw.get("last_used")
        setups.sort(key=lambda s: s.id != last)
        return setups

    def get(self, setup_id: str) -> Setup | None:
        return next((s for s in self.all() if s.id == setup_id), None)

    def save(self, setup: Setup, *, used: bool = False) -> None:
        with self._changing() as raw:
            entries = [e for e in raw.get("setup", []) if e.get("id") != setup.id]
            entries.append(setup.to_toml())
            raw["setup"] = entries
            if used:
                raw["last_used"] = setup.id

    def mark_used(self, setup_id: str) -> None:
        with self._changing() as raw:
            raw["last_used"] = setup_id

    def delete(self, setup_id: str) -> None:
        with self._changing() as raw:
            raw["setup"] = [e for e in raw.get("setup", []) if e.get("id") != setup_id]
            if raw.get("last_used") == setup_id:
                raw.pop("last_used")

    def last_used(self) -> Setup | None:
        raw = self._read()
        return self.get(raw["last_used"]) if raw.get("last_used") else None


# --- Checking ---------------------------------------------------------------


def check(setup: Setup, *, own_data: Path | None = None) -> folders.Layout:
    """The setup's folders, checked as they are now. Raises FolderRefused."""
    working = folders.check_folder(setup.working, own_data=own_data).path
    writes = [folders.check_folder(p, own_data=own_data).path for p in setup.writes]
    reads = [folders.check_folder(p, own_data=own_data).path for p in setup.reads]
    return folders.plan(working, writes, reads)


def moved(setup: Setup, *, own_data: Path | None = None) -> list[tuple[str, Path]]:
    """Saved folders that now resolve somewhere else: (as saved, where it goes now).

    A folder the agent could write may have had a part of its path swapped for
    a link (by an earlier launch, a sync, or an unpacked archive), which would
    point the next launch at a different folder.

    Folder by folder: one that's refused now (gone, say) is skipped, so it
    never hides another that moved; check() reports the refused one."""
    changed = []
    for saved in (setup.working, *setup.writes, *setup.reads):
        try:
            now = folders.check_folder(saved, own_data=own_data).path
        except FolderRefused:
            continue
        if not folders.same(Path(saved), now):
            changed.append((saved, now))
    return changed


def resolved(setup: Setup, layout: folders.Layout) -> Setup:
    """The setup with each folder as it resolves now (what was approved)."""
    return replace(
        setup,
        working=str(layout.working),
        writes=tuple(str(host) for host, _ in layout.writes),
        reads=tuple(str(host) for host, _ in layout.reads),
    )


# --- Asking -----------------------------------------------------------------


WRITES_ARE_REAL = "These are your real files: changes and deletions there happen straight away, with no undo."
BROWSER_PLAIN = "Codex can open websites in a fresh browser inside the sandbox; it has none of your logins."
BROWSER_QUESTION = f"Browser tool on? ({BROWSER_PLAIN})"
BROWSER_ASKS_QUESTION = "Approve each browser action (opening pages, clicking, typing)?"


def yes(ask: Ask, question: str, default: bool = True) -> bool:
    hint = "[Y/n]" if default else "[y/N]"
    while True:
        answer = ask(f"{question} {hint} ").strip().lower()
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False


def app_folder() -> Path:
    """The working folder offered when UM-Codex is opened from its app (or
    shortcut) and there's no last setup to offer: made when it's chosen."""
    return Path.home() / "Documents" / "UM-Codex"


def shown(path: str) -> str:
    """A path as people read it: ~ for the home folder."""
    home = str(Path.home())
    return "~" + path[len(home) :] if path == home or path.startswith(home + os.sep) else path


def ask_folder(ask: Ask, say: Say, question: str, default: str | None, own_data: Path | None) -> str:
    """One folder, checked. Empty input takes the default; the app's own
    default folder (~/Documents/UM-Codex) is made when it's chosen."""
    say(question)
    prompt = f"Drag a folder here, or press Enter for {shown(default)}: " if default else (
        "Drag a folder here, or type its path: "
    )  # fmt: skip
    while True:
        raw = ask(prompt).strip()
        if not raw and default:
            raw = default
            if Path(default) == app_folder():
                with contextlib.suppress(OSError):  # if it can't be made, the check says why
                    app_folder().mkdir(parents=True, exist_ok=True)
        if not raw:
            say("  Drag a folder from Finder or File Explorer into this window (or type its path),")
            say("  then press Enter.")
            continue
        try:
            checked = folders.check_folder(folders.parse_path_input(raw), own_data=own_data)
        except FolderRefused as refused:
            say(f"  {refused}")
            continue
        for warning in checked.warnings:
            say(f"  Note: {warning}")
        return str(checked.path)


def ask_folders(
    ask: Ask, say: Say, question: str, current: Sequence[str], own_data: Path | None
) -> tuple[str, ...]:
    """Any number of folders, one per line, ending with an empty line."""
    chosen = list(current)
    if chosen:
        say(f"{question} Now:")
        for path in chosen:
            say(f"  - {path}")
        if not yes(ask, "Keep these?", True):
            chosen = []
    say(f"{question} One per line (you can drag a folder in); press Enter on an empty line when done.")
    while True:
        raw = ask("  Folder: ").strip()
        if not raw:
            return tuple(chosen)
        try:
            checked = folders.check_folder(folders.parse_path_input(raw), own_data=own_data)
        except FolderRefused as refused:
            say(f"  {refused}")
            continue
        for warning in checked.warnings:
            say(f"  Note: {warning}")
        chosen.append(str(checked.path))


def ask_model(ask: Ask, say: Say, current: str, models: Sequence[str]) -> str:
    if models:
        say("Models on the Toolkit:")
        for number, model in enumerate(models, 1):
            mark = "  (current)" if model == current else ""
            say(f"  {number}. {model}{mark}")
    while True:
        answer = ask(f"Model (a number or a name) [{current}]: ").strip()
        if not answer:
            return current
        if answer.isdigit() and 1 <= int(answer) <= len(models):
            return models[int(answer) - 1]
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:\-/]{0,99}", answer):
            return answer
        say("  That isn't a model name.")


def ask_setup(
    ask: Ask,
    say: Say,
    *,
    start_folder: Path | None,
    models: Sequence[str] = (),
    existing: Setup | None = None,
    own_data: Path | None = None,
    fallback: str | None = None,
) -> Setup:
    """Every question for a new setup, or to edit `existing`. The working
    folder's default: the existing one's, else the folder um-codex was
    started in (`start_folder`), else `fallback` (opened from the app)."""
    base = existing
    say("")
    if base:
        default_working: str | None = base.working
    elif start_folder is not None:
        default_working = _default_working(start_folder, own_data)
    else:
        default_working = fallback
    working = ask_folder(
        ask, say, "Working folder (Codex starts here, and can read, write and delete)",
        default_working, own_data,
    )  # fmt: skip
    default_name = base.name if base else Path(working).name
    name = ask(f"Name for this setup [{default_name}]: ").strip() or default_name
    writes = ask_folders(
        ask, say, "More folders Codex can write (and delete in)?", base.writes if base else (), own_data
    )
    reads = ask_folders(ask, say, "Folders Codex can only read?", base.reads if base else (), own_data)
    internet = yes(
        ask,
        "Internet on? (Off: Codex can reach only the model.)",
        base.internet if base else False,
    )
    browser, browser_asks = False, base.browser_asks if base else True
    if internet:
        browser = yes(ask, BROWSER_QUESTION, base.browser if base else False)
        if browser:
            browser_asks = yes(ask, BROWSER_ASKS_QUESTION, browser_asks)
    model = ask_model(ask, say, base.model if base else DEFAULT_MODEL, models)
    say("Approvals:")
    say("  1. Codex runs commands without asking (recommended: the container is its sandbox)")
    say("  2. Codex asks me before commands")
    current = "2" if base and base.approvals == "on-request" else "1"
    approvals: Approvals = "never"
    while True:
        choice = ask(f"Choose 1 or 2 [{current}]: ").strip() or current
        if choice in ("1", "2"):
            approvals = "never" if choice == "1" else "on-request"
            break
    setup = Setup(
        id=base.id if base else new_id(name),
        name=name,
        working=working,
        writes=writes,
        reads=reads,
        internet=internet,
        model=model,
        approvals=approvals,
        browser=browser,
        browser_asks=browser_asks,
        open_in=base.open_in if base else "terminal",
        # Where it runs is chosen in the launcher window (M4); the terminal keeps it.
        runs_on=base.runs_on if base else "sandbox",
        local_access=base.local_access if base else "full",
        computer_use=base.computer_use if base else True,
    )
    return setup


def _default_working(start_folder: Path, own_data: Path | None) -> str | None:
    try:
        return str(folders.check_folder(start_folder, own_data=own_data).path)
    except FolderRefused:
        return None


def summary(setup: Setup, layout: folders.Layout) -> list[str]:
    """The summary screen, in plain words."""
    if setup.on_this_computer:
        return local_summary(setup, layout)
    lines = [
        "",
        f"Setup: {setup.name}",
        "",
        "Codex can read, change and DELETE files in:",
        f"  {layout.working}   (its working folder, /work)",
    ]
    lines += [f"  {host}   ({target})" for host, target in layout.writes]
    lines.append(WRITES_ARE_REAL)
    if layout.reads:
        lines += ["", "Codex can only read:"]
        lines += [f"  {host}   ({target})" for host, target in layout.reads]
    lines += [f"  Note: {note}" for note in layout.notes]
    lines.append("")
    if setup.internet:
        lines += [
            "Internet: ON. Codex can reach the whole internet, so it could send anything it",
            "can read above to anywhere. It can also reach programs on this computer that",
            "listen only locally (for example a local web app or database), and computers",
            "on your local network and VPN.",
        ]
    else:
        lines.append("Internet: off. Codex can reach only the model.")
    if setup.internet and setup.browser:
        lines.append(f"Browser tool: ON. {BROWSER_PLAIN}")
        lines.append(
            "  It asks you before each browser action (opening pages, clicking, typing);"
            " reading a page doesn't ask."
            if setup.browser_asks
            else "  It doesn't ask you before browser actions."
        )
    elif setup.internet:
        lines.append("Browser tool: off.")
    lines.append(f"Model: {setup.model}")
    if setup.approvals == "never":
        lines.append("Approvals: Codex runs commands without asking.")
    else:
        lines.append("Approvals: Codex asks you before commands.")
    lines += [
        "",
        "Your Toolkit key stays on this computer; the container never sees it.",
        "",
    ]
    return lines


LOCAL_PLAIN = "Codex runs on this computer, not in the sandbox: it can do anything you can do on this Mac."


def local_summary(setup: Setup, layout: folders.Layout) -> list[str]:
    """The summary of a setup that runs on this computer (M4)."""
    lines = ["", f"Setup: {setup.name}", "", f"ON THIS COMPUTER. {LOCAL_PLAIN}", "", "Its project folders:"]
    lines.append(f"  {layout.working}")
    lines += [f"  {host}" for host, _ in layout.writes]
    lines += [f"  Note: {note}" for note in layout.notes]
    if setup.local_access == "folder":
        lines.append("Codex's commands can change only these folders (Codex's own sandbox).")
        if setup.computer_use:
            lines.append("That doesn't limit computer and browser control: they act through your apps.")
        lines.append(
            "Internet for Codex's commands: ON." if setup.internet else "Internet for Codex's commands: off."
        )
    else:
        lines.append("Codex can read, change and DELETE any of your files, not only these.")
        lines.append("Internet: ON, everything this Mac can reach (full access doesn't limit it).")
    lines.append(
        "Computer and browser control: ON (Computer Use and the app's own browser; not your Chrome "
        'yet). macOS asks you once for Screen Recording and Accessibility, for "Codex Computer Use".'
        if setup.computer_use
        else "Computer and browser control: off."
    )
    lines.append(f"Model: {setup.model}")
    lines.append(
        "Approvals: Codex runs commands without asking."
        if setup.approvals == "never"
        else "Approvals: Codex asks you before commands."
    )
    lines += [
        "",
        "Your Toolkit key stays in the keychain, but Codex runs as you here, so it may be able to reach it.",
        "",
    ]
    return lines


def choose(
    store: SetupStore,
    ask: Ask,
    say: Say,
    *,
    start_folder: Path | None,
    models: Callable[[], Sequence[str]] = lambda: (),
    own_data: Path | None = None,
) -> tuple[Setup, folders.Layout] | None:
    """The launch's setup questions, up to "Start? [Y/n]". None if the person stops.

    `start_folder` is the folder um-codex was started in, offered as a new
    setup's working folder. None when it was opened from the app (whose
    folder means nothing): then the last setup's working folder is offered,
    or else ~/Documents/UM-Codex."""
    setups = store.all()
    fallback = None
    if start_folder is None:
        fallback = setups[0].working if setups else str(app_folder())
    setup: Setup | None = None
    if setups:
        last = setups[0]
        if yes(ask, f"Use “{last.name}” again ({last.working})?", True):
            setup = last
        else:
            say("")
            say("Setups:")
            for number, item in enumerate(setups, 1):
                say(f"  {number}. {item.name}   ({item.working})")
            say("  n. A new setup")
            while True:
                answer = ask("Choose a number, or n [n]: ").strip().lower() or "n"
                if answer == "n":
                    break
                if answer.isdigit() and 1 <= int(answer) <= len(setups):
                    setup = setups[int(answer) - 1]
                    break
    if setup is None:
        setup = ask_setup(
            ask, say, start_folder=start_folder, models=models(), own_data=own_data, fallback=fallback
        )
    while True:
        try:
            layout = check(setup, own_data=own_data)
        except FolderRefused as refused:
            say("")
            say(f"This setup can't be used as it is: {refused}")
            if not yes(ask, "Change it now?", True):
                return None
            setup = ask_setup(
                ask,
                say,
                start_folder=start_folder,
                models=models(),
                existing=setup,
                own_data=own_data,
                fallback=fallback,
            )
            continue
        changed = moved(setup, own_data=own_data)
        if changed:
            say("")
            say("WARNING: a saved folder now leads somewhere else (a link was put in its path):")
            for saved, now in changed:
                say(f"  {saved}")
                say(f"    now goes to {now}")
            say("This can happen when something (an earlier launch, a sync, an unpacked archive)")
            say("replaced part of the path with a link. Check that this is what you want.")
            answer = ask("Type yes to use them where they go now, or press Enter to change the setup: ")
            if answer.strip().lower() != "yes":
                setup = ask_setup(
                    ask,
                    say,
                    start_folder=start_folder,
                    models=models(),
                    existing=setup,
                    own_data=own_data,
                    fallback=fallback,
                )
                continue
            setup = resolved(setup, layout)
        for line in summary(setup, layout):
            say(line)
        answer = ask("Start? [Y/n, or e to change the setup] ").strip().lower()
        if answer in ("", "y", "yes"):
            store.save(setup, used=True)
            return setup, layout
        if answer in ("e", "edit", "change"):
            setup = ask_setup(
                ask,
                say,
                start_folder=start_folder,
                models=models(),
                existing=setup,
                own_data=own_data,
                fallback=fallback,
            )
            continue
        if answer in ("n", "no"):
            if yes(ask, "Save this setup for next time anyway?", False):
                store.save(setup)
            return None


def manage(store: SetupStore, ask: Ask, say: Say, *, models: Callable[[], Sequence[str]] = lambda: (),
           remove_volume: Callable[[Setup], None] | None = None) -> None:  # fmt: skip
    """`um-codex setups`: list, edit and delete setups."""
    while True:
        setups = store.all()
        say("")
        if not setups:
            say("There are no saved setups yet. Run `um-codex` to make one.")
            return
        say("Saved setups (the last one used first):")
        for number, item in enumerate(setups, 1):
            net = "internet on" if item.internet else "internet off"
            net += ", browser tool" if item.internet and item.browser else ""
            say(f"  {number}. {item.name}   ({item.working}; {net}; {item.model})")
        answer = ask("Choose a number to edit or delete it, or press Enter to finish: ").strip()
        if not answer:
            return
        if not (answer.isdigit() and 1 <= int(answer) <= len(setups)):
            continue
        chosen = setups[int(answer) - 1]
        action = ask(f"“{chosen.name}”: e to edit, d to delete, Enter to go back: ").strip().lower()
        if action == "e":
            edited = ask_setup(ask, say, start_folder=Path(chosen.working), models=models(), existing=chosen)
            store.save(replace(edited, id=chosen.id))
            say("Saved.")
        elif action == "d" and yes(ask, f"Delete “{chosen.name}” and its Codex history?", False):
            store.delete(chosen.id)
            if remove_volume is not None:
                remove_volume(chosen)
            say("Deleted. Your folders themselves weren't touched.")
