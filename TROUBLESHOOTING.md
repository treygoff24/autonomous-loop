# Autonomous Loop Troubleshooting

Start here:

```bash
autonomous-loop doctor
autonomous-loop doctor --cwd /path/to/repo
```

Every remediation path below maps back to a specific failed doctor check. Re-run the same `doctor` command after each fix.

## `cli_on_path` Failed

`doctor` could not find an executable `autonomous-loop` command on `PATH`.

Check:

1. the package install completed successfully
2. the environment where you run Codex can resolve `autonomous-loop`
3. the command on `PATH` is executable

If you are validating from source in this repo, the equivalent help check is:

```bash
python3 bin/autoloop_cli.py --help
```

## `machine_config` Failed

The machine bootstrap record at `$CODEX_HOME/autoloop/machine.json` is missing, malformed, points at a missing file, or points at a non-executable file.

Fix:

```bash
autonomous-loop bootstrap
autonomous-loop doctor
```

If the command path on the machine changed, rerun `autonomous-loop bootstrap --force`.

## `global_hooks` Failed

The machine-level `hooks.json` is missing or does not match the command path recorded in `machine.json`.

Fix:

```bash
autonomous-loop bootstrap --force
autonomous-loop doctor
```

If Codex was already running, restart it once after bootstrap.

## `global_skill` Failed

The machine-level skill file is missing from `$CODEX_HOME/skills/autonomous-loop/SKILL.md`.

Fix:

```bash
autonomous-loop bootstrap --force
autonomous-loop doctor
```

If Codex still does not notice the skill after bootstrap succeeds, restart Codex once.

## `repo_install` Failed

Run the repo-scoped check so the failure includes the resolved repo root:

```bash
autonomous-loop doctor --cwd /path/to/repo
```

Then match the failure reason:

- missing `.codex/autoloop.project.json`: rerun `autonomous-loop install-repo --repo /path/to/repo`
- missing `.codex/hooks.json`: rerun `autonomous-loop install-repo --repo /path/to/repo --force`
- missing repo-local skill (expected at `.agents/skills/autonomous-loop/SKILL.md`): rerun `autonomous-loop install-repo --repo /path/to/repo --force`
- repo hooks stop command does not match machine config: rerun `autonomous-loop bootstrap --force`, then `autonomous-loop install-repo --repo /path/to/repo --force`

Re-run:

```bash
autonomous-loop doctor --cwd /path/to/repo
```

## `install-repo` Fails Before Writing Files

`install-repo` returns machine-readable JSON. Common failures:

- `missing_machine_bootstrap`: run `autonomous-loop bootstrap`, then rerun `install-repo`
- `missing_package_json`: target repo is not a supported Node-style repo root
- `ambiguous_package_manager`: remove conflicting lockfiles or pass `--package-manager <npm|pnpm|yarn|bun>`
- `missing_package_manager`: add `packageManager` to `package.json` or pass `--package-manager`
- `missing_verification_scripts`: define at least one of `typecheck`, `lint`, or `test`
- `invalid_preferred_script` or `missing_preferred_script`: fix the `--prefer-scripts` list
- `invalid_package_manager_override`: `--package-manager` was passed with an unsupported value; use one of `npm|pnpm|yarn|bun`
- `unsupported_package_manager`: `package.json` has a `packageManager` field with an unrecognized value; fix the field or pass `--package-manager` to override

After the install succeeds, validate with:

```bash
autonomous-loop doctor --cwd /path/to/repo
```

## Enable Request Never Activates

There are two activation paths:

1. direct-env activation when the Codex environment exposes `CODEX_SESSION_ID` or `CODEX_THREAD_ID`
2. fallback claim-token activation through the next real `Stop` event

If the response from `request enable` includes `activation_mode: "direct-env"`, the loop is already bound to the current session and this section does not apply.

In the fallback path, the stop hook only binds a pending request when the next real turn-ending `Stop` event sees the claim token in `last_assistant_message`.

Expected pattern:

1. the skill runs `autonomous-loop request enable ...`
2. the CLI returns `AUTOLOOP_CLAIM:<nonce>`
3. the assistant includes that exact token in its next message
4. that token-bearing turn actually ends, so Codex emits a `Stop` hook

If the token is missing, changed, or the turn has not ended yet, the request stays pending.

## Status Shows Pending Requests But No Session State

That means the request exists, but no fallback `Stop` hook claim has happened yet.

Check:

1. there was another assistant turn after the request
2. that turn contained the exact claim token
3. that turn actually ended and triggered a `Stop` hook
4. the repo path in the request matches the current working repo

Same-turn `status` checks are expected to show `pending` until that stop event happens.

## Hook Fails Closed With Contract Hash Mismatch

This means at least one of these changed unexpectedly after activation:

- `contract.json`
- `verification.json`
- `state.json` contract hash field

Inspect the session directory under `$CODEX_HOME/autoloop/repos/<repo_hash>/sessions/<safe_session_id>/`, where `<safe_session_id>` is the session ID lowercased with special characters replaced by `-` (the `safe_name()` transform). If the contract really changed, disable or release the run and re-enable it.

## Final Gates Keep Blocking Release

Inspect:

- `ledger.json`
- `verification.json`
- `contract.json`
- `events.log`
- `debug.log`

`ledger.json` records the last gate results, so you can see exactly which trusted command ref is still failing.

## Repeated Failure Signature Hard-Stops The Run

The default repeated-signature threshold is controlled by `.codex/autoloop.project.json`:

- `defaults.maxRepeatedFailureSignature`

If the same blocker repeats too many times, the runtime marks the run failed and returns a hard stop.

## Pause Or Resume Does Nothing

Pause, resume, disable, and release follow the same two-path model as enable. In `direct-env` mode they apply immediately only when the current session already has loop state. Otherwise they are pending requests that must be claimed through the same nonce token flow as enable.

Check pending requests with:

```bash
autonomous-loop status --cwd /path/to/repo
```

## Wrong Repo Root

Repo resolution prefers:

1. nearest parent containing `.codex/autoloop.project.json`
2. nearest parent containing `.git`
3. current working directory

If `doctor --cwd /path/to/repo` reports the wrong `repo_root`, point it at the actual repo root or put `.codex/autoloop.project.json` at the correct root.
