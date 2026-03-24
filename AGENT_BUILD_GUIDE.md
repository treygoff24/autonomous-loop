# Agent Build Guide

If you are an agent and the user wants `autonomous-loop` installed, working, or debugged, start here.

This guide is the shortest reliable path. Follow it in order. Do not improvise around the install flow unless a step fails and you have evidence for why.

## What you are setting up

`autonomous-loop` has two layers:

1. machine bootstrap, once per machine
2. repo install, once per target repo

Machine bootstrap writes:

- `$CODEX_HOME/hooks.json`
- `$CODEX_HOME/skills/autonomous-loop/SKILL.md`
- `$CODEX_HOME/autoloop/machine.json`

Repo install writes:

- `.codex/autoloop.project.json`
- `.codex/hooks.json`
- `.agents/skills/autonomous-loop/SKILL.md`

Mutable runtime state lives under `$CODEX_HOME/autoloop`. It does not live in the target repo.

## Fast path

From the `autonomous-loop` repo:

```bash
python3 -m pip install .
autonomous-loop bootstrap
autonomous-loop doctor
autonomous-loop install-repo --repo /path/to/repo
autonomous-loop doctor --cwd /path/to/repo
```

If all five commands succeed, stop there. The install is good.

If Codex was already open before bootstrap, restart it once so it reloads the global hooks and skill.

## How to tell whether the install is healthy

Use `doctor` first. It is the source of truth.

```bash
autonomous-loop doctor
autonomous-loop doctor --cwd /path/to/repo
```

Healthy output means:

- `cli_on_path.ok` is `true`
- `machine_config.ok` is `true`
- `global_hooks.ok` is `true`
- `global_skill.ok` is `true`
- `repo_install.ok` is `true` for the target repo

`runtime_hygiene` is advisory. Warnings there do not mean the install is broken. They mean old runtime state has piled up and should be cleaned or allowed to auto-clean on the next real session start.

## If the install is broken

### `cli_on_path` failed

The shell cannot resolve the right `autonomous-loop` launcher.

Fix the launcher on `PATH`, then rerun:

```bash
autonomous-loop doctor
```

If the command on `PATH` is older than the one in machine bootstrap, `doctor` will say so directly.

### `machine_config` failed

Bootstrap is missing or stale. Run:

```bash
autonomous-loop bootstrap --force
autonomous-loop doctor
```

### `global_hooks` or `global_skill` failed

Re-bootstrap and restart Codex if it was already open:

```bash
autonomous-loop bootstrap --force
autonomous-loop doctor
```

### `repo_install` failed

Reinstall the repo-local files:

```bash
autonomous-loop install-repo --repo /path/to/repo --force
autonomous-loop doctor --cwd /path/to/repo
```

## If the loop seems stuck or messy

Check runtime status:

```bash
autonomous-loop status --cwd /path/to/repo
```

That output now includes:

- live sessions
- live pending requests
- archived artifact counts
- a hygiene summary

If you see stale sessions or old requests, clean them:

```bash
autonomous-loop cleanup --cwd /path/to/repo
```

Default cleanup behavior:

- stale active sessions older than 8 hours are archived
- unclaimed pending requests older than 8 hours are archived
- old paused sessions, inactive sessions, and historical applied requests older than 24 hours are archived

Cleanup is archive-first. It moves old artifacts out of the live runtime path and preserves them under the repo runtime root.

## If enable does not bind

There are two activation paths.

### Direct bind

If the environment exposes `CODEX_SESSION_ID` or `CODEX_THREAD_ID`, `request enable` binds immediately to the current live session.

### Claim-token fallback

If there is no live session ID, the CLI returns `AUTOLOOP_CLAIM:<nonce>`. The next assistant message must include that exact token, and that turn must actually end so the next real `Stop` hook can claim it.

If the request stays pending, check:

1. the exact token appeared in the assistant message
2. the turn actually ended
3. the repo path matched the intended repo

## Recommended operating sequence for agents

If the user asks you to install or repair `autonomous-loop`, use this order:

1. run `autonomous-loop doctor`
2. run `autonomous-loop doctor --cwd /path/to/repo` if a target repo exists
3. fix the first failing check instead of guessing
4. rerun the same `doctor` command after each fix
5. only then use `request enable` or other runtime actions

## Read next

- [`README.md`](README.md)
- [`docs/install.md`](docs/install.md)
- [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md)
