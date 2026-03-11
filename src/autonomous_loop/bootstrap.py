from __future__ import annotations

import os
import shlex
import shutil
from pathlib import Path
from typing import Any


MACHINE_VERSION = "0.1"
CLI_BINARY = "autonomous-loop"


def resolve_cli_path(binary_name: str = CLI_BINARY) -> tuple[str | None, str | None]:
    command = shutil.which(binary_name)
    if not command:
        return None, f"{binary_name} was not found on PATH"
    absolute = Path(os.path.abspath(command))
    if not absolute.exists():
        return None, f"{binary_name} resolved to a missing file: {absolute}"
    if not os.access(absolute, os.X_OK):
        return None, f"{binary_name} is not executable: {absolute}"
    return str(absolute), None


def build_hook_commands(command_path: str) -> dict[str, str]:
    quoted = shlex.quote(command_path)
    return {
        "session_start": f"{quoted} hook session-start",
        "stop": f"{quoted} hook stop",
    }


def build_hooks_payload(hook_commands: dict[str, str]) -> dict[str, Any]:
    return {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "startup|resume",
                    "hooks": [
                        {
                            "type": "command",
                            "command": hook_commands["session_start"],
                            "timeout": 15,
                            "statusMessage": "autonomous-loop continuity",
                        }
                    ],
                }
            ],
            "Stop": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": hook_commands["stop"],
                            "timeout": 60,
                            "statusMessage": "autonomous-loop stop gate",
                        }
                    ]
                }
            ],
        }
    }


def build_machine_config(command_path: str) -> dict[str, Any]:
    hook_commands = build_hook_commands(command_path)
    return {
        "version": MACHINE_VERSION,
        "command_mode": "absolute-cli",
        "command_path": command_path,
        "hook_commands": hook_commands,
    }


def validate_machine_config(payload: Any) -> tuple[bool, str | None]:
    if not isinstance(payload, dict):
        return False, "machine config payload is missing"
    hook_commands = payload.get("hook_commands")
    if payload.get("command_mode") != "absolute-cli":
        return False, "machine config command_mode must be absolute-cli"
    if not isinstance(payload.get("command_path"), str) or not payload["command_path"]:
        return False, "machine config command_path is missing"
    if not isinstance(hook_commands, dict):
        return False, "machine config hook_commands is missing"
    for key in ("session_start", "stop"):
        value = hook_commands.get(key)
        if not isinstance(value, str) or not value:
            return False, f"machine config hook_commands.{key} is missing"
    return True, None
