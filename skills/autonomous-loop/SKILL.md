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

For Node-style repos, `install-repo` generates `.codex/autoloop.project.json` from `package.json`, `packageManager`, lockfiles, and the supported scripts `typecheck`, `lint`, and `test`. For non-Node repos, install the hooks and repo-local skill, then write `.codex/autoloop.project.json` manually.

## Enable the loop

1. Read the current repo-local `.codex/autoloop.project.json`.
2. Synthesize a small deterministic contract from the current task.
3. Queue the request:

```bash
autonomous-loop request enable --cwd "$PWD" --objective "<objective>" --task-json '<task-json>'
```

4. Inspect the response:
   - if it includes `activation_mode: "direct-env"`, the loop is already bound to the current Codex thread
   - otherwise read the returned `claim_token`
5. In the fallback path, include that exact token in your next assistant message, and let that turn end normally. Without the token in `last_assistant_message`, the live `Stop` hook cannot bind the request to the actual Codex session.
6. Do not claim the loop is active until either the direct-env response confirms it or a later `autonomous-loop status --cwd "$PWD"` call shows the request as applied or the session as active.

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

If the response includes `activation_mode: "direct-env"`, the change is already bound to the current Codex thread. Otherwise include the returned claim token in your next assistant message and let that turn end so the next real `Stop` hook can claim it.

## Boundaries

- Do not write mutable runtime state into the repo.
- Do not register arbitrary shell strings as trusted gates.
- Do not say the loop is active until direct-env activation is confirmed or the next `Stop` hook has actually claimed the request.
- Expect `status` to keep showing `pending` if you check it before that token-bearing assistant turn has ended.
- If the repo is missing `.codex/autoloop.project.json`, install it before trying to enable anything.
