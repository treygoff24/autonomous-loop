from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


NODE_PACKAGE_MANAGERS = ("npm", "pnpm", "yarn", "bun")
NODE_SCRIPT_PRIORITY = ("check", "quality", "ci", "typecheck", "lint", "test")
COMBINED_SCRIPT_NAMES = ("check", "quality", "ci")
LOCKFILE_PACKAGE_MANAGERS = {
    "pnpm-lock.yaml": "pnpm",
    "package-lock.json": "npm",
    "yarn.lock": "yarn",
    "bun.lock": "bun",
    "bun.lockb": "bun",
}
MAKE_TARGET_PRIORITY = ("check", "quality", "ci", "typecheck", "lint", "test")


@dataclass(slots=True)
class InstallRepoFailure(Exception):
    error_code: str
    message: str
    evidence: dict[str, Any]
    remediation: list[str]

    def to_payload(self, repo_root: Path) -> dict[str, Any]:
        return {
            "ok": False,
            "error_code": self.error_code,
            "repo_root": str(repo_root),
            "evidence": self.evidence,
            "message": self.message,
            "remediation": list(self.remediation),
        }


def detect_package_manager(
    package_json: dict[str, Any],
    lockfiles: set[str],
    override: str | None,
) -> str:
    if override is not None:
        return _validated_package_manager(override, error_code="invalid_package_manager_override")

    package_manager_value = package_json.get("packageManager")
    if package_manager_value is not None:
        return _validated_package_manager(str(package_manager_value))

    signals = _lockfile_signals(lockfiles)
    if len(signals) == 1:
        return signals[0]
    if len(signals) > 1:
        raise InstallRepoFailure(
            "ambiguous_package_manager",
            "install-repo found conflicting lockfile signals and cannot determine a trustworthy package manager",
            evidence={"lockfiles_found": sorted(lockfiles), "package_managers_detected": signals},
            remediation=[
                "Remove conflicting lockfiles",
                "Or rerun with --package-manager <npm|pnpm|yarn|bun>",
            ],
        )
    raise InstallRepoFailure(
        "missing_package_manager",
        "install-repo could not determine a package manager from package.json or lockfiles",
        evidence={"lockfiles_found": sorted(lockfiles)},
        remediation=[
            "Add packageManager to package.json",
            "Or rerun with --package-manager <npm|pnpm|yarn|bun>",
        ],
    )


def detect_scripts(package_json: dict[str, Any], preferred: list[str] | None) -> list[str]:
    scripts = _package_scripts(package_json)
    script_names = sorted(scripts)
    if preferred:
        return _ordered_preferred_scripts(preferred, script_names)

    combined = [name for name in COMBINED_SCRIPT_NAMES if name in scripts]
    if combined:
        return combined[:1]

    detected = [name for name in NODE_SCRIPT_PRIORITY if name in scripts]
    if not detected:
        raise InstallRepoFailure(
            "missing_verification_scripts",
            "install-repo requires a supported verification script",
            evidence={"scripts_found": script_names},
            remediation=[
                "Add a check, quality, ci, typecheck, lint, or test script to package.json",
                "Or rerun with --prefer-scripts using scripts that already exist",
            ],
        )
    return detected


def build_project_config(package_manager: str, scripts: list[str]) -> dict[str, Any]:
    commands = {name: _node_command_for_script(package_manager, name) for name in scripts}
    return build_config_from_commands(commands)


def build_config_from_commands(commands: dict[str, list[str]]) -> dict[str, Any]:
    validate_command_map(commands)
    command_names = list(commands)
    profiles = {
        "fast": [command_names[0]],
        "default": command_names,
        "final": command_names,
    }
    return {
        "version": "0.1",
        "commands": commands,
        "gateProfiles": profiles,
        "defaults": {
            "gateProfile": "default",
            "fastGateProfile": "fast",
            "finalGateProfile": "final",
            "maxStopIterations": 12,
            "maxRepeatedFailureSignature": 3,
        },
        "semanticReview": "advisory-after-green",
    }


def validate_command_map(commands: dict[str, list[str]]) -> None:
    if not commands:
        raise InstallRepoFailure(
            "missing_verification_commands",
            "install-repo generated no trusted verification commands",
            evidence={"commands": commands},
            remediation=["Define at least one trustworthy verification command"],
        )
    for name, argv in commands.items():
        if not isinstance(argv, list) or not argv or not all(isinstance(item, str) and item for item in argv):
            raise InstallRepoFailure(
                "invalid_command_argv",
                f"install-repo generated an invalid argv for command {name!r}",
                evidence={"command_name": name, "argv": argv},
                remediation=["Ensure generated commands are explicit argv arrays"],
            )


def validate_generated_config(config: dict[str, Any]) -> None:
    commands = config.get("commands", {})
    if not isinstance(commands, dict):
        commands = {}
    validate_command_map(commands)

    profiles = config.get("gateProfiles", {})
    for profile_name in ("fast", "default", "final"):
        profile = profiles.get(profile_name)
        if not isinstance(profile, list) or not profile:
            raise InstallRepoFailure(
                "empty_gate_profile",
                f"install-repo generated an empty gate profile: {profile_name}",
                evidence={"profile_name": profile_name, "profile": profile},
                remediation=["Make sure at least one trusted command is available for every gate profile"],
            )
        for command_name in profile:
            if command_name not in commands:
                raise InstallRepoFailure(
                    "unknown_command_ref",
                    f"Gate profile {profile_name!r} references undefined command {command_name!r}",
                    evidence={"profile_name": profile_name, "command_name": command_name},
                    remediation=["Ensure every gate profile references only generated command refs"],
                )

    defaults = config.get("defaults", {})
    for default_key in ("gateProfile", "fastGateProfile", "finalGateProfile"):
        profile_name = defaults.get(default_key)
        if profile_name not in profiles:
            raise InstallRepoFailure(
                "unknown_default_profile",
                f"Default {default_key!r} points to undefined gate profile {profile_name!r}",
                evidence={"default_key": default_key, "profile_name": profile_name},
                remediation=["Ensure defaults only reference generated gate profiles"],
            )


def inspect_repo(
    repo_root: Path,
    *,
    package_manager_override: str | None = None,
    prefer_scripts: list[str] | None = None,
) -> dict[str, Any]:
    prepared = _inspect_node_repo(repo_root, package_manager_override, prefer_scripts)
    if prepared is None:
        prepared = _inspect_non_node_repo(repo_root)
    validate_generated_config(prepared["project_config"])
    return prepared


def _inspect_node_repo(
    repo_root: Path,
    package_manager_override: str | None,
    prefer_scripts: list[str] | None,
) -> dict[str, Any] | None:
    package_json_path = repo_root / "package.json"
    if not package_json_path.is_file():
        return None

    package_json = _load_package_json(package_json_path)
    lockfiles = _lockfiles_for(repo_root)
    package_manager = detect_package_manager(package_json, lockfiles, package_manager_override)
    scripts = detect_scripts(package_json, prefer_scripts)
    config = build_project_config(package_manager, scripts)
    return _inspection_payload(
        repo_root,
        project_type="node",
        commands=config["commands"],
        project_config=config,
        package_manager=package_manager,
        scripts=scripts,
        lockfiles=sorted(lockfiles),
    )


def _inspect_non_node_repo(repo_root: Path) -> dict[str, Any]:
    detectors = (_makefile_commands, _python_commands, _rust_commands, _go_commands)
    for detector in detectors:
        detected = detector(repo_root)
        if detected is not None:
            project_type, commands, warnings = detected
            config = build_config_from_commands(commands)
            return _inspection_payload(
                repo_root,
                project_type=project_type,
                commands=commands,
                project_config=config,
                warnings=warnings,
            )
    raise InstallRepoFailure(
        "missing_verification_commands",
        "install-repo could not detect trustworthy verification commands for this repo",
        evidence={"repo_root": str(repo_root)},
        remediation=[
            "For Node repos, add package.json scripts such as check, quality, ci, typecheck, lint, or test",
            "For Make/Python/Rust/Go repos, add standard project files and verification targets",
            "Or create .codex/autoloop.project.json manually",
        ],
    )


def _inspection_payload(
    repo_root: Path,
    *,
    project_type: str,
    commands: dict[str, list[str]],
    project_config: dict[str, Any],
    package_manager: str | None = None,
    scripts: list[str] | None = None,
    lockfiles: list[str] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "repo_root": str(repo_root),
        "project_type_detected": project_type,
        "package_manager_detected": package_manager,
        "scripts_detected": scripts or list(commands),
        "commands_generated": commands,
        "gate_profiles_generated": project_config["gateProfiles"],
        "project_config": project_config,
        "lockfiles_found": lockfiles or [],
        "warnings": _warnings_for(commands, warnings or []),
    }


def _warnings_for(commands: dict[str, list[str]], warnings: list[str]) -> list[str]:
    result = list(warnings)
    if len(commands) == 1:
        result.append("Only one verification command was detected; all gate profiles use the same command.")
    return result


def _validated_package_manager(value: str, *, error_code: str = "unsupported_package_manager") -> str:
    normalized = value.strip().lower()
    if "@" in normalized:
        normalized = normalized.split("@", 1)[0]
    if normalized not in NODE_PACKAGE_MANAGERS:
        raise InstallRepoFailure(
            error_code,
            f"Unsupported package manager value: {value}",
            evidence={"packageManager": value},
            remediation=[f"Use one of: {', '.join(NODE_PACKAGE_MANAGERS)}"],
        )
    return normalized


def _lockfile_signals(lockfiles: set[str]) -> list[str]:
    signals = {LOCKFILE_PACKAGE_MANAGERS[name] for name in lockfiles if name in LOCKFILE_PACKAGE_MANAGERS}
    return sorted(signals)


def _package_scripts(package_json: dict[str, Any]) -> dict[str, str]:
    scripts = package_json.get("scripts", {})
    return {str(name): str(command) for name, command in scripts.items()} if isinstance(scripts, dict) else {}


def _ordered_preferred_scripts(preferred: list[str], script_names: list[str]) -> list[str]:
    ordered: list[str] = []
    for name in preferred:
        if name not in NODE_SCRIPT_PRIORITY:
            raise InstallRepoFailure(
                "invalid_preferred_script",
                f"Preferred script {name!r} is not a supported verification script",
                evidence={"preferred_scripts": preferred, "supported_scripts": list(NODE_SCRIPT_PRIORITY)},
                remediation=[
                    f"Use only supported verification scripts: {', '.join(NODE_SCRIPT_PRIORITY)}",
                    "Or write .codex/autoloop.project.json manually for custom trusted gates",
                ],
            )
        if name not in script_names:
            raise InstallRepoFailure(
                "missing_preferred_script",
                f"Preferred script {name!r} is not defined in package.json",
                evidence={"preferred_scripts": preferred, "scripts_found": script_names},
                remediation=[
                    f"Add {name!r} to package.json scripts",
                    "Or rerun with --prefer-scripts using only defined scripts",
                ],
            )
        if name not in ordered:
            ordered.append(name)
    return ordered


def _node_command_for_script(package_manager: str, script_name: str) -> list[str]:
    if package_manager == "npm":
        if script_name == "test":
            return ["npm", "test"]
        return ["npm", "run", script_name]
    if package_manager in {"pnpm", "yarn"}:
        return [package_manager, script_name]
    if package_manager == "bun":
        return ["bun", "run", script_name]
    raise InstallRepoFailure(
        "unsupported_package_manager",
        f"Unsupported package manager value: {package_manager}",
        evidence={"package_manager_detected": package_manager},
        remediation=[f"Use one of: {', '.join(NODE_PACKAGE_MANAGERS)}"],
    )


def _load_package_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InstallRepoFailure(
            "invalid_package_json",
            f"package.json is not valid JSON: {exc}",
            evidence={"package_json_path": str(path)},
            remediation=["Fix package.json JSON syntax and rerun install-repo"],
        ) from exc
    return payload if isinstance(payload, dict) else {}


def _lockfiles_for(repo_root: Path) -> set[str]:
    return {name for name in LOCKFILE_PACKAGE_MANAGERS if (repo_root / name).is_file()}


def _makefile_commands(repo_root: Path) -> tuple[str, dict[str, list[str]], list[str]] | None:
    makefile = next((repo_root / name for name in ("Makefile", "makefile") if (repo_root / name).is_file()), None)
    if makefile is None:
        return None
    targets = _make_targets(makefile)
    selected = [target for target in MAKE_TARGET_PRIORITY if target in targets]
    if not selected:
        return None
    return "make", {target: ["make", target] for target in selected}, []


def _make_targets(makefile: Path) -> set[str]:
    targets: set[str] = set()
    for line in makefile.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or line.startswith(("\t", ".", "#")) or ":" not in line:
            continue
        name = line.split(":", 1)[0].strip()
        if name and " " not in name:
            targets.add(name)
    return targets


def _python_commands(repo_root: Path) -> tuple[str, dict[str, list[str]], list[str]] | None:
    if not any((repo_root / name).exists() for name in ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt")):
        return None
    runner = ["uv", "run"] if (repo_root / "uv.lock").is_file() else []
    commands: dict[str, list[str]] = {}
    if (repo_root / "tests").exists() or _pyproject_mentions(repo_root, "pytest"):
        commands["test"] = [*runner, "pytest", "-q"] if runner else ["python3", "-m", "pytest", "-q"]
    if _pyproject_mentions(repo_root, "ruff"):
        commands["lint"] = [*runner, "ruff", "check", "."] if runner else ["ruff", "check", "."]
    if _pyproject_mentions(repo_root, "mypy"):
        commands["typecheck"] = [*runner, "mypy", "."] if runner else ["mypy", "."]
    if not commands:
        raise InstallRepoFailure(
            "missing_verification_commands",
            "install-repo found Python project files but no trustworthy Python verification command",
            evidence={
                "project_files_found": [
                    name
                    for name in ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt")
                    if (repo_root / name).exists()
                ],
                "tests_dir_found": (repo_root / "tests").exists(),
            },
            remediation=[
                "Add a tests/ directory or a pytest configuration",
                "Add ruff or mypy configuration to pyproject.toml",
                "Or write .codex/autoloop.project.json manually for custom trusted gates",
            ],
        )
    return "python", commands, []


def _pyproject_mentions(repo_root: Path, needle: str) -> bool:
    pyproject = repo_root / "pyproject.toml"
    if not pyproject.is_file():
        return False
    return needle.lower() in pyproject.read_text(encoding="utf-8", errors="replace").lower()


def _rust_commands(repo_root: Path) -> tuple[str, dict[str, list[str]], list[str]] | None:
    if not (repo_root / "Cargo.toml").is_file():
        return None
    return (
        "rust",
        {
            "fmt": ["cargo", "fmt", "--check"],
            "clippy": ["cargo", "clippy", "--all-targets", "--", "-D", "warnings"],
            "test": ["cargo", "test"],
        },
        [],
    )


def _go_commands(repo_root: Path) -> tuple[str, dict[str, list[str]], list[str]] | None:
    if not (repo_root / "go.mod").is_file():
        return None
    return "go", {"test": ["go", "test", "./..."]}, []
