"""Tasks: an outside assistant hands UM-Codex a step that touches study data.

UM-Codex is approved for sensitive study data; an assistant like Claude
isn't. A task lets the assistant plan the work and write code, while only
Codex, in the sandbox, reads the data:

1. The assistant writes a task file (its goal, the setup, the steps in plain
   words, how many runs, for how long) and asks with `um-codex task request`.
2. The person approves it in the launcher window (or, in a real terminal,
   `um-codex task approve`). That gives the task a grant: so many runs, until
   a time. The assistant can't approve it: the launcher needs its signed-in
   browser session, the command a person typing.
3. Each `um-codex task run` starts the setup with its settings locked (no
   internet, no browser tool, no questions) and runs `codex exec` with the
   brief. Codex writes its results to /handoff/out with a manifest.json.
4. The disclosure check (disclosure.py) moves each result to released/ (an
   aggregate that passes) or held/ (everything else, for the person only).
   Codex's own messages are always held. The assistant reads result.json and
   released/, nothing else.

Only setups with `tasks` on can be used: the person decides which folders a
task can ever reach. Every request, decision and run goes in audit.jsonl,
without content.
"""

from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from umcodex import disclosure, locks
from umcodex.containers import BindMount
from umcodex.folders import FolderRefused
from umcodex.paths import data_dir
from umcodex.setups import Setup, SetupStore, check, moved

log = logging.getLogger(__name__)

MAX_RUNS = 50
MAX_HOURS = 24
DEFAULT_TIMEOUT_MINUTES = 60
TASK_ID_BYTES = 4

HANDOFF_IN = "/handoff/in"
HANDOFF_OUT = "/handoff/out"
HANDOFF_META = "/handoff/meta"  # Codex's last message: held, for the person

# Put before every brief, whatever it says: where results go and what may be in them.
PREAMBLE = f"""\
You are running a UM-Codex task, headless: nobody can answer questions, so
make reasonable choices and say what you chose in your final message.

The study data you can see is sensitive. An assistant that is NOT approved
to see it will read only the results that pass an automatic disclosure check.
Rules for your results:
- Write every result file to {HANDOFF_OUT}, and list each one in
  {HANDOFF_OUT}/manifest.json:
  {{"files": [{{"path": "by_cohort.csv", "kind": "aggregate_table", "count_column": "n"}},
             {{"path": "summary.json", "kind": "aggregate_json", "count_fields": ["n"]}}]}}
- Only aggregates: tables (CSV) or JSON where every row or group has a count of
  at least {{min_cell}} participants in its count column: DISTINCT PEOPLE behind
  that row, not observations, visits or responses. No participant-level rows,
  no identifiers (IDs, names, contact details, exact dates, places smaller than a
  state), no free text written by participants.
- Groups smaller than {{min_cell}}: combine them or leave them out, and say so.
- Anything else (plots, notes, tables that can't meet these rules) may go in
  {HANDOFF_OUT} too: it's held for the person to review, not passed on.
- Files the assistant sent you, if any, are in {HANDOFF_IN} (read only).
Your final message is kept for the person only.

The task:
"""


class TaskError(Exception):
    """A task request, approval or run that can't go ahead, in plain words."""


def tasks_dir(data: Path | None = None) -> Path:
    return (data or data_dir()) / "tasks"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _stamp(when: dt.datetime) -> str:
    return when.isoformat(timespec="seconds")


def audit(event: str, data: Path | None = None, **details: object) -> None:
    """One line in audit.jsonl: what happened and when, never content."""
    folder = tasks_dir(data)
    folder.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"at": _stamp(_now()), "event": event, **details}, ensure_ascii=False)
    with locks.held(folder / "audit.lock"), (folder / "audit.jsonl").open("a", encoding="utf-8") as file:
        file.write(line + "\n")


# --- Requests ---------------------------------------------------------------


@dataclass(frozen=True)
class Request:
    goal: str
    setup_id: str
    steps: tuple[str, ...]
    max_runs: int
    hours: float


def _text(raw: dict, field: str, limit: int) -> str:
    value = raw.get(field)
    if not isinstance(value, str) or not value.strip():
        raise TaskError(f"The task file needs “{field}” (text).")
    if len(value) > limit:
        raise TaskError(f"The task's “{field}” is longer than {limit} characters.")
    return value.strip()


def parse_request(text: str, store: SetupStore) -> Request:
    """A task file (TOML): goal, setup (its id or name), steps, max_runs, hours."""
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise TaskError(f"The task file isn't valid TOML: {error}") from None
    goal = _text(raw, "goal", 2000)
    wanted = _text(raw, "setup", 200)
    steps = raw.get("steps", [])
    if not isinstance(steps, list) or not steps or not all(isinstance(s, str) and s.strip() for s in steps):
        raise TaskError("The task file needs “steps”: a list of the planned steps, in plain words.")
    if len(steps) > 30 or any(len(s) > 1000 for s in steps):
        raise TaskError("The task's steps are too many or too long (30 steps, 1000 characters each).")
    max_runs = raw.get("max_runs", 10)
    if not isinstance(max_runs, int) or isinstance(max_runs, bool) or not 1 <= max_runs <= MAX_RUNS:
        raise TaskError(f"“max_runs” must be a whole number from 1 to {MAX_RUNS}.")
    hours = raw.get("hours", 8)
    if not isinstance(hours, int | float) or isinstance(hours, bool) or not 0 < hours <= MAX_HOURS:
        raise TaskError(f"“hours” must be more than 0 and at most {MAX_HOURS}.")
    setup = task_setup(store, wanted)
    return Request(goal, setup.id, tuple(s.strip() for s in steps), max_runs, float(hours))


def task_setup(store: SetupStore, wanted: str) -> Setup:
    """The saved setup (by id, else name) that tasks may use."""
    setups = store.all()
    setup = next((s for s in setups if s.id == wanted), None) or next(
        (s for s in setups if s.name == wanted), None
    )
    if setup is None:
        raise TaskError(f"There's no saved setup called “{wanted}”.")
    if setup.on_this_computer:
        raise TaskError(
            f"“{setup.name}” runs on this computer, not in the sandbox: tasks run only in the sandbox."
        )
    if not setup.tasks:
        raise TaskError(
            f"“{setup.name}” doesn't allow tasks. The person can turn on “Allow tasks” in its Edit "
            "form, in UM-Codex."
        )
    return setup


def locked(setup: Setup) -> Setup:
    """A task's settings, whatever the setup says: no internet, no browser
    tool, no questions (nobody's there to answer), in the sandbox."""
    return dataclasses.replace(
        setup, internet=False, browser=False, browser_asks=False, approvals="never", runs_on="sandbox"
    )


@dataclass
class Task:
    id: str
    folder: Path

    @property
    def request_file(self) -> Path:
        return self.folder / "request.json"

    @property
    def grant_file(self) -> Path:
        return self.folder / "grant.json"

    @property
    def lock_file(self) -> Path:
        return self.folder / "task.lock"

    def request(self) -> dict:
        return json.loads(self.request_file.read_text(encoding="utf-8"))

    def grant(self) -> dict | None:
        try:
            return json.loads(self.grant_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None


def get_task(task_id: str, data: Path | None = None) -> Task:
    if not re.fullmatch(f"[0-9a-f]{{{TASK_ID_BYTES * 2}}}", task_id):
        raise TaskError(f"“{task_id}” isn't a task id.")
    folder = tasks_dir(data) / task_id
    if not (folder / "request.json").is_file():
        raise TaskError(f"There's no task {task_id}.")
    return Task(task_id, folder)


def all_tasks(data: Path | None = None) -> list[Task]:
    folder = tasks_dir(data)
    if not folder.is_dir():
        return []
    found = [Task(f.name, f) for f in folder.iterdir() if (f / "request.json").is_file()]
    return sorted(found, key=lambda t: t.request().get("requested_at", ""), reverse=True)


def request(text: str, *, store: SetupStore | None = None, data: Path | None = None) -> Task:
    """Save a task request; it waits for the person's approval."""
    store = store or SetupStore()
    asked = parse_request(text, store)
    task_id = secrets.token_hex(TASK_ID_BYTES)
    folder = tasks_dir(data) / task_id
    folder.mkdir(parents=True)
    record = {
        "id": task_id,
        "goal": asked.goal,
        "setup_id": asked.setup_id,
        "steps": list(asked.steps),
        "max_runs": asked.max_runs,
        "hours": asked.hours,
        "requested_at": _stamp(_now()),
    }
    (folder / "request.json").write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    audit("requested", data, task=task_id, setup=asked.setup_id, max_runs=asked.max_runs, hours=asked.hours)
    return Task(task_id, folder)


def status(task: Task, *, now: dt.datetime | None = None) -> dict:
    """What the assistant may know about a task: no content."""
    asked = task.request()
    grant = task.grant()
    now = now or _now()
    state = "waiting"
    if grant is not None:
        if grant.get("declined"):
            state = "declined"
        elif dt.datetime.fromisoformat(grant["expires_at"]) <= now:
            state = "expired"
        elif grant["runs_left"] <= 0:
            state = "used up"
        else:
            state = "approved"
    out = {"task": task.id, "state": state, "setup": asked["setup_id"], "max_runs": asked["max_runs"]}
    if grant is not None and not grant.get("declined"):
        out |= {"runs_left": grant["runs_left"], "expires_at": grant["expires_at"]}
    return out


def decide(task: Task, *, approve: bool, via: str, data: Path | None = None) -> dict:
    """The person's answer to a waiting request. `via` says where it was
    given (the launcher window, or a terminal), for the audit."""
    with locks.held(task.lock_file):
        if task.grant() is not None:
            raise TaskError("This task was already answered.")
        asked = task.request()
        now = _now()
        if approve:
            grant = {
                "approved_at": _stamp(now),
                "expires_at": _stamp(now + dt.timedelta(hours=asked["hours"])),
                "runs_left": asked["max_runs"],
                "via": via,
            }
        else:
            grant = {"declined": True, "answered_at": _stamp(now), "via": via}
        task.grant_file.write_text(json.dumps(grant, indent=2), encoding="utf-8")
    audit("approved" if approve else "declined", data, task=task.id, via=via)
    return status(task)


def _take_run(task: Task) -> None:
    """One run off the grant, or TaskError."""
    with locks.held(task.lock_file):
        grant = task.grant()
        if grant is None:
            raise TaskError("This task is waiting for the person's approval in UM-Codex.")
        if grant.get("declined"):
            raise TaskError("The person declined this task.")
        if dt.datetime.fromisoformat(grant["expires_at"]) <= _now():
            raise TaskError("This task's approval has expired. Ask again with a new task request.")
        if grant["runs_left"] <= 0:
            raise TaskError("This task has used all its approved runs. Ask again with a new task request.")
        grant["runs_left"] -= 1
        task.grant_file.write_text(json.dumps(grant, indent=2), encoding="utf-8")


def _give_back_run(task: Task) -> None:
    with locks.held(task.lock_file):
        grant = task.grant()
        if grant is not None and not grant.get("declined"):
            grant["runs_left"] += 1
            task.grant_file.write_text(json.dumps(grant, indent=2), encoding="utf-8")


# --- Runs -------------------------------------------------------------------


def exec_command(agent: str) -> list[str]:
    """`codex exec`, headless, the brief on stdin; events on stdout (held)."""
    return [
        "docker", "exec", "-i", "-w", "/work", agent,
        "codex", "exec", "--skip-git-repo-check", "--json",
        "--output-last-message", f"{HANDOFF_META}/final.md", "-",
    ]  # fmt: skip


def brief_text(brief: str, *, min_cell: int) -> str:
    return PREAMBLE.replace("{min_cell}", str(min_cell)) + brief.strip() + "\n"


@dataclass(frozen=True)
class RunFolders:
    root: Path

    @property
    def inbox(self) -> Path:
        return self.root / "in"

    @property
    def out(self) -> Path:
        return self.root / "out"

    @property
    def meta(self) -> Path:
        return self.root / "meta"

    @property
    def held(self) -> Path:
        return self.root / "held"

    @property
    def released(self) -> Path:
        return self.root / "released"

    def make(self) -> None:
        for folder in (self.inbox, self.out, self.meta, self.held, self.released):
            folder.mkdir(parents=True, exist_ok=True)


def run(
    task_id: str,
    brief: str,
    *,
    inbox: Path | None = None,
    timeout_minutes: float = DEFAULT_TIMEOUT_MINUTES,
    min_cell: int = disclosure.MIN_CELL,
    data: Path | None = None,
    store: SetupStore | None = None,
    launcher: Callable[..., int] | None = None,
    run_exec: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    say: Callable[[str], None] = lambda text: None,
) -> dict:
    """One approved run of a task. Returns result.json's contents (also
    written in the run's folder)."""
    from umcodex import launch

    data = data or data_dir()
    store = store or SetupStore()
    task = get_task(task_id, data)
    asked = task.request()
    if not brief.strip():
        raise TaskError("The brief is empty.")
    setup = task_setup(store, asked["setup_id"])  # still allowed?
    try:
        layout = check(setup)
        if moved(setup):
            raise TaskError(
                f"A folder of “{setup.name}” now leads somewhere else: the person must check it in UM-Codex."
            )
    except FolderRefused as refused:
        raise TaskError(f"“{setup.name}” can't be used as it is: {refused}") from None
    _take_run(task)

    run_id = _stamp(_now()).replace(":", "").replace("+0000", "") + "-" + secrets.token_hex(2)
    folders = RunFolders(task.folder / "runs" / run_id)
    folders.make()
    if inbox is not None:
        if not inbox.is_dir():
            raise TaskError(f"{inbox} isn't a folder.")
        shutil.copytree(inbox, folders.inbox, dirs_exist_ok=True, symlinks=False)
    text = brief_text(brief, min_cell=min_cell)
    (folders.root / "brief.md").write_text(text, encoding="utf-8")
    audit("run started", data, task=task.id, run=run_id, setup=setup.id)

    outcome: dict[str, object] = {"code": None, "timed_out": False, "started": False}

    def session(running: launch.Running) -> int:
        outcome["started"] = True
        with (
            (folders.meta / "events.jsonl").open("w", encoding="utf-8") as events,
            (folders.meta / "stderr.log").open("w", encoding="utf-8") as errors,
        ):
            try:
                done = run_exec(
                    exec_command(running.spec.agent),
                    input=text,
                    stdout=events,
                    stderr=errors,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout_minutes * 60,
                )
            except subprocess.TimeoutExpired:
                outcome["timed_out"] = True
                return 124
        outcome["code"] = done.returncode
        return done.returncode

    mounts = (
        BindMount(folders.inbox, HANDOFF_IN, readonly=True),
        BindMount(folders.out, HANDOFF_OUT, readonly=False),
        BindMount(folders.meta, HANDOFF_META, readonly=False),
    )
    launcher = launcher or launch.run
    try:
        code = launcher(locked(setup), layout, say=say, extra_mounts=mounts, session=session)
    except Exception as error:  # the launch itself failed: still sort out what's there
        log.exception("task %s run %s: the launch failed", task.id, run_id)
        code = 1
        outcome["error"] = type(error).__name__

    if not outcome["started"]:
        _give_back_run(task)  # Codex never ran (no image, Docker trouble): the run isn't used up
    verdicts = disclosure.apply(folders.out, folders.released, folders.held, min_cell=min_cell)
    # Codex's own words (and its event stream) are the person's only.
    for name in os.listdir(folders.meta):
        shutil.move(str(folders.meta / name), str(folders.held / name))
    with contextlib.suppress(OSError):
        folders.meta.rmdir()
        folders.out.rmdir()

    result = {
        "task": task.id,
        "run": run_id,
        "status": "timed out"
        if outcome["timed_out"]
        else "done"
        if code == 0
        else "failed"
        if outcome["started"]
        else "not started",
        "exit_code": code,
        "released_folder": str(folders.released),
        "released": [_verdict(v) for v in verdicts if v.released],
        # The manifest itself is held too, but isn't a result: not listed.
        "held": [_verdict(v) for v in verdicts if not v.released and v.path != "manifest.json"],
        "note": (
            "Only released files may be read. Held files (and Codex's own messages) are for "
            "the person, in UM-Codex."
        ),
    }
    if "error" in outcome:
        result["error"] = f"UM-Codex couldn't start the run ({outcome['error']}); see um-codex.log."
    (folders.root / "result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    audit(
        "run ended",
        data,
        task=task.id,
        run=run_id,
        status=result["status"],
        released=len(result["released"]),  # type: ignore[arg-type]
        held=len(result["held"]),  # type: ignore[arg-type]
    )
    return result


def _verdict(verdict: disclosure.Verdict) -> dict:
    out: dict[str, object] = {"path": verdict.path, "reason": verdict.reason}
    if verdict.rows is not None:
        out["rows"] = verdict.rows
    if verdict.columns is not None:
        out["columns"] = verdict.columns
    return out


def protected_paths(*, store: SetupStore | None = None, data: Path | None = None) -> dict[str, object]:
    """What an assistant must never read: every folder of a setup that allows
    tasks, and UM-Codex's whole data folder (its launcher's sign-in, tasks'
    answers and outputs), apart from task runs' released/ folders."""
    store = store or SetupStore()
    study: list[str] = []
    for setup in store.all():
        if setup.tasks:
            study += [setup.working, *setup.writes, *setup.reads]
    return {
        "study_folders": sorted(dict.fromkeys(str(Path(p).expanduser()) for p in study)),
        "umcodex_data": str(data or data_dir()),
        "readable": "tasks/<task>/runs/<run>/released/",
    }
