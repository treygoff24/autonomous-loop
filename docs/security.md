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

## Current activation model

When the environment exposes a stable thread or session identifier such as `CODEX_THREAD_ID` or `CODEX_SESSION_ID`, loop requests bind directly to the live Codex session. When those identifiers are unavailable, activation falls back to the nonce-claim handshake through the next `Stop` hook. In that fallback path, `request enable` only arms a pending request, and the request becomes active only when a later `Stop` hook sees the exact `AUTOLOOP_CLAIM:<nonce>` token in `last_assistant_message` and binds it to the real session.
