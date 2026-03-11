# Examples

## Bootstrap The Machine

```bash
autonomous-loop bootstrap
autonomous-loop doctor
```

## Install Repo-Local Support Files

```bash
autonomous-loop install-repo --repo ~/Code/my-app
autonomous-loop doctor --cwd ~/Code/my-app
```

## Install Into A pnpm Repo With Explicit Override

```bash
autonomous-loop install-repo --repo ~/Code/my-pnpm-app --package-manager pnpm
```

## Prefer A Narrower Verification Stack

```bash
autonomous-loop install-repo --repo ~/Code/my-app --prefer-scripts lint,test
```

`--prefer-scripts` is a single comma-separated argument.

## Machine Bootstrap Missing

If you run `install-repo` before `bootstrap`, the command exits non-zero and returns JSON with:

- `error_code: "missing_machine_bootstrap"`
- `message: "Run \`autonomous-loop bootstrap\` before \`install-repo\`."`

Run:

```bash
autonomous-loop bootstrap
autonomous-loop doctor
```

Then rerun `install-repo`.

## Unsafe Install Fails Closed

If the target repo has `package.json` but none of `typecheck`, `lint`, or `test`, `install-repo` exits non-zero and returns machine-readable JSON explaining the failure and remediation.

## Enable The Loop For A Task

```bash
autonomous-loop request enable \
  --cwd "$PWD" \
  --objective "Implement the approved feature to completion" \
  --task-json '{"id":"T1","title":"Ship the feature","required":true,"evidence":[{"kind":"pathChanged","glob":"src/**"}]}'
```

Fallback responses return JSON like:

```json
{
  "action": "enable",
  "claim_token": "AUTOLOOP_CLAIM:abcd1234",
  "nonce": "abcd1234",
  "repo_root": "/Users/you/Code/my-app",
  "request_id": "request-0001"
}
```

In environments that expose `CODEX_THREAD_ID` or `CODEX_SESSION_ID`, the response instead binds immediately to the live session and looks like:

```json
{
  "action": "enable",
  "activation_mode": "direct-env",
  "repo_root": "/Users/you/Code/my-app",
  "request_id": "...",
  "session_id": "abc123",
  "session_id_source": "CODEX_SESSION_ID",
  "run_id": "abc123",
  "contract_hash": "...",
  "state": "active"
}
```

`session_id_source` is the name of the environment variable that was read (`CODEX_SESSION_ID` or `CODEX_THREAD_ID`). `run_id`, `contract_hash`, and `state` are only present when an active runtime state exists after the request is applied.

If the response includes a `claim_token` field instead, include that exact value in the next assistant message, then let that turn end so the next real `Stop` hook can claim the request.

## Check Status

```bash
autonomous-loop status --cwd "$PWD"
```

## Pause The Loop

```bash
autonomous-loop request pause --cwd "$PWD"
```

If the response uses `direct-env`, the pause applies immediately. Otherwise include the returned `claim_token` value in your next assistant message and let that turn end. Immediate pause only works when the current session already has loop state.

## Resume The Loop

```bash
autonomous-loop request resume --cwd "$PWD"
```

If the response uses `direct-env`, the resume applies immediately. Otherwise include the returned `claim_token` value in your next assistant message and let that turn end. Immediate resume only works when the current session already has loop state.
