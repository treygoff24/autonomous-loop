from __future__ import annotations

import json
import re
from typing import Any


CLAIM_TOKEN_RE = re.compile(r"AUTOLOOP_CLAIM:([A-Za-z0-9_-]+)")


def parse_claim_nonce(last_assistant_message: str | None) -> str | None:
    if not last_assistant_message:
        return None
    match = CLAIM_TOKEN_RE.search(last_assistant_message)
    if match is None:
        return None
    return match.group(1)


def parse_hook_input(raw: str) -> dict[str, Any]:
    payload = json.loads(raw or "{}")
    if not isinstance(payload, dict):
        raise ValueError("hook payload must be a JSON object")
    return payload


def stop_block(reason: str) -> dict[str, Any]:
    return {"decision": "block", "reason": reason}


def stop_hard_stop(reason: str) -> dict[str, Any]:
    return {"continue": False, "stopReason": reason}


def session_start_context(message: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": message,
        }
    }


def wrap_hook_result(exit_code: int, stdout: str = "", stderr: str = "") -> str:
    if exit_code == 0 and not stdout.strip():
        return ""
    if stdout.strip():
        return stdout.strip()
    return stderr.strip()
