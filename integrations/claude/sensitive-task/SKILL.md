---
name: sensitive-task
description: Run a task that needs sensitive study data by handing the data steps to UM-Codex (approved for study data) and doing everything else yourself. Use when the person describes work that needs study data (participant-level data in a UM-Codex setup that allows tasks), or says "sensitive task", "use UM-Codex for the data", or invokes /sensitive-task.
---

# Sensitive tasks through UM-Codex

You (Claude) are NOT approved to see sensitive study data. UM-Codex is: it runs Codex on U-M GPT in a sandbox, with no internet for tasks. Split the work so that only UM-Codex ever reads the data, and you see only results that passed UM-Codex's disclosure check.

The `protect-study-data` hook refuses any tool call that names a study folder or UM-Codex's task internals. If it blocks you, don't look for another way to the same files: that refusal is the boundary working.

## 1. Plan the split

- **You do:** understanding the request, choosing methods, reading docs and literature, writing code (R, Python, SQL), and drafting the report, slides or figures from released aggregates. Also anything about the data's *shape* that the person tells you or that comes back as an aggregate.
- **UM-Codex does:** every step that opens the data. That includes exploring it: ask for an aggregate profile (counts, missingness, ranges as binned counts), never for rows.
- Prefer few, well-specified runs. Each run starts a fresh, headless Codex with no memory of earlier runs, apart from the files in the setup's folders.

## 2. Ask for the task (once)

Write `task.toml` in your scratch folder:

```toml
goal = "Mean PHQ-9 by cohort and year, and a regression of PHQ-9 on work hours"
setup = "IHS study"          # a UM-Codex setup with "Allow tasks" on
steps = [
  "Profile the PHQ-9 and work-hours tables: counts and missingness by cohort and year",
  "Compute mean PHQ-9 by cohort and year, with n",
  "Fit the regression in analysis.R and report coefficients with n",
]
max_runs = 6      # 1-50
hours = 4         # how long the approval lasts, at most 24
```

Run `um-codex task request task.toml`. It prints JSON with the task id and `"state": "waiting"`. Tell the person, in one line:
- what you asked for;
- that they approve it in the UM-Codex window, or in their own terminal with `um-codex task approve <id>`.

**Never approve, decline or edit a task yourself.** Check with `um-codex task status <id>` once they say it's done. Don't poll in a tight loop.

## 3. Each data step: a brief, then a run

Write a brief (`brief-1.md`). UM-Codex adds its own rules about the outbox and cell sizes in front of it. Yours should say:
- exactly what to compute, and from which files or tables, as the person described them;
- the output files: names, columns and a count column `n` in every table. Coefficients, means and so on each go with the `n` they're based on;
- what to do with small groups: combine or drop them, and say so;
- if you wrote code, that it's in `/handoff/in/` and how to run it. Code goes in through `--inbox`, never pasted data.

Run:

```sh
um-codex task run --task <id> --brief brief-1.md [--inbox ./code] [--timeout 60]
```

It prints `result.json`:
- `status`;
- `released`: the files you may read, under `released_folder`;
- `held`: names and reasons only.

## 4. Use what came back

- Read only files under `released_folder`.
- For held files, tell the person their names and reasons. They can review and release them in the UM-Codex window if they want you to have them. Don't ask them to paste held content to you; if they choose to, that's their call.
- Codex's own final message is always held. If you need to know what it did, ask for it in a released file, for example a JSON "decisions" summary with counts.
- If a run failed or its results were held, fix the brief (smaller groups combined, an `n` column added, no identifiers) and run again, within the approved runs.

## 5. Finish

Do the rest yourself from the released aggregates: the report, figures, code and write-up. Say plainly which numbers came from UM-Codex runs (task id and run id), and anything you couldn't do because results were held.
