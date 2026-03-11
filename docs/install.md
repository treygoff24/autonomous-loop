# Install

First-time setup is a two-step flow:

1. bootstrap the machine
2. install support files into each repo

Run `autonomous-loop doctor` after each step. It is the fastest way to see exactly what is missing.

## Machine Setup

Install the package:

```bash
python3 -m pip install .
```

Bootstrap the current machine once:

```bash
autonomous-loop bootstrap
```

Pass `--force` to overwrite existing global hooks and skill files:

```bash
autonomous-loop bootstrap --force
```

That command writes:

- `$CODEX_HOME/hooks.json`
- `$CODEX_HOME/skills/autonomous-loop/SKILL.md`
- `$CODEX_HOME/autoloop/machine.json`

Verify machine setup:

```bash
autonomous-loop doctor
```

Expected result: `ok: true`.

`doctor` runs the following checks and reports each as a field in the JSON output:

- `cli_on_path` — verifies `autonomous-loop` is discoverable on `PATH`
- `machine_config` — validates `$CODEX_HOME/autoloop/machine.json` exists and that `command_path` is absolute, exists, and is executable
- `global_hooks` — verifies `$CODEX_HOME/hooks.json` exists and that the stop command matches the machine config
- `global_skill` — verifies `$CODEX_HOME/skills/autonomous-loop/SKILL.md` exists

When invoked with `--cwd`, an additional check is included:

- `repo_install` — verifies repo-local config, hooks, and skill are present, and that the repo hooks match the machine config

If Codex was already running, restart it once after bootstrap so it reloads the global hooks and skill.

## Repo Setup

Install repo-local support files into a target project:

```bash
autonomous-loop install-repo --repo /path/to/repo
```

That command currently supports Node-style repos with `package.json`. It writes:

- `.codex/autoloop.project.json`
- `.codex/hooks.json`
- `.agents/skills/autonomous-loop/SKILL.md`

It also uses the verified machine command saved by `bootstrap`. If machine bootstrap is missing, `install-repo` exits non-zero with `error_code: "missing_machine_bootstrap"`.

Verify the repo install:

```bash
autonomous-loop doctor --cwd /path/to/repo
```

Expected result: `ok: true` with a passing `repo_install` check.

**Repo root resolution:** `--cwd` resolves upward from the given directory. It stops at the first ancestor that contains `.codex/autoloop.project.json`, falling back to the first ancestor with a `.git` directory. Placing `.codex/autoloop.project.json` at the right level ensures correct resolution in monorepos where multiple projects share a single `.git` root.

## Repo Detection And Verification Commands

For Node-style repos, `install-repo` currently:

- requires `package.json`
- detects the package manager with this precedence:
  - `--package-manager`
  - `package.json.packageManager`
  - lockfiles
- trusts only these verification script names:
  - `typecheck`
  - `lint`
  - `test`

Existing repo-local files are preserved unless you pass `--force`.

Override examples:

```bash
autonomous-loop install-repo --repo /path/to/repo --package-manager npm
autonomous-loop install-repo --repo /path/to/repo --prefer-scripts lint,test
autonomous-loop install-repo --repo /path/to/repo --force
```

`--prefer-scripts` is a single comma-separated argument.

Current autodetect scope is Node-style repos only. For non-Node repos, install the repo-local support files you need and write `.codex/autoloop.project.json` manually.

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

## Smoke Test

Run the full onboarding path against a real repo:

```bash
autonomous-loop bootstrap
autonomous-loop doctor
autonomous-loop install-repo --repo /path/to/repo
autonomous-loop doctor --cwd /path/to/repo
```

If any step fails, start with the failing `doctor` check and follow the matching section in [`TROUBLESHOOTING.md`](../TROUBLESHOOTING.md).
