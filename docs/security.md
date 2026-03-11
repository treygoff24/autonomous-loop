# Security

`autonomous-loop` is designed to fail closed.

## Core rules

- Do not trust the model's own statement that work is complete.
- Do not let the model author the commands that verify completion.
- Do not execute shell derived from assistant output.
- Do not print normal logs to hook stdout.
- Keep trusted gate commands in repo-local config as argv arrays.

## Verification model

The controller judges completion through:

- a frozen contract
- deterministic evidence
- trusted gate profiles

Trusted commands are executed with `subprocess.run(..., shell=False)`.

## Runtime state

Mutable runtime state lives under `CODEX_HOME/autoloop`, not in the target repo. This reduces cross-repo collisions and keeps controller state out of normal project version control.

## Current limitation

Normal in-session Codex tool calls do not expose `session_id`, so loop activation uses a nonce-claim handshake through the next `Stop` hook.
