from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any


def run_command(argv: list[str], cwd: str | Path, extra_env: dict[str, str] | None = None) -> dict[str, Any]:
    if not argv:
        raise ValueError("trusted command argv cannot be empty")
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    completed = subprocess.run(
        argv,
        cwd=str(cwd),
        env=env,
        shell=False,
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "command": argv,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "passed": completed.returncode == 0,
    }


def run_gate_profile(profile_name: str, project_config: dict[str, Any], cwd: str | Path) -> dict[str, Any]:
    commands = project_config.get("commands", {})
    profiles = project_config.get("gateProfiles", {})
    failures: list[str] = []
    results: dict[str, dict[str, Any]] = {}
    for command_name in profiles.get(profile_name, []):
        argv = commands.get(command_name)
        if not isinstance(argv, list):
            result = {
                "command": [],
                "returncode": 127,
                "stdout": "",
                "stderr": f"unknown commandRef: {command_name}",
                "passed": False,
            }
        else:
            result = run_command([str(item) for item in argv], cwd=cwd)
        results[command_name] = result
        if not result["passed"]:
            failures.append(command_name)
    return {"profile": profile_name, "passed": not failures, "failures": failures, "results": results}
