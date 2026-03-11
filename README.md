# Autonomous Loop

`autonomous-loop` is a Codex hook runtime that keeps a task open until deterministic evidence and trusted repo-defined gates say it is done.

The runtime is intentionally outside the model loop. Codex can propose the contract and do the work, but the `Stop` hook checks the real repo state, runs the trusted commands from repo config, and decides whether the session can end. That reduces the common failure mode where the agent reports completion before the task is actually green.

## What It Does

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

## Install

Install the package:

```bash
python3 -m pip install .
```

Install repo-local support files into a target project:

```bash
autonomous-loop install-repo --repo /path/to/repo
```

For Node-style repos, `install-repo` currently:

- requires `package.json`
- detects the package manager with this precedence:
  - `--package-manager`
  - `package.json.packageManager`
  - lockfiles
- trusts only these script names: `typecheck`, `lint`, `test`
- generates `.codex/autoloop.project.json`
- copies `.codex/hooks.json`
- copies `.agents/skills/autonomous-loop/SKILL.md`
- preserves existing copies of those repo-local files unless you pass `--force`

The generated config contains explicit argv arrays for trusted commands plus `fast`, `default`, and `final` gate profiles.

Example overrides:

```bash
autonomous-loop install-repo --repo /path/to/repo --package-manager npm
autonomous-loop install-repo --repo /path/to/repo --prefer-scripts lint,test
```

`--prefer-scripts` is a single comma-separated argument.

Current `install-repo` autodetect scope is Node-style repos with `package.json`. For non-Node repos, install the repo-local support files you need and write `.codex/autoloop.project.json` manually.

## Codex Setup

Repo-local install is not the whole setup. To use the loop from Codex, also:

1. copy [`skills/autonomous-loop/SKILL.md`](skills/autonomous-loop/SKILL.md) to `$CODEX_HOME/skills/autonomous-loop/SKILL.md`
2. merge [`templates/.codex/hooks.json`](templates/.codex/hooks.json) into the `hooks.json` file for the Codex config layer you actually use

If `$CODEX_HOME` is unset, Codex usually defaults to `~/.codex`.

## Typical Flow

1. run `autonomous-loop install-repo --repo /path/to/repo`
2. install the global skill and global hooks
3. use the `autonomous-loop` skill in Codex
4. the skill runs `autonomous-loop request enable ...`
5. confirm whether the response is `direct-env` or fallback claim-token
6. work normally until the trusted stop checks release the run

## Scope and Isolation

Runtime state is scoped by `repo_hash + session_id`. One repo does not interfere with another, and separate Codex sessions in the same repo get separate runtime state, contracts, ledgers, and logs.

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
