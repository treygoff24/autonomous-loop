---
name: autonomous-loop
description: Install and control the Codex autonomous-loop runtime. Use this when the user wants to enable, pause, resume, disable, release, inspect, or install the loop.
---

## Codex usage

- Purpose: install repo templates, wire the current repo to the shared runtime, and operate the current repo plus current session loop.
- Reads: the current repo plus this cloned autonomous-loop repo.
- Writes: repo-local `.codex/autoloop.project.json`, repo-local skill files, and pending runtime requests under `CODEX_HOME/autoloop/`.
- Runtime state does not live in this skill directory.

# Autonomous-loop workflow

## Install a repo

Run:

```bash
autonomous-loop install-repo --repo "$PWD"
```

Then make sure the repo-local `.codex/autoloop.project.json` command refs and gate profiles match that repository.

## Enable the loop

1. Read the current repo-local `.codex/autoloop.project.json`.
2. Synthesize a small deterministic contract from the current task.
3. Queue the request:

```bash
autonomous-loop request enable --cwd "$PWD" --objective "<objective>" --task-json '<task-json>'
```

4. Read the returned `claim_token`.
5. Include that exact token in your next assistant message. Without it, the live `Stop` hook cannot bind the request to the actual Codex session.

## Status

Run:

```bash
autonomous-loop status --cwd "$PWD"
```

## Pause, Resume, Disable, Release

Queue the request:

```bash
autonomous-loop request <pause|resume|disable|release> --cwd "$PWD"
```

Then include the returned claim token in your next assistant message.

## Boundaries

- Do not write mutable runtime state into the repo.
- Do not register arbitrary shell strings as trusted gates.
- Do not say the loop is active until the next `Stop` hook has actually claimed the request.
- If the repo is missing `.codex/autoloop.project.json`, install it before trying to enable anything.
