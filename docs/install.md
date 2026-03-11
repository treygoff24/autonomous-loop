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

That command writes:

- `$CODEX_HOME/hooks.json`
- `$CODEX_HOME/skills/autonomous-loop/SKILL.md`
- `$CODEX_HOME/autoloop/machine.json`

Verify machine setup:

```bash
autonomous-loop doctor
```

Expected result: `ok: true`.

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

## Smoke Test

Run the full onboarding path against a real repo:

```bash
autonomous-loop bootstrap
autonomous-loop doctor
autonomous-loop install-repo --repo /path/to/repo
autonomous-loop doctor --cwd /path/to/repo
```

If any step fails, start with the failing `doctor` check and follow the matching section in [`TROUBLESHOOTING.md`](../TROUBLESHOOTING.md).
