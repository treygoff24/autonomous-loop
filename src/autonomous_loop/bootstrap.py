from __future__ import annotations

import json
import os
import shlex
import shutil
from pathlib import Path
from typing import Any


MACHINE_VERSION = "0.2"
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


def detect_codex_version(codex_home: Path) -> str | None:
    """Return the installed Codex CLI version, or fall back to version.json metadata."""
    import shutil as _shutil
    import subprocess as _subprocess

    codex_bin = _shutil.which("codex")
    if codex_bin:
        try:
            result = _subprocess.run(
                [codex_bin, "--version"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip().split()[-1]
        except (OSError, _subprocess.TimeoutExpired):
            pass

    version_path = codex_home / "version.json"
    if not version_path.is_file():
        return None
    try:
        payload = json.loads(version_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    value = payload.get("latest_version")
    return str(value) if value is not None else None


def build_machine_config(command_path: str, codex_home: Path | None = None) -> dict[str, Any]:
    hook_commands = build_hook_commands(command_path)
    config: dict[str, Any] = {
        "version": MACHINE_VERSION,
        "command_mode": "absolute-cli",
        "command_path": command_path,
        "hook_commands": hook_commands,
    }
    if codex_home is not None:
        codex_version = detect_codex_version(codex_home)
        if codex_version is not None:
            config["codex_version"] = codex_version
    return config


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
