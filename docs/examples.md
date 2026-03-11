# Examples

## Install templates into a repo

```bash
autonomous-loop install-repo --repo ~/Code/my-app
```

## Install into a pnpm repo with explicit override

```bash
autonomous-loop install-repo --repo ~/Code/my-pnpm-app --package-manager pnpm
```

## Prefer a narrower verification stack

```bash
autonomous-loop install-repo --repo ~/Code/my-app --prefer-scripts lint,test
```

## Unsafe install fails closed

If the target repo has `package.json` but none of `typecheck`, `lint`, or `test`, `install-repo` exits non-zero and returns machine-readable JSON explaining the missing evidence and remediation.

## Enable the loop for a task

```bash
autonomous-loop request enable \
  --cwd "$PWD" \
  --objective "Implement the approved feature to completion" \
  --task-json '{"id":"T1","title":"Ship the feature","required":true,"evidence":[{"kind":"pathChanged","glob":"src/**"}]}'
```

The command returns a claim token like:

```text
AUTOLOOP_CLAIM:abcd1234
```

In environments that expose `CODEX_THREAD_ID` or `CODEX_SESSION_ID`, the response can instead include `activation_mode: "direct-env"` and the live session binding immediately. If the response includes a claim token, include that token in the next assistant message, then let that turn end so the next `Stop` hook can claim the request.

Important:

- `request enable` binds immediately when it returns `activation_mode: "direct-env"`
- otherwise it writes a pending request
- in the fallback path, same-turn `status` checks can still show `pending`
- in the fallback path, activation happens when the next real `Stop` hook sees that token in `last_assistant_message`

## Check status

```bash
autonomous-loop status --cwd "$PWD"
```

## Pause the loop

```bash
autonomous-loop request pause --cwd "$PWD"
```

If the response uses direct-env activation, the pause applies immediately. Otherwise include the returned claim token in your next assistant message and let that turn end.

## Resume the loop

```bash
autonomous-loop request resume --cwd "$PWD"
```

If the response uses direct-env activation, the resume applies immediately. Otherwise include the returned claim token in your next assistant message and let that turn end.
