# First-Time User Onboarding Implementation Plan

**Goal:** Make `autonomous-loop` easy for a first-time user to install, verify, and use without hand-editing global hooks, debugging PATH issues, or discovering setup layers by trial and error.

**Architecture:** Add a machine-level bootstrap flow and a doctor/self-check flow, then make `install-repo` consume the verified machine configuration instead of copying a static hook template that assumes `autonomous-loop` is already callable everywhere. Keep repo-local policy in `.codex/autoloop.project.json`, but move machine-specific hook/skill installation and validation into explicit runtime commands.

**Tech Stack:** Python 3.11+, `argparse`, `json`, `pathlib`, `shutil`, existing `AutonomousLoopRuntime`, `RuntimeStore`, `RuntimePaths`, and `unittest`.

---

## Product Direction Locked For This Plan

- Add `autonomous-loop bootstrap` for one-time machine setup.
- Add `autonomous-loop doctor` for machine plus repo validation.
- Store machine bootstrap metadata under the runtime root so `install-repo` can render repo-local hooks from the actual verified invocation path.
- Keep `install-repo` focused on repo-local support files, but make it fail loudly when machine bootstrap prerequisites are missing.
- Rewrite onboarding docs around a two-step path:
  1. machine bootstrap
  2. repo install

## Task 1: Add failing bootstrap and doctor tests

**Parallel:** no  
**Blocked by:** none  
**Owned files:** `tests/test_bootstrap.py`, `tests/support.py`

**Files:**
- Create: `tests/test_bootstrap.py`
- Modify: `tests/support.py`
- Test: `tests/test_bootstrap.py`

**Step 1: Add temp-home helpers to the test harness**

Extend `tests/support.py` with helpers that can:

- create an isolated fake `CODEX_HOME`
- expose a fake user bin directory on `PATH`
- write/read `~/.codex/hooks.json`
- write/read `~/.codex/skills/autonomous-loop/SKILL.md`
- run the CLI with env overrides

Add a helper shaped like:

```python
def run_cli(args: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "bin" / "autonomous-loop"), *args],
        text=True,
        capture_output=True,
        env={**os.environ, **(env or {})},
        check=False,
    )
```

**Step 2: Write the first failing doctor test**

Create `tests/test_bootstrap.py` with a red test proving a fresh machine reports missing bootstrap state:

```python
def test_doctor_reports_missing_machine_setup(self) -> None:
    completed = run_cli(["doctor"], env=self.env)
    payload = json.loads(completed.stdout)
    self.assertEqual(completed.returncode, 1)
    self.assertFalse(payload["ok"])
    self.assertIn("global_hooks", payload["checks"])
    self.assertIn("global_skill", payload["checks"])
    self.assertIn("cli_on_path", payload["checks"])
```

**Step 3: Write the bootstrap success test**

Add a red test proving bootstrap installs global assets and records the verified invocation:

```python
def test_bootstrap_installs_global_hooks_and_skill(self) -> None:
    completed = run_cli(["bootstrap"], env=self.env)
    payload = json.loads(completed.stdout)
    self.assertEqual(completed.returncode, 0)
    self.assertTrue(payload["ok"])
    self.assertTrue((self.codex_home / "hooks.json").is_file())
    self.assertTrue((self.codex_home / "skills" / "autonomous-loop" / "SKILL.md").is_file())
    machine = load_json(self.runtime_root / "machine.json")
    self.assertEqual(machine["command_mode"], "absolute-cli")
```

**Step 4: Write the repo-install inheritance test**

Add a red test proving `install-repo` uses the verified machine invocation instead of a bare `autonomous-loop` string when needed:

```python
def test_install_repo_renders_hooks_from_bootstrap_machine_config(self) -> None:
    run_cli(["bootstrap"], env=self.env)
    repo = make_node_repo(...)
    completed = run_cli(["install-repo", "--repo", str(repo)], env=self.env)
    hooks = load_json(repo / ".codex" / "hooks.json")
    command = hooks["hooks"]["Stop"][0]["hooks"][0]["command"]
    self.assertIn(str(self.fake_cli_path), command)
```

**Step 5: Run the test file to confirm failure**

Run:

```bash
python3 -m unittest tests.test_bootstrap -v
```

Expected: FAIL because neither `bootstrap` nor `doctor` exists yet.

## Task 2: Implement machine bootstrap state and global setup

**Parallel:** no  
**Blocked by:** Task 1  
**Owned files:** `src/autonomous_loop/bootstrap.py`, `src/autonomous_loop/paths.py`, `src/autonomous_loop/storage.py`

**Files:**
- Create: `src/autonomous_loop/bootstrap.py`
- Modify: `src/autonomous_loop/paths.py`
- Modify: `src/autonomous_loop/storage.py`
- Test: `tests/test_bootstrap.py`

**Step 1: Add machine-state paths**

Extend `RuntimePaths` with explicit machine bootstrap paths:

```python
def machine_config_path(self) -> Path:
    return self.root / "machine.json"

def codex_home_hooks_path(self) -> Path:
    return self.root.parent / "hooks.json"

def global_skill_path(self) -> Path:
    return self.root.parent / "skills" / "autonomous-loop" / "SKILL.md"
```

The important invariant is: runtime state stays under `$CODEX_HOME/autoloop`, while global hooks and global skills still live under `$CODEX_HOME`.

**Step 2: Implement a dedicated bootstrap module**

Create `src/autonomous_loop/bootstrap.py` with helpers for:

- resolving the current CLI invocation path
- validating whether it is absolute and executable
- generating the global hooks payload
- copying the global skill
- writing `machine.json`

Recommended payload:

```python
{
    "version": "0.1",
    "command_mode": "absolute-cli",
    "command_path": "/Users/example/.local/bin/autonomous-loop",
    "hook_commands": {
        "session_start": "/Users/example/.local/bin/autonomous-loop hook session-start",
        "stop": "/Users/example/.local/bin/autonomous-loop hook stop",
    },
}
```

**Step 3: Build hooks from Python instead of trusting a static machine template**

Add a storage helper:

```python
def write_global_hooks(self, hook_commands: dict[str, str], force: bool = False) -> str | None:
    payload = {
        "hooks": {
            "SessionStart": [...],
            "Stop": [...],
        }
    }
    atomic_write_json(codex_home / "hooks.json", payload)
    return str(codex_home / "hooks.json")
```

> **Note (implementation divergence):** The actual signature in `storage.py` is
> `def write_global_hooks(self, hook_commands: dict[str, str], force: bool = False) -> str | None:`.
> There is no `codex_home` parameter — the path is resolved internally via `self.paths.codex_home_hooks_path()`.
> The method returns `None` when the file already exists and `force=False`, matching the pattern used by
> other idempotent write helpers in `RuntimeStore`.

This removes the current mismatch risk between template docs and live hooks.

**Step 4: Re-run the bootstrap tests**

Run:

```bash
python3 -m unittest tests.test_bootstrap.BootstrapTests.test_bootstrap_installs_global_hooks_and_skill -v
```

Expected: PASS.

## Task 3: Add `bootstrap` and `doctor` CLI commands

**Parallel:** no  
**Blocked by:** Task 2  
**Owned files:** `src/autonomous_loop/cli.py`, `src/autonomous_loop/controller.py`

**Files:**
- Modify: `src/autonomous_loop/cli.py`
- Modify: `src/autonomous_loop/controller.py`
- Test: `tests/test_bootstrap.py`

**Step 1: Extend the CLI surface**

Add top-level commands:

```python
bootstrap = subparsers.add_parser("bootstrap")
bootstrap.add_argument("--force", action="store_true")

doctor = subparsers.add_parser("doctor")
doctor.add_argument("--cwd")
```

**Step 2: Add runtime entrypoints**

In `AutonomousLoopRuntime`, add:

```python
def bootstrap(self, *, force: bool = False) -> dict[str, Any]: ...
def doctor(self, cwd: str | Path | None = None) -> dict[str, Any]: ...
```

`bootstrap()` should:

- resolve the live CLI path
- install or overwrite the global skill
- install or overwrite the global hooks file
- persist `machine.json`
- return machine-readable JSON

`doctor()` should return a structured check bundle like:

```json
{
  "ok": false,
  "checks": {
    "cli_on_path": {"ok": true, "path": "..."},
    "machine_config": {"ok": false, "reason": "missing or invalid machine.json"},
    "global_hooks": {"ok": false, "reason": "missing hooks.json"},
    "global_skill": {"ok": false, "reason": "missing skill"},
    "repo_install": {"ok": false, "reason": "missing .codex/autoloop.project.json"}
  }
}
```

**Step 3: Make return codes meaningful**

- `bootstrap`: exit `0` on success, `1` on failure
- `doctor`: exit `0` only when every required check is green; otherwise `1`

**Step 4: Run the doctor tests**

Run:

```bash
python3 -m unittest tests.test_bootstrap.BootstrapTests.test_doctor_reports_missing_machine_setup -v
python3 -m unittest tests.test_bootstrap.BootstrapTests.test_bootstrap_installs_global_hooks_and_skill -v
```

Expected: PASS.

## Task 4: Make `install-repo` consume machine bootstrap output

**Parallel:** no  
**Blocked by:** Task 3  
**Owned files:** `src/autonomous_loop/controller.py`, `src/autonomous_loop/storage.py`, `src/autonomous_loop/resources/templates/.agents/skills/autonomous-loop/SKILL.md`, `templates/.agents/skills/autonomous-loop/SKILL.md`

**Files:**
- Modify: `src/autonomous_loop/controller.py`
- Modify: `src/autonomous_loop/storage.py`
- Modify: `src/autonomous_loop/resources/templates/.agents/skills/autonomous-loop/SKILL.md`
- Modify: `templates/.agents/skills/autonomous-loop/SKILL.md`
- Test: `tests/test_bootstrap.py`
- Test: `tests/test_install_repo.py`

**Step 1: Refuse silent machine drift**

Before copying repo-local support files, have `install_repo()` load `machine.json`.

If machine bootstrap is missing, return a structured failure like:

```json
{
  "ok": false,
  "error_code": "missing_machine_bootstrap",
  "message": "Run `autonomous-loop bootstrap` before `install-repo`.",
  "remediation": ["Run `autonomous-loop bootstrap`", "Then rerun `autonomous-loop install-repo --repo ...`"]
}
```

**Step 2: Render repo-local hooks from machine config**

Replace the static `.codex/hooks.json` copy path with a generated payload using the verified machine command:

```python
hook_command = machine["hook_commands"]["stop"]
```

That prevents repo installs from silently depending on a command path that the machine has not validated.

**Step 3: Update the repo-local skill template**

The repo-local skill should explicitly tell the agent:

- machine bootstrap must already be complete
- `install-repo` was generated from the machine’s verified command path
- if `doctor --cwd "$PWD"` fails, stop and report the failing checks

**Step 4: Run focused install tests**

Run:

```bash
python3 -m unittest tests.test_install_repo -v
python3 -m unittest tests.test_bootstrap.BootstrapTests.test_install_repo_renders_hooks_from_bootstrap_machine_config -v
```

Expected: PASS.

## Task 5: Rewrite docs around a two-step onboarding path

**Parallel:** yes  
**Blocked by:** Task 4  
**Owned files:** `README.md`, `docs/install.md`, `docs/examples.md`, `TROUBLESHOOTING.md`, `CHANGELOG.md`

**Files:**
- Modify: `README.md`
- Modify: `docs/install.md`
- Modify: `docs/examples.md`
- Modify: `TROUBLESHOOTING.md`
- Modify: `CHANGELOG.md`
- Test: doc accuracy check against CLI help and focused smoke commands

**Step 1: Make the quickstart brutally short**

The top of `README.md` should reduce to:

```markdown
1. `python3 -m pip install .`
2. `autonomous-loop bootstrap`
3. `autonomous-loop install-repo --repo /path/to/repo`
4. Open Codex in that repo and say: "Use /autonomous-loop for this task."
```

**Step 2: Add a single source of truth for first-time setup**

`docs/install.md` should split setup into:

- Machine setup
- Repo setup
- Smoke test

**Step 3: Add doctor-led troubleshooting**

`TROUBLESHOOTING.md` should begin with:

```bash
autonomous-loop doctor
autonomous-loop doctor --cwd /path/to/repo
```

Every remediation branch should point back to a failed doctor check.

**Step 4: Document restart expectations clearly**

If Codex still needs a restart after machine bootstrap, say that explicitly once and keep it consistent in all docs.

**Step 5: Verify docs against the real CLI**

Run:

```bash
autonomous-loop --help
autonomous-loop bootstrap --help
autonomous-loop doctor --help
```

Expected: docs match the shipped CLI names and arguments exactly.

## Task 6: Add a machine-level smoke lane to CI

**Parallel:** yes  
**Blocked by:** Task 4  
**Owned files:** `.github/workflows/test.yml`

**Files:**
- Modify: `.github/workflows/test.yml`
- Test: `.github/workflows/test.yml`

**Step 1: Add a smoke script block**

After the unit tests pass, run a temp-home bootstrap plus install smoke:

```bash
TMP_CODEX_HOME="$(mktemp -d)"
export CODEX_HOME="$TMP_CODEX_HOME"
export PATH="$HOME/.local/bin:$PATH"
python bin/autonomous-loop bootstrap
python bin/autonomous-loop doctor
python bin/autonomous-loop install-repo --repo "$PWD" --force
python bin/autonomous-loop doctor --cwd "$PWD"
```

Use `python bin/autonomous-loop` only if CI cannot rely on an installed console script yet. Otherwise prefer the installed `autonomous-loop` entrypoint after `pip install .`.

**Step 2: Keep the smoke lane narrow**

Do not try to emulate a real Codex desktop session in CI. The goal is only to prove:

- bootstrap writes global assets
- doctor reports green
- install-repo writes repo-local assets from machine config

**Step 3: Verify the workflow locally**

Run the same smoke commands locally with a temp `CODEX_HOME`.

## Acceptance Criteria

Implementation is complete only when all of the following are true:

1. A first-time user can complete machine setup with `python3 -m pip install .` and `autonomous-loop bootstrap`.
2. `autonomous-loop doctor` reports machine-level failures before bootstrap and green after bootstrap.
3. `autonomous-loop install-repo --repo ...` either succeeds with machine-derived repo-local hooks or fails with a clear `missing_machine_bootstrap` error.
4. Repo-local `.codex/hooks.json` no longer depends on an unverified bare command path.
5. The repo-local skill template is valid YAML and accurately reflects direct-env plus doctor-led usage.
6. README quickstart fits the two-step model: machine bootstrap, then repo install.
7. CI includes at least one smoke lane that exercises bootstrap, doctor, and install-repo together.

## Verification Checklist

Run all of these before calling the onboarding flow complete:

```bash
python3 -m unittest tests.test_bootstrap -v
python3 -m unittest tests.test_install_repo -v
python3 -m unittest discover -s tests -v
python3 -m compileall src bin
autonomous-loop --help
autonomous-loop bootstrap --help
autonomous-loop doctor --help
```

## Execution Options

1. Execute sequentially in this session.
2. Execute in a new worktree.
3. Split into parallel tickets after Task 3:
   - Ticket A: Task 4 install-repo + template rendering
   - Ticket B: Task 5 docs rewrite
   - Ticket C: Task 6 CI smoke lane
