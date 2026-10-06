"""Tasks (tasks.py): requests, the person's approval, locked runs, what comes back."""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from umcodex import tasks
from umcodex.paths import data_dir
from umcodex.setups import Setup, SetupStore

SECRET = "Jane Q. Participant, MRN 4471923"  # stands for study data: must never come back


@pytest.fixture
def study(tmp_path: Path) -> Path:
    folder = tmp_path / "study"
    folder.mkdir()
    (folder / "phq.csv").write_text(f"name,score\n{SECRET},12\n", encoding="utf-8")
    return Path(os.path.realpath(folder))


@pytest.fixture
def store(study: Path) -> SetupStore:
    store = SetupStore()
    store.save(
        Setup(id="study-a1", name="study", working=str(study), internet=True, browser=True, tasks=True)
    )
    store.save(Setup(id="plain-b2", name="plain", working=str(study)))
    store.save(Setup(id="local-c3", name="local", working=str(study), tasks=True, runs_on="this-computer"))
    return store


def task_file(setup: str = "study", **extra: object) -> str:
    steps = "[]" if setup == "nosteps" else '["Compute mean PHQ-9 by cohort with n", "Fit a regression"]'
    lines = [
        'goal = "Mean PHQ-9 by cohort"',
        f'setup = "{"study" if setup == "nosteps" else setup}"',
        f"steps = {steps}",
    ]
    lines += [f"{key} = {json.dumps(value)}" for key, value in extra.items()]
    return "\n".join(lines) + "\n"


# --- Requests and answers -------------------------------------------------------


def test_a_request_waits_for_the_person(store):
    task = tasks.request(task_file(), store=store)
    assert tasks.status(task) == {"task": task.id, "state": "waiting", "setup": "study-a1", "max_runs": 10}
    with pytest.raises(tasks.TaskError, match="waiting for the person's approval"):
        tasks.run(task.id, "do it", store=store, launcher=lambda *a, **k: 0)


@pytest.mark.parametrize(
    ("setup", "extra", "words"),
    [
        ("plain", {}, "doesn't allow tasks"),
        ("local", {}, "only in the sandbox"),
        ("nobody", {}, "no saved setup"),
        ("study", {"max_runs": 0}, "max_runs"),
        ("study", {"max_runs": 51}, "max_runs"),
        ("study", {"hours": 25}, "hours"),
        ("nosteps", {}, "steps"),
    ],
)
def test_requests_that_cant_be_made(store, setup, extra, words):
    with pytest.raises(tasks.TaskError, match=words):
        tasks.request(task_file(setup, **extra), store=store)


def test_an_answer_is_given_once_and_declined_tasks_dont_run(store):
    task = tasks.request(task_file(), store=store)
    assert tasks.decide(task, approve=False, via="launcher")["state"] == "declined"
    with pytest.raises(tasks.TaskError, match="already answered"):
        tasks.decide(task, approve=True, via="launcher")
    with pytest.raises(tasks.TaskError, match="declined"):
        tasks.run(task.id, "do it", store=store, launcher=lambda *a, **k: 0)


def test_runs_count_down_and_expire(store, monkeypatch):
    task = tasks.request(task_file(max_runs=1, hours=1), store=store)
    state = tasks.decide(task, approve=True, via="launcher")
    assert state["state"] == "approved" and state["runs_left"] == 1
    tasks.run(task.id, "do it", store=store, launcher=lambda *a, **k: 0)
    assert tasks.status(task)["state"] == "used up"
    with pytest.raises(tasks.TaskError, match="used all"):
        tasks.run(task.id, "do it", store=store, launcher=lambda *a, **k: 0)

    later = tasks.request(task_file(hours=1), store=store)
    tasks.decide(later, approve=True, via="launcher")
    future = dt.datetime.now(dt.UTC) + dt.timedelta(hours=2)
    monkeypatch.setattr(tasks, "_now", lambda: future)
    assert tasks.status(later)["state"] == "expired"
    with pytest.raises(tasks.TaskError, match="expired"):
        tasks.run(later.id, "do it", store=store, launcher=lambda *a, **k: 0)


def test_a_setup_that_stops_allowing_tasks_stops_its_tasks(store, study):
    task = tasks.request(task_file(), store=store)
    tasks.decide(task, approve=True, via="launcher")
    store.save(Setup(id="study-a1", name="study", working=str(study), tasks=False))
    with pytest.raises(tasks.TaskError, match="doesn't allow tasks"):
        tasks.run(task.id, "do it", store=store, launcher=lambda *a, **k: 0)
    assert tasks.status(task)["runs_left"] == 10  # nothing was used


def test_task_ids_are_checked():
    for bad in ("../x", "ABCDEF12", "abc", "abcdefg1/"):
        with pytest.raises(tasks.TaskError):
            tasks.get_task(bad)


# --- A run ------------------------------------------------------------------


def approved(store: SetupStore) -> tasks.Task:
    task = tasks.request(task_file(), store=store)
    tasks.decide(task, approve=True, via="launcher")
    return task


def fake_codex(writes: dict[str, str], final: str = f"Done. Row 1 was {SECRET}."):
    """A launcher whose `codex exec` writes `writes` into the outbox."""
    seen = {}

    def launcher(setup, layout, *, say, extra_mounts, session):
        seen["setup"] = setup
        seen["mounts"] = {m.target: m for m in extra_mounts}
        out = seen["mounts"][tasks.HANDOFF_OUT].source
        meta = seen["mounts"][tasks.HANDOFF_META].source

        def run_exec(command, *, input, stdout, **_):
            seen["command"] = command
            seen["brief"] = input
            for name, text in writes.items():
                (out / name).write_text(text, encoding="utf-8")
            (meta / "final.md").write_text(final, encoding="utf-8")
            stdout.write(json.dumps({"type": "item", "text": SECRET}) + "\n")
            return subprocess.CompletedProcess(command, 0)

        seen["run_exec"] = run_exec
        return session(SimpleNamespace(spec=SimpleNamespace(agent="umcodex-agent-x")))

    return launcher, seen


def run_with(store, launcher, seen, **kwargs):
    task = approved(store)
    return task, tasks.run(
        task.id,
        "Mean PHQ-9 by cohort.",
        store=store,
        launcher=launcher,
        run_exec=lambda *a, **k: seen["run_exec"](*a, **k),
        **kwargs,
    )


GOOD = "cohort,year,mean_phq9,n\nA,2024,7.2,40\nB,2024,8.1,33\n"
MANIFEST = json.dumps({"files": [{"path": "by_cohort.csv", "kind": "aggregate_table", "count_column": "n"}]})


def test_a_run_is_locked_whatever_the_setup_says(store):
    launcher, seen = fake_codex({"by_cohort.csv": GOOD, "manifest.json": MANIFEST})
    run_with(store, launcher, seen)
    setup = seen["setup"]
    assert (setup.internet, setup.browser, setup.approvals, setup.runs_on) == (
        False,
        False,
        "never",
        "sandbox",
    )
    assert seen["mounts"][tasks.HANDOFF_IN].readonly and not seen["mounts"][tasks.HANDOFF_OUT].readonly
    assert seen["command"][:7] == ["docker", "exec", "-i", "-w", "/work", "umcodex-agent-x", "codex"]
    assert "exec" in seen["command"] and seen["command"][-1] == "-"
    assert seen["brief"].startswith(tasks.PREAMBLE.replace("{min_cell}", "11")[:40])
    assert "at least 11 participants" in seen["brief"] and seen["brief"].rstrip().endswith(
        "Mean PHQ-9 by cohort."
    )


def test_only_checked_aggregates_come_back(store):
    raw = f"name,score\n{SECRET},12\n"
    launcher, seen = fake_codex({"by_cohort.csv": GOOD, "rows.csv": raw, "manifest.json": MANIFEST})
    task, result = run_with(store, launcher, seen)
    assert result["status"] == "done"
    assert [r["path"] for r in result["released"]] == ["by_cohort.csv"]
    held = {h["path"] for h in result["held"]}
    assert "rows.csv" in held
    released = Path(result["released_folder"])
    assert (released / "by_cohort.csv").read_text(encoding="utf-8") == GOOD
    assert sorted(p.name for p in released.iterdir()) == ["by_cohort.csv"]
    # Codex's own words and events are held, never in the result.
    run_folder = released.parent
    assert (run_folder / "held" / "final.md").is_file() and (run_folder / "held" / "events.jsonl").is_file()
    shown = json.dumps(result) + (run_folder / "result.json").read_text(encoding="utf-8")
    assert SECRET not in shown and "4471923" not in shown
    audit = (data_dir() / "tasks" / "audit.jsonl").read_text(encoding="utf-8")
    assert SECRET not in audit and "4471923" not in audit
    events = [json.loads(line)["event"] for line in audit.splitlines()]
    assert events == ["requested", "approved", "run started", "run ended"]


def test_a_run_that_times_out_says_so_and_still_sorts_its_files(store):
    def launcher(setup, layout, *, say, extra_mounts, session):
        out = next(m.source for m in extra_mounts if m.target == tasks.HANDOFF_OUT)
        (out / "partial.csv").write_text(GOOD, encoding="utf-8")
        return session(SimpleNamespace(spec=SimpleNamespace(agent="a")))

    def slow(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    task = approved(store)
    result = tasks.run(task.id, "x", store=store, launcher=launcher, run_exec=slow, timeout_minutes=1)
    assert result["status"] == "timed out" and result["exit_code"] == 124
    assert result["released"] == [] and [h["path"] for h in result["held"]] == ["partial.csv"]  # no manifest


def test_files_from_the_assistant_go_in_read_only(store, tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "analysis.R").write_text("summary(lm(y ~ x))\n", encoding="utf-8")
    launcher, seen = fake_codex({"manifest.json": MANIFEST, "by_cohort.csv": GOOD})
    task = approved(store)
    tasks.run(
        task.id,
        "Run analysis.R",
        inbox=inbox,
        store=store,
        launcher=launcher,
        run_exec=lambda *a, **k: seen["run_exec"](*a, **k),
    )
    mount = seen["mounts"][tasks.HANDOFF_IN]
    assert mount.readonly and (mount.source / "analysis.R").is_file()


def test_protected_paths_cover_task_setups_and_the_tasks_folder(store, study):
    paths = tasks.protected_paths(store=store)
    assert paths["study_folders"] == [str(study)]  # the plain setup's folder is the same one, once
    assert paths["umcodex_data"] == str(data_dir())
