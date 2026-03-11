# Autonomous Loop

`autonomous-loop` is a Codex hook runtime that keeps a task open until deterministic evidence and trusted repo-defined gates say it is done.

## Quickstart

1. Install the package:

```bash
python3 -m pip install .
```

2. Bootstrap this machine once:

```bash
autonomous-loop bootstrap
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
- `$CODEX_HOME/autoloop/machine.json`

`install-repo` writes the repo-local assets:

- `.codex/autoloop.project.json`
- `.codex/hooks.json`
- `.agents/skills/autonomous-loop/SKILL.md`

Pass `--force` to `bootstrap` to overwrite existing global hooks and skill files.

`install-repo` fails closed until machine bootstrap is complete. The repo-local hooks it generates are derived from the verified command path saved during `bootstrap`.

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
3. re-evaluates deterministic task evidence from the filesystem
4. runs the trusted commands referenced by the configured gate profile
5. blocks, releases, or hard-stops based on those results

If the contract hash changes unexpectedly, required runtime files are unreadable, or the same blocker repeats too many times, the runtime fails closed.

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

## Activation Model

There are two request paths.

### `direct-env`

If the Codex environment exposes `CODEX_SESSION_ID` or `CODEX_THREAD_ID`, `autonomous-loop request enable` binds immediately to that live session. The CLI response includes:

- `activation_mode: "direct-env"`
- `session_id`
- `session_id_source`

For follow-up actions, `request pause`, `request resume`, `request disable`, and `request release` use the same immediate path only when that session already has loop state.

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

For Node-style repos, `install-repo` currently:

- requires `package.json`
- detects the package manager with this precedence:
  - `--package-manager`
  - `package.json.packageManager`
  - lockfiles
- trusts only these script names: `typecheck`, `lint`, `test`
- preserves existing repo-local files unless you pass `--force`

Example overrides:

```bash
autonomous-loop install-repo --repo /path/to/repo --package-manager npm
autonomous-loop install-repo --repo /path/to/repo --prefer-scripts lint,test
```

`--prefer-scripts` is a single comma-separated argument.

Current `install-repo` autodetect scope is Node-style repos with `package.json`. For non-Node repos, install the repo-local support files you need and write `.codex/autoloop.project.json` manually.

## Read Next

- [`docs/install.md`](docs/install.md)
- [`docs/examples.md`](docs/examples.md)
- [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md)
- [`docs/security.md`](docs/security.md)
- [`docs/agent-implementation-brief.md`](docs/agent-implementation-brief.md)

## Current Assumptions

This project is built around the verified Codex CLI `0.114.0` hook model:

- `SessionStart` and `Stop` hooks exist
- hooks are discovered from `hooks.json`
- `Stop` groups are discovered without a matcher
- this controller currently relies on command hooks

The main upstream quirk is that live hook registration belongs in `hooks.json`, not `config.toml`.
