---
name: autonomous-loop
description: "Use when the user says /autonomous-loop, use autonomous-loop, work autonomously until done, prevent early exit, keep going until quality gates pass, or asks Codex not to stop until a task list is complete. Enables the autonomous-loop CLI, creates and continuously maintains the Codex task plan with update_plan, implements the task, runs trusted gates from .codex/autoloop.project.json, and does not finish until every plan item is completed and verification gates pass."
---

# autonomous-loop

## What this is

autonomous-loop is infrastructure that runs in the background via Codex hooks. It exists for one reason: **to stop you from exiting before your work is actually done.**

You are the implementation agent. Your job is to write code, fix bugs, run tests, and ship the task the user gave you. autonomous-loop is not the task — it is a controller that watches your stop events and blocks premature exit when the latest Codex plan still has pending/in-progress items, verification gates still fail, or required files are still missing.

## Non-negotiable plan discipline

The latest Codex task plan is an enforcement input. The Stop hook reads transcript `update_plan` calls and blocks exit while any item is not `completed`.

Before doing implementation work:

1. Call `update_plan` with a concrete task list.
2. Keep exactly one task `in_progress` while work remains.
3. Mark tasks `completed` only after the code, docs, and tests for that task are actually done.
4. Add newly discovered required work to the plan instead of hiding it.
5. Before ending, ensure every plan item is `completed` and all verification gates pass.

Never mark the plan complete just to escape the loop. If gates fail, keep or restore an `in_progress` or `pending` item for the failing work.

## When the user says "use autonomous-loop" or "/autonomous-loop"

This means: **enable the loop, create/maintain the Codex task plan, then immediately start implementing the task.**

### Step 1: Check setup

Run:

```bash
autonomous-loop doctor --cwd "$PWD"
```

If this fails, report the setup problem and stop. Do not guess past a broken install.

### Step 2: Read trusted repo gates

Read `.codex/autoloop.project.json` to understand what verification commands and gate profiles exist. Do not invent verification commands.

You may also run this helper when available:

```bash
autonomous-loop agent-instructions --cwd "$PWD"
```

It prints the exact activation reminders, available gate profiles, and an AGENTS.md snippet.

### Step 3: Create the Codex task plan

Call `update_plan` before implementation. Use the user's requested outcome as the plan, not autonomous-loop setup itself. Keep the plan current throughout the task.

### Step 4: Enable the loop

Keep the contract minimal. One or two tasks with simple evidence is enough because the Codex plan and gate commands are the real release criteria.

```bash
autonomous-loop request enable --cwd "$PWD" \
  --objective "<one-line summary of the user's task>" \
  --task-json '{"id":"T1","title":"<task title>","required":true,"evidence":[{"kind":"pathChanged","glob":"src/**"}]}'
```

If the response includes `activation_mode: "direct-env"`, continue. If it returns a `claim_token`, include that exact token text in your next assistant message, then continue.

### Step 5: Do the actual work

Implement the task. Write the code. Run the tests. Fix what breaks. Keep going until everything passes.

The loop runs in the background. If you try to stop and your plan or gates are still red, the stop hook will block you and tell you what's still failing. Read that feedback, update the plan truthfully, fix the issues, and continue.

## Work loop

Repeat until released:

1. Implement the next plan item.
2. Run the relevant trusted gate commands from `.codex/autoloop.project.json`.
3. Fix failures.
4. Update the Codex plan truthfully.
5. Do not produce a final answer until the full plan is completed and gates pass.

You do not decide completion by vibe. The latest Codex plan plus trusted gates decide.

## Fresh context recovery

If this skill loads in an existing task or after a context reset:

1. Run `autonomous-loop status --cwd "$PWD"`.
2. Run `autonomous-loop doctor --cwd "$PWD"` if setup looks suspect.
3. Inspect the current Codex plan/task state in the conversation.
4. Continue from the first non-completed plan item.
5. Do not disable, pause, or release unless the user explicitly asks.

## Other commands (only if the user asks)

- **Status:** `autonomous-loop status --cwd "$PWD"`
- **Pause:** `autonomous-loop request pause --cwd "$PWD"`
- **Resume:** `autonomous-loop request resume --cwd "$PWD"`
- **Disable:** `autonomous-loop request disable --cwd "$PWD"`

These are user-facing controls. Do not run them on your own initiative.

## Rules

- **Do not confuse enabling the loop with doing the task.** Enabling is one CLI call. The task is everything after that.
- **Do not spend time crafting elaborate contracts.** A simple objective and basic evidence is enough. The Codex task plan plus gates verify completion.
- **Do not invent verification commands.** The trusted commands live in `.codex/autoloop.project.json`.
- **Do not claim work is complete because you think it is.** The latest Codex plan state plus trusted gates decide.
- **If `autonomous-loop doctor --cwd "$PWD"` fails, stop and tell the user.** Do not guess your way past setup problems.
- **If the stop hook blocks you, read its output carefully.** It tells you exactly what failed. Fix that, not something else.
