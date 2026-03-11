# Autonomous Loop Troubleshooting

## No Hook Activity At All

Check:

1. your Codex config-layer `hooks.json` exists
2. the commands in that file point at a working `autonomous-loop` install
3. `autonomous-loop` is on `PATH` or the hook command uses a valid absolute path
4. the hook file is in a config layer Codex actually loads

## Enable Request Never Activates

The stop hook only binds a pending request if the next assistant message includes the claim token.

Expected pattern:

1. the skill runs `autonomous-loop request enable ...`
2. the CLI returns `AUTOLOOP_CLAIM:<nonce>`
3. the assistant includes that exact token in its next message

If the token is missing or changed, the request stays pending.

## Status Shows Pending Requests But No Session State

That means the request exists, but no `Stop` hook has claimed it yet.

Check:

1. there was another assistant turn after the request
2. that turn contained the exact claim token
3. the repo path in the request matches the current working repo

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

Pause and resume are also pending requests. They must be claimed through the same nonce token flow as enable.

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
