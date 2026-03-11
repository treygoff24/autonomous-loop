# Examples

## Install templates into a repo

```bash
autonomous-loop install-repo --repo ~/Code/my-app
```

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

Include that token in the next assistant message so the next `Stop` hook can claim the request.

## Check status

```bash
autonomous-loop status --cwd "$PWD"
```

## Pause the loop

```bash
autonomous-loop request pause --cwd "$PWD"
```

## Resume the loop

```bash
autonomous-loop request resume --cwd "$PWD"
```
