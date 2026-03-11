# Autonomous Loop Implementation Brief for Agents

This file is meant to be handed directly to an autonomous coding agent. Its job is to give the agent enough context to understand the system deeply and implement it from scratch in one pass, without human cleanup.

## One sentence summary

Build a repo and session scoped Codex controller that prevents premature agent exit by freezing a deterministic contract, recomputing evidence from real repo state, and blocking `Stop` until trusted gate profiles pass.

## Core goal

The system exists to stop Codex from handing control back to the user before the implementation plan is actually complete. It must fail closed. It must not trust the model's own claim that work is done. It must support multiple repos and multiple Codex sessions on the same machine at the same time.

## Product shape

This is not a single script. It is a small system with four parts:

1. A shared Python runtime and CLI
2. Hook handlers for `SessionStart` and `Stop`
3. Repo-local templates and skills
4. Tests, docs, and packaging

## Environment assumptions

- Codex CLI version target: `0.114.0+`
- Hooks are discovered from `hooks.json`
- Hook event names: `SessionStart` and `Stop`
- Current supported hook type: `command`
- `prompt`, `agent`, and `async` hooks are not relied on
- Python target: `3.11+`

## Problem the system solves

Without a controller, an agent can say “done” early, skip important tests, or try to manipulate its own exit path. This system makes that much harder by moving the definition of done into a frozen contract plus trusted gates.

The model does not get to:

- author the shell commands that judge completion
- edit its own ledger to declare success
- bypass the stop controller by writing plausible text
- use stdout from hooks for anything except structured control output

## High level architecture

### Shared runtime

The shared runtime is a Python package that exposes:

- a CLI command named `autonomous-loop`
- hook entrypoints for `autonomous-loop hook session-start`
- hook entrypoints for `autonomous-loop hook stop`
- request commands for `enable`, `pause`, `resume`, `disable`, and `release`
- `install-repo`
- `status`

### Repo-local static files

Each target repo gets:

```text
.codex/autoloop.project.json
.codex/hooks.json
.agents/skills/autonomous-loop/SKILL.md
```

Those files are version-controlled and human-reviewable. `install-repo` generates `.codex/autoloop.project.json` for Node-style repos by inspecting `package.json`, `package.json.packageManager`, lockfiles, and the supported verification scripts `typecheck`, `lint`, and `test`.

### Mutable runtime state

Mutable runtime state never lives in the target repo. It lives under:

```text
$CODEX_HOME/autoloop/
  repos/
    <repo_hash>/
      project-cache.json
      pending-requests/
        <request_id>.json
      sessions/
        <session_id>/
          state.json
          contract.json
          verification.json
          ledger.json
          events.log
          debug.log
          lock
```

Default `CODEX_HOME` should behave like `~/.codex` unless overridden.

## Scoping rules

The system is scoped by `repo_hash + session_id`.

That means:

- enabling the loop in one repo must not affect another repo
- enabling the loop in one Codex session must not affect a second session in the same repo
- every run gets its own state, contract, verification bundle, ledger, and lock

## Activation model

The loop is off by default.

The user can enable it mid-session. There are two activation paths:

1. Direct-env activation when the Codex environment exposes a stable identifier such as `CODEX_THREAD_ID` or `CODEX_SESSION_ID`
2. Fallback nonce-claim activation when those identifiers are unavailable

Fallback handshake:

1. A repo skill runs `autonomous-loop request enable --cwd ... --objective ... --task-json ...`
2. The CLI writes a pending request and returns a token like `AUTOLOOP_CLAIM:<nonce>`
3. The assistant includes that exact token in its next reply
4. That reply must actually finish so Codex emits a `Stop` hook
5. The next `Stop` hook sees the token in `last_assistant_message`
6. The `Stop` hook claims the pending request and binds it to the real `session_id`

The same two-path model is used for `pause`, `resume`, `disable`, and `release`.

## State machine

Required states:

- `disabled`
- `armed`
- `active`
- `paused`
- `released`
- `failed`

Practical interpretation:

- `disabled`: no enforcement
- `armed`: intent exists, but no claimed session state yet because direct-env binding was unavailable and no `Stop` hook has claimed it
- `active`: stop hook enforces contract
- `paused`: state and ledger preserved, enforcement suspended
- `released`: success path, stop hook no longer blocks
- `failed`: fail-closed state due to corruption or non-convergence

## Deterministic contract model

The system owns the contract. The model may help synthesize it, but it does not get to mutate it after activation.

### Required contract fields

```json
{
  "version": "0.1",
  "contractId": "feature-xyz",
  "objective": "Implement the agreed plan to completion",
  "mode": "implement-until-done",
  "gateProfile": "default",
  "tasks": [
    {
      "id": "T1",
      "title": "Add backend endpoint",
      "dependsOn": [],
      "required": true,
      "evidence": [
        { "kind": "pathExists", "path": "src/api/foo.ts" },
        { "kind": "pathChanged", "glob": "src/api/**" },
        { "kind": "commandRef", "name": "test_api_foo" }
      ]
    }
  ],
  "limits": {
    "maxStopIterations": 12,
    "maxRepeatedFailureSignature": 3
  },
  "policy": {
    "contractEditableByAgent": false,
    "semanticReview": "advisory-after-green"
  }
}
```

### Contract rules

- freeze the contract after activation
- compute and store a contract hash
- store a verification bundle with the resolved commands and baselines
- do not store mutable `completed` flags in the contract
- derive completion from evidence and gates only

## Verification bundle

The runtime must write a verification artifact that contains:

- contract hash
- resolved command registry
- resolved gate profiles
- path-change baselines for `pathChanged` evidence

This is what lets the runtime fail closed if the contract or verification context drifts.

## Evidence evaluation

Minimum supported evidence kinds:

- `pathExists`
- `pathChanged`
- `commandRef`

### `pathExists`

Passes only if the relative path exists under the resolved repo root.

### `pathChanged`

Uses a baseline snapshot captured at activation time. Compare the current matching files and hashes against the saved baseline.

### `commandRef`

Looks up a named trusted command in `.codex/autoloop.project.json` and runs it with `shell=False`.

## Trusted gate registry

Repo-local config owns the gate registry. The model never writes the command strings that decide success.

Example:

```json
{
  "commands": {
    "typecheck": ["pnpm", "typecheck"],
    "lint": ["pnpm", "lint"],
    "test": ["pnpm", "test"]
  },
  "gateProfiles": {
    "fast": ["typecheck"],
    "default": ["typecheck", "lint", "test"],
    "final": ["typecheck", "lint", "test"]
  },
  "defaults": {
    "gateProfile": "default",
    "fastGateProfile": "fast",
    "finalGateProfile": "final",
    "maxStopIterations": 12,
    "maxRepeatedFailureSignature": 3
  }
}
```

## Stop hook behavior

The `Stop` hook is the controller. It must:

1. Read JSON from stdin
2. Resolve repo root from `cwd`
3. In the fallback path, parse `last_assistant_message` for a claim token
4. In the fallback path, apply any pending request for that repo and claim token
5. Load session state for the real `session_id`
6. No-op if the loop is not active for that repo plus session
7. Validate contract and verification integrity
8. Recompute evidence
9. If required tasks remain incomplete:
   - run the fast gate profile
   - update ledger and failure counters
   - return `{"decision":"block","reason":"..."}`
10. If tasks are complete:
   - run the final gate profile
   - if gates fail, block with a narrow reason
11. If deterministic checks pass:
   - mark the run `released`
   - emit no stdout
12. If iteration or repeated-failure thresholds are exceeded:
   - mark the run `failed`
   - return `{"continue":false,"stopReason":"..."}`

Note: the `Stop` hook is still required for ongoing enforcement even when direct-env activation is available. Direct-env removes the need to use `Stop` as the initial claim mechanism.

## SessionStart hook behavior

The `SessionStart` hook is continuity only. It must:

- no-op when no active or paused state exists for the repo plus session
- return concise context about:
  - current state
  - objective
  - outstanding tasks
  - last failing gates
  - current policy

Structured JSON output is preferred.

## Hook output rules

Do not print normal logs to stdout from hooks.

Allowed stdout:

- valid stop hook control JSON
- valid session-start context JSON

All other diagnostics go to `debug.log`.

## Repo skill behavior

The repo-local skill should:

- inspect `.codex/autoloop.project.json`
- synthesize a deterministic contract
- run `autonomous-loop request enable ...`
- inspect the response for `activation_mode: "direct-env"`
- in the fallback path, read the returned claim token
- in the fallback path, include it in the next assistant message
- avoid claiming activation until either direct-env is confirmed or a later stop event has applied the request

It must not pretend runtime state lives in the skill file.

## CLI requirements

Required commands:

- `autonomous-loop request enable`
- `autonomous-loop request pause`
- `autonomous-loop request resume`
- `autonomous-loop request disable`
- `autonomous-loop request release`
- `autonomous-loop hook stop`
- `autonomous-loop hook session-start`
- `autonomous-loop install-repo`
- `autonomous-loop status`

## Packaging requirements

The repo must be publishable and usable by others:

- `pyproject.toml`
- source package under `src/autonomous_loop`
- tests under `tests`
- CLI wrappers under `bin`
- package data for installable templates
- top-level docs
- templates for repo install
- global skill and repo skill
- `.github/workflows/test.yml`
- `.gitignore`
- `LICENSE`

If installable templates are needed after `pip install .`, include them as package data. Do not rely only on a source checkout path.

## Anti-tamper rules

Hard requirements:

- never trust the model's own claim of completion
- never let the model author trusted gate commands
- never execute shell derived from assistant output
- never use hook stdout for unstructured logging
- fail closed on unreadable or mismatched state
- keep mutable runtime state out of the repo

## Tests you must have

At minimum:

1. disabled mode no-op
2. enable creates separate state and contract artifacts
3. stop blocks on incomplete tasks
4. stop blocks on final gate failure
5. stop releases when tasks and gates are green
6. contract hash mismatch fails closed
7. per-run isolation across repos and sessions
8. pause and resume preserve and restore state
9. repeated failure signature escalates to hard stop
10. hook wrapper stays silent on empty success

## Implementation checklist

When implementing this system from scratch, the agent should produce:

- the runtime package
- hook handlers
- CLI
- package-internal installable templates
- top-level templates for repo consumers
- global skill and repo skill
- tests
- README
- troubleshooting doc
- install docs
- security docs
- CI workflow

## Acceptance criteria

The system is done when all of the following are true:

1. `python3 -m unittest discover -s tests -v` passes
2. `python3 -m compileall src bin` passes
3. `python3 -m pip install .` works in a clean venv
4. the installed `autonomous-loop` command can run `install-repo`
5. the repo templates are copied correctly
6. a hook stop smoke test can claim an enable request and block incomplete work
7. a session-start smoke test returns continuity context
8. the docs are usable by both non-experts and engineers

## What the agent should not do

- do not stop at a design doc
- do not stop at scaffolding
- do not hardcode a personal home directory
- do not assume only one repo or one session exists
- do not bury the real control flow in vague prose
- do not imply that printing the token alone activates the loop before a real `Stop` hook runs

If you are an implementation agent receiving this file, treat it as the canonical system brief and build the system end to end.
