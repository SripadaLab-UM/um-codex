# Tasks: an assistant hands UM-Codex the steps that touch study data

UM-Codex is approved for sensitive study data. Assistants like Claude aren't.
With tasks, you describe a piece of work to the assistant once:
- the assistant plans it and does everything that doesn't need the data (methods, code, write-up);
- it hands the data steps to UM-Codex;
- it reads back only aggregate results that pass an automatic disclosure check.

## How it works

1. **A setup that allows tasks.** In a setup's Edit form, turn on **Allow tasks from an assistant**.
   - Its internet stays off and its browser tool off, every time.
   - Only these setups' folders can ever be reached by a task.
2. **The assistant asks.** It writes a task file (goal, setup, steps, how many runs, for how long) and runs:

   ```sh
   um-codex task request task.toml
   ```
3. **You approve once.** The request shows at the top of the UM-Codex window, as **A task is waiting for you**. It shows the goal, the steps, the setup's folders and the limits.
   - **Approve** gives the task its runs until the time is up.
   - **Decline** ends it.
   - In a terminal you type in, `um-codex task approve <id>` does the same, and asks you to type the id.
4. **Runs.** Each run starts the setup in the sandbox with no internet, no browser tool and no questions. It runs Codex headless with the assistant's brief:

   ```sh
   um-codex task run --task <id> --brief brief.md [--inbox <folder of code>] [--timeout 60]
   ```

   UM-Codex puts its own rules in front of every brief. Codex then writes its results to an outbox, with a `manifest.json`.
5. **The disclosure check** (`src/umcodex/disclosure.py`) sorts each result:
   - **Sent back to the assistant:** aggregate tables (CSV, TSV or JSON) where every row has a count of at least 11 distinct people, with no identifier-like columns, exact dates, free text or long codes.
   - **Held for you:** everything else. That includes plots, notes, anything that fails the check, and always Codex's own messages.

   The assistant gets `result.json`: the released files, plus the held files' names and reasons. It never gets their content.
6. **Held results.** **Task results** in the UM-Codex window lists every run's held files.
   - **Show held files** opens them on your computer.
   - **Release to the assistant…** passes one on, after asking.

Every request, answer, run and release is recorded, without content, in `tasks/audit.jsonl` in UM-Codex's data folder.

## The assistant's side (Claude Code)

`integrations/claude/` has two pieces:

- **`protect-study-data.py`** is a PreToolUse hook. It refuses any tool call that names:
  - a folder of a setup that allows tasks;
  - UM-Codex's data folder, apart from task runs' `released/` folders;
  - an answer to a task (`um-codex task approve` or `decline`, a grant file, the launcher's task or control addresses);
  - UM-Codex's containers.

  It asks `um-codex task protected-paths` which folders to protect.
- **`sensitive-task/SKILL.md`** is how Claude plans a task, writes briefs, runs them and uses what comes back.

To install, put the hook in `~/.claude/hooks/` and the skill in `~/.claude/skills/sensitive-task/`, then add the hook to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "*", "hooks": [{ "type": "command", "command": "python3 ~/.claude/hooks/protect-study-data.py" }] }
    ]
  }
}
```

## Limits to know

- **Counts:** a count of 11 or more doesn't prove a row covers 11 or more people if Codex counts observations instead. The rules ask for distinct people.
- **Not covered:** the check doesn't look for differencing between tables, or for values hidden in numbers.
- **Release carefully:** release a held file only after you've looked at it.
- **Approval:** the approval needs your signed-in UM-Codex window, or your typing. The hook stops Claude from reaching the approval through commands. An assistant that drives a browser could still click **Approve** in the window, so Claude's instructions forbid it. Keep the UM-Codex window yours.
