# Autonomous Loop Troubleshooting

## No Hook Activity At All

Check:

1. your Codex config-layer `hooks.json` exists
2. the commands in that file point at a working `autonomous-loop` install
3. `autonomous-loop` is on `PATH` or the hook command uses a valid absolute path
4. the hook file is in a config layer Codex actually loads

## Install-Repo Fails With Missing package.json

`install-repo` v1 autodetect currently supports Node-style repos only.

Check:

1. you pointed `--repo` at the actual repo root
2. that root contains `package.json`
3. for non-Node repos, you are prepared to write `.codex/autoloop.project.json` manually after installing hooks and the repo-local skill

## Install-Repo Fails With Conflicting Lockfiles

Autodetect uses this precedence:

1. `--package-manager`
2. `package.json.packageManager`
3. lockfiles

If lockfiles disagree and there is no stronger signal, `install-repo` fails closed.

Fix:

1. remove stale lockfiles
2. add `packageManager` to `package.json`
3. or rerun with `--package-manager <npm|pnpm|yarn|bun>`

## Install-Repo Fails With Missing Verification Scripts

Autodetect only trusts these script names:

- `typecheck`
- `lint`
- `test`

Fix:

1. add at least one of those scripts to `package.json`
2. or rerun with `--prefer-scripts` using only scripts that are already present

## Enable Request Never Activates

There are two activation paths:

1. direct-env activation when the Codex environment exposes `CODEX_THREAD_ID` or `CODEX_SESSION_ID`
2. fallback claim-token activation through the next real `Stop` event

If the response from `request enable` already includes `activation_mode: "direct-env"`, the loop should already be bound to the current session and this section does not apply.

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

Same-turn `status` checks are expected to show `pending` until that stop event happens. If your environment exposes `CODEX_THREAD_ID` or `CODEX_SESSION_ID` and you still see `pending`, direct-env binding is not happening and the runtime should be investigated.

## Hook Fails Closed With Contract Hash Mismatch

This means at least one of these changed unexpectedly after activation:

- `contract.json`
- `verification.json`
- `state.json` contract hash field

Fix:

1. inspect the session directory under `$CODEX_HOME/autoloop/repos/<repo_hash>/sessions/<session_id>/`
2. compare `contract.json` and `verification.json`
3. if the contract really changed, disable or release the run and re-enable it

## Final Gates Keep Blocking Release

Inspect:

- `ledger.json`
- `events.log`
- `debug.log`

`ledger.json` records the last gate results, so you can see exactly which trusted command ref is still failing.

## Repeated Failure Signature Hard-Stops The Run

The default repeated-signature threshold is controlled by `.codex/autoloop.project.json`:

- `defaults.maxRepeatedFailureSignature`

If the same blocker repeats too many times, the runtime marks the run failed and returns a hard stop.

## Pause Or Resume Does Nothing

Pause, resume, disable, and release follow the same two-path model as enable. In direct-env mode they apply immediately. In fallback mode they are pending requests that must be claimed through the same nonce token flow as enable.

Check pending requests with:

```bash
autonomous-loop status --cwd /path/to/repo
```

## Wrong Repo Root

Repo resolution prefers:

1. nearest parent containing `.codex/autoloop.project.json`
2. nearest parent containing `.git`
3. current working directory

If Codex is running in a deep subdirectory and the wrong root is being chosen, put `.codex/autoloop.project.json` at the actual repo root.

## Skill Exists But Codex Does Not Pick It Up

Codex usually detects newly installed skills automatically, but a restart may still be needed after adding a brand new global skill directory under `$CODEX_HOME/skills/`.

## No Runtime Files Under CODEX_HOME

Default runtime root:

```text
$CODEX_HOME/autoloop
```

If that path is empty, check whether `AUTONOMOUS_LOOP_HOME` or `CODEX_HOME` was overridden in the shell that launched Codex.
