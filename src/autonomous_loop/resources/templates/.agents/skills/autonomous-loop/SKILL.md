---
name: autonomous-loop
description: "Control the repo-local autonomous-loop for this repository: enable, status, pause, resume, disable, and release."
---

# Repo-local autonomous-loop

Read these files first:

- `.codex/autoloop.project.json`
- `.agents/skills/autonomous-loop/SKILL.md`

Use the shared `autonomous-loop` CLI as the runtime. Mutable state lives under `CODEX_HOME`, not in this repo.

## Enable

When the user asks to enable the loop:

1. Synthesize a compact deterministic contract for the current agreed task.
2. Run:

```bash
autonomous-loop request enable --cwd "$PWD" --objective "<objective>" --task-json '<task-json>'
```

3. Inspect the response:
   - if it includes `activation_mode: "direct-env"`, the loop is already bound to the current Codex thread
   - otherwise read the returned `claim_token`
4. In the fallback path, include that exact token in your next assistant message so the next `Stop` hook can bind the request to the live Codex session.

## Status

Run:

```bash
autonomous-loop status --cwd "$PWD"
```

## Pause, Resume, Disable, Release

Queue the matching request:

```bash
autonomous-loop request <pause|resume|disable|release> --cwd "$PWD"
```

If the response includes `activation_mode: "direct-env"`, the change is already bound to the current Codex thread. Otherwise include the returned claim token in your next assistant message.

## Hard Rules

- Do not claim the loop is active until direct-env activation is confirmed or a `Stop` hook has actually claimed the request.
- A direct-env enable response is already active and does not need a claim token.
- Do not invent verification commands outside `.codex/autoloop.project.json`.
- Do not say work is complete just because the model thinks it is done.
