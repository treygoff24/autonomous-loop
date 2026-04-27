# Autonomous Loop

`autonomous-loop` is ralph loop but improved and ported to Codex. stop the early outs, force Codex to work until it's actually done and passes quality gates.

If you are using an agent to install or operate this, point it at [`AGENT_BUILD_GUIDE.md`](AGENT_BUILD_GUIDE.md) first. That file is the shortest path from zero to working setup, plus the fastest troubleshooting path when something feels off.

## Quickstart

### Install from GitHub

For friends or a second machine, install the tagged release directly from GitHub:

```bash
python3 -m pip install "git+https://github.com/treygoff24/autonomous-loop.git@v0.2.0"
```

If you use `pipx` for global CLI tools:

```bash
pipx install "git+https://github.com/treygoff24/autonomous-loop.git@v0.2.0"
```

This release is tested on Codex CLI `0.125.0` and requires Codex hook support with the `codex_hooks` feature enabled.

### Install from a local checkout

From this repo:

```bash
python3 -m pip install .
```

### Bootstrap and install a repo

1. Bootstrap this machine once:

```bash
autonomous-loop bootstrap
```

2. Verify machine setup:

```bash
autonomous-loop doctor
```

3. Install repo-local support files into a target repo:

```bash
autonomous-loop install-repo --repo /path/to/repo
```

4. Verify the result:

```bash
autonomous-loop doctor --cwd /path/to/repo
```

5. Open Codex in that repo and say: `Use /autonomous-loop for this task.`

If Codex was already running when you bootstrapped the machine, restart it once so it picks up the new global hooks and skill.

## Two-Step Onboarding Model

`autonomous-loop` now has two setup layers:

- Machine bootstrap: `autonomous-loop bootstrap`
- Repo install: `autonomous-loop install-repo --repo /path/to/repo`

`bootstrap` writes the machine-level assets under your Codex home:

- `$CODEX_HOME/hooks.json`
- `$CODEX_HOME/skills/autonomous-loop/SKILL.md`
- `$CODEX_HOME/skills/autonomous-loop/agents/openai.yaml`
- `$CODEX_HOME/autoloop/machine.json`

`install-repo` writes the repo-local assets:

- `.codex/autoloop.project.json`
- `.agents/skills/autonomous-loop/SKILL.md`
- `.agents/skills/autonomous-loop/agents/openai.yaml`

Pass `--force` to `bootstrap` to overwrite existing global hooks and skill files.

`install-repo` fails closed until machine bootstrap is complete. Repo-local hooks are intentionally **not** installed by default because the global `$CODEX_HOME/hooks.json` hook enforces the loop across profiles. Use `--install-hooks` only for an explicit repo-local opt-in.

## What The Runtime Does

When you enable the loop, the runtime freezes a contract for the current task. That contract records:

- the objective
- the required tasks
- the evidence each task needs
- the gate profile that decides whether the run can release

Mutable runtime state lives under `$CODEX_HOME/autoloop`, not inside the target repo. The repo only carries its local policy in `.codex/autoloop.project.json` plus the repo-local support files installed by `install-repo`.

At each real `Stop` hook, the runtime:

1. resolves the active repo and session
2. validates the saved contract and verification bundle
3. reads the latest Codex `update_plan` state from the hook transcript, if available
4. re-evaluates deterministic task evidence from the filesystem
5. runs the trusted commands referenced by the configured gate profile
6. blocks, releases, or hard-stops based on those results

If the contract hash changes unexpectedly, required runtime files are unreadable, or the same blocker repeats too many times, the runtime fails closed.

At each real `SessionStart` hook, the runtime now:

1. cleans stale runtime artifacts for the current repo
2. preserves the live current session
3. refreshes that session's heartbeat
4. injects continuity context only after hygiene has been applied

## CLI Reference

### `request enable`

```
autonomous-loop request enable --cwd <path> --objective <text> \
  [--task-json '<json>'] ... \
  [--gate-profile <name>] \
  [--max-stop-iterations <n>]
```

- `--cwd` (required) — repo working directory
- `--objective` (required) — task objective
- `--task-json` (repeatable, optional) — JSON task definition; may be repeated for multiple tasks
- `--gate-profile` (optional) — gate profile name
- `--max-stop-iterations` (optional) — maximum stop-hook iterations before hard-stop

### `request pause / resume / disable / release`

```
autonomous-loop request pause   --cwd <path> [--reason <text>]
autonomous-loop request resume  --cwd <path> [--reason <text>]
autonomous-loop request disable --cwd <path> [--reason <text>]
autonomous-loop request release --cwd <path> [--reason <text>]
```

- `--cwd` (required) — repo working directory
- `--reason` (optional) — human-readable reason logged with the action

### `status`

```
autonomous-loop status --cwd <path> [--session-id <id>]
```

- `--cwd` (required) — repo working directory
- `--session-id` (optional) — inspect a specific session instead of the active one

`status` includes a repo hygiene summary and archived artifact counts so stale state is visible without reading the runtime directories directly.

### `agent-instructions`

```
autonomous-loop agent-instructions --cwd <path>
```

- `--cwd` (required) — repo working directory

`agent-instructions` returns a JSON checklist for fresh Codex contexts: setup health, available trusted commands, gate profiles, an enable-command template, the reminder that `update_plan` is part of Stop-hook enforcement, and an AGENTS.md snippet you can paste into repo guidance.

### `cleanup`

```
autonomous-loop cleanup --cwd <path> [--stale-hours <n>] [--retention-hours <n>]
```

- `--cwd` (required) — repo working directory
- `--stale-hours` (optional, default `8`) — archive stale active sessions and unclaimed pending requests older than this threshold
- `--retention-hours` (optional, default `24`) — archive old paused sessions, inactive sessions, and historical applied requests older than this threshold

`cleanup` is archive-first rather than delete-first. It moves old artifacts out of the live runtime directories and keeps them under archived folders for later inspection.

## Activation Model

There are two request paths.

### `direct-env`

If the Codex environment exposes `CODEX_SESSION_ID` or `CODEX_THREAD_ID`, `autonomous-loop request enable` binds immediately to that live session. The CLI response includes:

- `activation_mode: "direct-env"`
- `session_id`
- `session_id_source`

For follow-up actions, `request pause`, `request resume`, `request disable`, and `request release` use the same immediate path only when that session already has loop state.

When a direct-env enable happens, the runtime also archives stale sibling live sessions for that repo before activating the new one. Explicitly paused sessions are retained until the longer retention window expires.

### Fallback claim-token activation

If no live session identifier is available, the CLI stores a pending request and returns JSON with a `claim_token` field whose value looks like:

```text
AUTOLOOP_CLAIM:<nonce>
```

In that path:

1. include the exact token in the next assistant message
2. let that turn end normally
3. the next real `Stop` hook claims the request for the live session

Until that stop event happens, `autonomous-loop status --cwd "$PWD"` can still show the request as pending.

## Install Notes

`install-repo` currently detects verification commands for Node, Make, Python, Rust, and Go repos.

For Node-style repos, it:

- requires `package.json`
- detects the package manager with this precedence:
  - `--package-manager`
  - `package.json.packageManager`
  - lockfiles
- prefers combined script names first: `check`, `quality`, `ci`
- otherwise trusts: `typecheck`, `lint`, `test`
- preserves existing repo-local files unless you pass `--force`

Example overrides:

```bash
autonomous-loop install-repo --repo /path/to/repo --package-manager npm
autonomous-loop install-repo --repo /path/to/repo --prefer-scripts lint,test
autonomous-loop install-repo --repo /path/to/repo --install-hooks
```

`--prefer-scripts` is a single comma-separated argument.

For non-Node repos, autodetect looks for standard Make targets, Python project files with concrete pytest/ruff/mypy signals, `Cargo.toml`, or `go.mod`. If no trustworthy command can be detected, write `.codex/autoloop.project.json` manually.

## Read Next

- [`AGENT_BUILD_GUIDE.md`](AGENT_BUILD_GUIDE.md)
- [`docs/install.md`](docs/install.md)
- [`docs/examples.md`](docs/examples.md)
- [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md)
- [`docs/security.md`](docs/security.md)
- [`docs/agent-implementation-brief.md`](docs/agent-implementation-brief.md)

## Current Assumptions

This project is built around the current Codex hook model:

- `SessionStart` and `Stop` hooks exist
- hooks are discovered from `hooks.json`
- `Stop` groups are discovered without a matcher
- this controller currently relies on command hooks

The main upstream quirk is that live hook registration belongs in `hooks.json`, not `config.toml`.
