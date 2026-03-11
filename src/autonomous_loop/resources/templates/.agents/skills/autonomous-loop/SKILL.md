---
name: autonomous-loop
description: Control the repo-local autonomous-loop for this repository: enable, status, pause, resume, disable, and release.
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

3. Read the returned `claim_token`.
4. Include that exact token in your next assistant message so the next `Stop` hook can bind the request to the live Codex session.

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

Then include the returned claim token in your next assistant message.

## Hard Rules

- Do not claim the loop is active until a `Stop` hook has actually claimed the request.
- Do not invent verification commands outside `.codex/autoloop.project.json`.
- Do not say work is complete just because the model thinks it is done.
