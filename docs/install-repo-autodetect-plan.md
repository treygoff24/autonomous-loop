# Install-Repo Autodetect Implementation Plan

**Goal:** Make `autonomous-loop install-repo` generate a trustworthy repo-local `.codex/autoloop.project.json` from target-repo evidence instead of copying static `pnpm` assumptions.

**Architecture:** Add a stdlib-only install pipeline in a new `src/autonomous_loop/install_repo.py` module. That module should detect package manager and runnable scripts, build a validated config payload, and return a structured success-or-failure result. Keep `src/autonomous_loop/controller.py` as a thin orchestration layer, keep `src/autonomous_loop/storage.py` responsible for filesystem writes, and leave hook/skill copying static in v1.

**Tech Stack:** Python 3.11, `argparse`, `json`, `pathlib`, `tempfile`, `unittest`, existing `AutonomousLoopRuntime` and `RuntimeStore`.

---

## Scope Lock

### In Scope For This Change

- Node-style repos only in v1: `package.json` is required.
- CLI overrides ship in v1:
  - `--package-manager <npm|pnpm|yarn|bun>`
  - `--prefer-scripts lint,test,typecheck`
- Generated config emits only verified command refs.
- `install-repo` returns machine-readable JSON and exits non-zero on unsafe installs.
- Hooks and repo-local skill files remain static copy artifacts.

### Not In This Change

- Non-Node repo autodetection.
- Repo-local hint files such as `.codex/autoloop.install.json`.
- Auto-including `build` in gate profiles.
- Running detected gates during install.
- Reworking hook merge semantics.

## Current Repo Evidence

| Concern | Current evidence | Why it matters |
| --- | --- | --- |
| CLI surface | `src/autonomous_loop/cli.py` exposes `install-repo` with only `--repo` and `--force`. | Overrides and exit-code semantics must start here. |
| Runtime wiring | `src/autonomous_loop/controller.py` resolves the repo root and returns `{"repo_root","copied"}` from `install_repo()`. | There is no detection, validation, or failure contract today. |
| Write path | `src/autonomous_loop/storage.py` copies `.codex/autoloop.project.json`, `.codex/hooks.json`, and `.agents/skills/autonomous-loop/SKILL.md`. | Dynamic config generation must replace only the config artifact, not all writes. |
| Static assumptions | `src/autonomous_loop/resources/templates/.codex/autoloop.project.json` hardcodes `pnpm typecheck/test/lint`. | npm/yarn/bun repos can install a broken config successfully. |
| User-facing drift | `README.md` and `docs/install.md` currently tell users to hand-edit trusted commands after install. | This change should remove that default manual step. |
| Existing tests | `tests/test_autonomous_loop_contract.py` covers enable/stop/pause/resume only. | Install-path behavior currently has no direct tests. |

## Current Loop Proof In This Repo

Use the existing local runtime while implementing so the loop itself stays part of the verification path.

Observed on `feature/install-repo-autodetect-plan`:

- `python3 bin/autoloop_cli.py install-repo --repo /Users/treygoff/Code/autonomous-loop`
  Expected current output: JSON showing copied `.codex/autoloop.project.json`, `.codex/hooks.json`, and `.agents/skills/autonomous-loop/SKILL.md`.
- `python3 bin/autoloop_cli.py status --cwd /Users/treygoff/Code/autonomous-loop`
  Expected current output: empty `pending_requests` and `sessions`.

During implementation, keep using the repo-local loop boundary:

1. Reinstall repo-local artifacts with the local CLI after changing install behavior.
2. Queue `request enable` from this repo.
3. Inspect the response:
   - if it includes `activation_mode: "direct-env"`, the loop is already bound to the current Codex thread
   - otherwise include the exact `AUTOLOOP_CLAIM:<nonce>` token in the final assistant message of that turn
4. Verify `status` and inspect `$CODEX_HOME/autoloop/.../verification.json` if activation looks wrong.

## Implementation Tasks

### Task 1: Add the red install-path test harness and happy-path fixtures

**Parallel:** no
**Blocked by:** none
**Owned files:** `tests/test_install_repo.py`, `tests/support.py`

**Files:**
- Create: `tests/test_install_repo.py`
- Modify: `tests/support.py`
- Test: `tests/test_install_repo.py`

**Step 1: Write the failing tests**

Add temp-repo fixture helpers that create synthetic npm and pnpm repos with real `package.json` and lockfile signals. Start with two red tests:

```python
def test_install_repo_generates_npm_commands(self) -> None:
    repo = make_node_repo(package_manager="npm", scripts={"lint": "eslint .", "test": "vitest run"})
    result = self.runtime.install_repo(repo)
    config = load_json(Path(repo) / ".codex" / "autoloop.project.json")
    self.assertEqual(config["commands"]["lint"], ["npm", "run", "lint"])
    self.assertEqual(config["commands"]["test"], ["npm", "test"])

def test_install_repo_generates_pnpm_profiles_in_stable_order(self) -> None:
    repo = make_node_repo(
        package_manager="pnpm@10.0.0",
        scripts={"typecheck": "tsc --noEmit", "lint": "eslint .", "test": "vitest run"},
        lockfiles=("pnpm-lock.yaml",),
    )
    result = self.runtime.install_repo(repo)
    config = load_json(Path(repo) / ".codex" / "autoloop.project.json")
    self.assertEqual(config["gateProfiles"]["fast"], ["typecheck"])
    self.assertEqual(config["gateProfiles"]["default"], ["typecheck", "lint", "test"])
```

**Step 2: Run tests to verify they fail**

Run:

```bash
python3 -m unittest tests.test_install_repo.InstallRepoTests.test_install_repo_generates_npm_commands \
  tests.test_install_repo.InstallRepoTests.test_install_repo_generates_pnpm_profiles_in_stable_order -v
```

Expected: FAIL because current install still copies static `pnpm` commands regardless of repo evidence.

**Step 3: Add the minimal test support**

Extend `tests/support.py` only with reusable install-fixture helpers, not install logic.

**Step 4: Re-run the same tests**

Expected: still FAIL, but now with stable red coverage and reproducible fixture setup.

### Task 2: Build the pure detection and config-generation layer

**Parallel:** no
**Blocked by:** Task 1
**Owned files:** `src/autonomous_loop/install_repo.py`, `tests/test_install_repo.py`

**Files:**
- Create: `src/autonomous_loop/install_repo.py`
- Modify: `tests/test_install_repo.py`
- Test: `tests/test_install_repo.py`

**Step 1: Add failing unit tests for precedence, ambiguity, and script filtering**

Add red tests for:

- CLI package-manager override winning over repo metadata.
- `package.json.packageManager` winning over lockfiles.
- ambiguous lockfile-only repos failing closed.
- repos with only `lint` generating one-command `fast/default/final` profiles.
- repos missing `lint`, `test`, and `typecheck` failing closed.

**Step 2: Run the targeted test module**

Run:

```bash
python3 -m unittest tests.test_install_repo -v
```

Expected: FAIL on missing detector/generator functions.

**Step 3: Implement the pure install module**

Recommended shape:

```python
@dataclass(frozen=True)
class InstallRepoSuccess:
    repo_root: str
    package_manager_detected: str
    scripts_detected: list[str]
    commands_generated: dict[str, list[str]]
    gate_profiles_generated: dict[str, list[str]]
    copied: list[str]
    warnings: list[str]

def detect_package_manager(package_json: dict[str, Any], lockfiles: set[str], override: str | None) -> str: ...
def detect_scripts(package_json: dict[str, Any], preferred: list[str] | None) -> list[str]: ...
def build_project_config(package_manager: str, scripts: list[str]) -> dict[str, Any]: ...
def validate_generated_config(config: dict[str, Any]) -> None: ...
```

Rules:

- Package-manager precedence is `CLI override -> package.json.packageManager -> lockfiles -> fail`.
- Supported script refs are exactly `typecheck`, `lint`, `test`.
- Use stable command/profile ordering: `typecheck`, `lint`, `test`.
- `fast` uses the first available trustworthy command in that order.
- `default` and `final` include all detected commands in stable order.

**Step 4: Re-run the targeted test module**

Expected: PASS for happy paths and pure-function failures.

### Task 3: Wire runtime writes, exit semantics, and overwrite rules

**Parallel:** no
**Blocked by:** Task 2
**Owned files:** `src/autonomous_loop/cli.py`, `src/autonomous_loop/controller.py`, `src/autonomous_loop/storage.py`, `src/autonomous_loop/install_repo.py`, `tests/test_install_repo.py`

**Files:**
- Modify: `src/autonomous_loop/cli.py`
- Modify: `src/autonomous_loop/controller.py`
- Modify: `src/autonomous_loop/storage.py`
- Modify: `src/autonomous_loop/install_repo.py`
- Modify: `tests/test_install_repo.py`
- Test: `tests/test_install_repo.py`

**Step 1: Add failing integration tests around install output and overwrite behavior**

Add red tests for:

- success payload includes `repo_root`, `package_manager_detected`, `scripts_detected`, `commands_generated`, `gate_profiles_generated`, `copied`, and `warnings`
- missing `package.json` returns a structured failure and CLI exit code `1`
- override pointing at a missing script returns a structured failure and CLI exit code `1`
- existing `.codex/autoloop.project.json` is preserved without `--force`
- hooks and repo-local skill files still copy as before

**Step 2: Run only the new integration cases**

Run:

```bash
python3 -m unittest tests.test_install_repo.InstallRepoTests -v
```

Expected: FAIL because `install-repo` still returns success on unsafe inputs and still treats `--force` as blanket template overwrite.

**Step 3: Implement runtime and storage wiring**

Implementation requirements:

- `src/autonomous_loop/controller.py`
  - call the new install module
  - convert install failures into a single JSON error schema
- `src/autonomous_loop/cli.py`
  - add `--package-manager` and `--prefer-scripts`
  - return `0` on success and `1` on structured install failure
- `src/autonomous_loop/storage.py`
  - stop copying the static `.codex/autoloop.project.json` template
  - add a helper that atomically writes generated config
  - keep `.codex/hooks.json` and `.agents/skills/autonomous-loop/SKILL.md` as copy-only artifacts
  - define per-artifact overwrite rules:
    - `.codex/autoloop.project.json`: overwrite only when `--force` is set
    - `.codex/hooks.json`: existing file is preserved unless `--force`
    - `.agents/skills/autonomous-loop/SKILL.md`: existing file is preserved unless `--force`

Recommended failure payload:

```json
{
  "ok": false,
  "error_code": "missing_verification_scripts",
  "repo_root": "/abs/path/to/repo",
  "evidence": {
    "package_manager_detected": "npm",
    "lockfiles_found": ["package-lock.json"],
    "scripts_found": []
  },
  "message": "install-repo requires at least one of: typecheck, lint, test",
  "remediation": [
    "Add a lint, test, or typecheck script to package.json",
    "Or rerun with --prefer-scripts using scripts that already exist"
  ]
}
```

**Step 4: Re-run the install test module**

Expected: PASS for success, failure, and overwrite cases.

### Task 4: Remove doc drift and publish the new operator workflow

**Parallel:** no
**Blocked by:** Task 3
**Owned files:** `README.md`, `docs/install.md`, `docs/examples.md`, `TROUBLESHOOTING.md`, `docs/agent-implementation-brief.md`, `src/autonomous_loop/resources/templates/.agents/skills/autonomous-loop/SKILL.md`

**Files:**
- Modify: `README.md`
- Modify: `docs/install.md`
- Modify: `docs/examples.md`
- Modify: `TROUBLESHOOTING.md`
- Modify: `docs/agent-implementation-brief.md`
- Modify: `src/autonomous_loop/resources/templates/.agents/skills/autonomous-loop/SKILL.md`
- Test: documentation examples and repo-local smoke checks

**Step 1: Update docs to remove the manual command-edit default**

Document:

- Node-only v1 scope
- package-manager detection precedence
- supported script names
- CLI override usage
- fail-closed install behavior
- one npm success example
- one pnpm success example
- one unsafe install example with non-zero exit

**Step 2: Fix source-of-truth language**

Docs must point at the packaged template paths this repo actually ships, not stale top-level mirrors, unless a deliberate mirrored asset policy is introduced in the same change.

**Step 3: Run the full repo test suite**

Run:

```bash
python3 -m unittest discover -s tests -v
```

Expected: PASS.

**Step 4: Run repo-local install and loop smoke checks**

Run:

```bash
python3 bin/autoloop_cli.py install-repo --repo /Users/treygoff/Code/autonomous-loop --force
python3 bin/autoloop_cli.py status --cwd /Users/treygoff/Code/autonomous-loop
```

Expected:

- install output shows generated config metadata instead of only copied template paths
- `status` still returns valid JSON for this repo

Then queue a real enable request:

```bash
python3 bin/autoloop_cli.py request enable \
  --cwd /Users/treygoff/Code/autonomous-loop \
  --objective "Implement install-repo autodetect to completion" \
  --task-json '{"id":"T1","title":"Ship install autodetect","required":true,"evidence":[{"kind":"pathChanged","glob":"src/**"},{"kind":"pathChanged","glob":"tests/**"},{"kind":"pathChanged","glob":"docs/**"}]}'
```

Expected: either a direct-env response with an already-bound session, or a fallback response with `claim_token`. In the fallback path, the implementer must place that exact token in the final assistant message of that turn, then confirm activation on the next turn with `status`.

## Verification Checklist

Implementation is complete only when all of the following are true:

1. `python3 -m unittest tests.test_install_repo -v` passes.
2. `python3 -m unittest discover -s tests -v` passes.
3. Synthetic npm and pnpm repos produce correct command arrays and gate profiles.
4. Repos with no `package.json`, no usable scripts, or ambiguous package-manager signals exit `1` with structured JSON failures.
5. `install-repo` never emits a nonexistent command ref.
6. `--force` behavior is explicit and tested per artifact.
7. Docs no longer tell the default user path to hand-edit commands after install.
8. Repo-local loop smoke checks still succeed in `autonomous-loop` itself.

## Suggested Execution Order

1. Execute Task 1.
2. Execute Task 2.
3. Execute Task 3.
4. Execute Task 4.

Do not parallelize these tasks. The owned files overlap intentionally, and each later slice depends on the earlier red-green coverage being in place first.
