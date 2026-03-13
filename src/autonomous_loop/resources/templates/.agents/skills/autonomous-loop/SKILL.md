---
name: autonomous-loop
description: "Autonomous persistence layer — keeps you implementing until the task genuinely passes all verification gates. You are the builder; the loop is the safety net."
---

# autonomous-loop

## What this is

autonomous-loop is infrastructure that runs in the background via Codex hooks. It exists for one reason: **to stop you from exiting before your work is actually done.**

You are the implementation agent. Your job is to write code, fix bugs, run tests, and ship the task the user gave you. autonomous-loop is not the task — it is a controller that watches your stop events and blocks premature exit when verification gates (typecheck, lint, test) still fail or required files are still missing.

**You do not need to manage, operate, or think about the loop.** It manages you. Focus entirely on the implementation work.

## When the user says "use autonomous-loop" or "/autonomous-loop"

This means: **enable the loop, then immediately start implementing the task.**

### Step 1: Enable the loop (fast, mechanical — spend no time here)

Read `.codex/autoloop.project.json` to understand what verification commands exist, then run:

```bash
autonomous-loop request enable --cwd "$PWD" \
  --objective "<one-line summary of the user's task>" \
  --task-json '{"id":"T1","title":"<task title>","required":true,"evidence":[{"kind":"pathChanged","glob":"src/**"}]}'
```

Keep the contract minimal. One or two tasks with simple evidence. Do not over-engineer the contract — it is not the deliverable.

If the response includes `activation_mode: "direct-env"`, you're set. If it returns a `claim_token`, include that exact token text in your next message, then move on.

### Step 2: Do the actual work

This is the part that matters. Implement the task. Write the code. Run the tests. Fix what breaks. Keep going until everything passes.

The loop runs in the background. If you try to stop and your gates are still red, the stop hook will block you and tell you what's still failing. Read that feedback, fix the issues, and continue.

### Step 3: You're done when the loop releases you

You do not decide when you're done. The verification gates decide. When all required evidence is satisfied and all gate commands pass, the loop releases automatically. Until then, keep working.

## Other commands (only if the user asks)

- **Status:** `autonomous-loop status --cwd "$PWD"`
- **Pause:** `autonomous-loop request pause --cwd "$PWD"`
- **Resume:** `autonomous-loop request resume --cwd "$PWD"`
- **Disable:** `autonomous-loop request disable --cwd "$PWD"`

These are user-facing controls. Do not run them on your own initiative.

## Rules

- **Do not confuse enabling the loop with doing the task.** Enabling is one CLI call. The task is everything after that.
- **Do not spend time crafting elaborate contracts.** A simple objective and basic evidence is enough. The gates (typecheck/lint/test) are what actually verify completion.
- **Do not invent verification commands.** The trusted commands live in `.codex/autoloop.project.json`. You cannot add to them.
- **Do not claim work is complete because you think it is.** The gates decide.
- **If `autonomous-loop doctor --cwd "$PWD"` fails, stop and tell the user.** Do not guess your way past setup problems.
- **If the stop hook blocks you, read its output carefully.** It tells you exactly what failed. Fix that, not something else.
