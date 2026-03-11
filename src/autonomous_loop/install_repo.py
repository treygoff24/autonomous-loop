from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SUPPORTED_PACKAGE_MANAGERS = ("npm", "pnpm", "yarn", "bun")
SUPPORTED_SCRIPTS = ("typecheck", "lint", "test")
LOCKFILE_PACKAGE_MANAGERS = {
    "pnpm-lock.yaml": "pnpm",
    "package-lock.json": "npm",
    "yarn.lock": "yarn",
    "bun.lock": "bun",
    "bun.lockb": "bun",
}


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


def _normalize_package_manager(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    if "@" in normalized:
        normalized = normalized.split("@", 1)[0]
    if normalized not in SUPPORTED_PACKAGE_MANAGERS:
        return None
    return normalized


def _lockfile_signals(lockfiles: set[str]) -> list[str]:
    signals = {LOCKFILE_PACKAGE_MANAGERS[name] for name in lockfiles if name in LOCKFILE_PACKAGE_MANAGERS}
    return sorted(signals)


def detect_package_manager(
    package_json: dict[str, Any],
    lockfiles: set[str],
    override: str | None,
) -> str:
    if override is not None:
        normalized_override = _normalize_package_manager(override)
        if normalized_override is None:
            raise InstallRepoFailure(
                "invalid_package_manager_override",
                f"Unsupported package manager override: {override}",
                evidence={"override": override},
                remediation=[f"Use one of: {', '.join(SUPPORTED_PACKAGE_MANAGERS)}"],
            )
        return normalized_override

    package_manager_value = package_json.get("packageManager")
    if package_manager_value is not None:
        normalized_package_manager = _normalize_package_manager(str(package_manager_value))
        if normalized_package_manager is None:
            raise InstallRepoFailure(
                "unsupported_package_manager",
                f"Unsupported packageManager value: {package_manager_value}",
                evidence={"packageManager": package_manager_value},
                remediation=[f"Use one of: {', '.join(SUPPORTED_PACKAGE_MANAGERS)}"],
            )
        return normalized_package_manager

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
    raw_scripts = package_json.get("scripts", {})
    scripts = raw_scripts if isinstance(raw_scripts, dict) else {}
    script_names = sorted(str(name) for name in scripts)
    if preferred:
        ordered: list[str] = []
        for name in preferred:
            if name not in SUPPORTED_SCRIPTS:
                raise InstallRepoFailure(
                    "invalid_preferred_script",
                    f"Unsupported preferred script: {name}",
                    evidence={"preferred_scripts": preferred},
                    remediation=[f"Use only: {', '.join(SUPPORTED_SCRIPTS)}"],
                )
            if name not in scripts:
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

    detected = [name for name in SUPPORTED_SCRIPTS if name in scripts]
    if not detected:
        raise InstallRepoFailure(
            "missing_verification_scripts",
            "install-repo requires at least one of: typecheck, lint, test",
            evidence={"scripts_found": script_names},
            remediation=[
                "Add a lint, test, or typecheck script to package.json",
                "Or rerun with --prefer-scripts using scripts that already exist",
            ],
        )
    return detected


def _command_for_script(package_manager: str, script_name: str) -> list[str]:
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
        remediation=[f"Use one of: {', '.join(SUPPORTED_PACKAGE_MANAGERS)}"],
    )


def build_project_config(package_manager: str, scripts: list[str]) -> dict[str, Any]:
    if not scripts:
        raise InstallRepoFailure(
            "missing_verification_scripts",
            "install-repo requires at least one verification command",
            evidence={"scripts_detected": scripts},
            remediation=["Define at least one of: typecheck, lint, test"],
        )
    commands = {name: _command_for_script(package_manager, name) for name in scripts}
    profiles = {
        "fast": [scripts[0]],
        "default": list(scripts),
        "final": list(scripts),
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


def validate_generated_config(config: dict[str, Any]) -> None:
    commands = config.get("commands", {})
    if not isinstance(commands, dict) or not commands:
        raise InstallRepoFailure(
            "empty_commands",
            "install-repo generated no trusted commands",
            evidence={"commands": commands},
            remediation=["Make sure the target repo defines at least one supported verification script"],
        )
    for name, argv in commands.items():
        if not isinstance(argv, list) or not argv or not all(isinstance(item, str) and item for item in argv):
            raise InstallRepoFailure(
                "invalid_command_argv",
                f"install-repo generated an invalid argv for command {name!r}",
                evidence={"command_name": name, "argv": argv},
                remediation=["Ensure generated commands are explicit argv arrays"],
            )

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
    package_json_path = repo_root / "package.json"
    if not package_json_path.is_file():
        raise InstallRepoFailure(
            "missing_package_json",
            "install-repo currently supports Node-style repos only and requires package.json",
            evidence={"package_json_path": str(package_json_path)},
            remediation=[
                "Run install-repo against a repo root containing package.json",
                "Or add package.json before rerunning install-repo",
            ],
        )

    try:
        package_json = json.loads(package_json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InstallRepoFailure(
            "invalid_package_json",
            f"package.json is not valid JSON: {exc}",
            evidence={"package_json_path": str(package_json_path)},
            remediation=["Fix package.json JSON syntax and rerun install-repo"],
        ) from exc

    lockfiles = {
        name for name in LOCKFILE_PACKAGE_MANAGERS if (repo_root / name).is_file()
    }
    package_manager = detect_package_manager(package_json, lockfiles, package_manager_override)
    scripts = detect_scripts(package_json, prefer_scripts)
    config = build_project_config(package_manager, scripts)
    validate_generated_config(config)

    warnings: list[str] = []
    if len(scripts) == 1:
        warnings.append("Only one verification script was detected; all gate profiles use the same command.")

    return {
        "ok": True,
        "repo_root": str(repo_root),
        "package_manager_detected": package_manager,
        "scripts_detected": scripts,
        "commands_generated": config["commands"],
        "gate_profiles_generated": config["gateProfiles"],
        "project_config": config,
        "lockfiles_found": sorted(lockfiles),
        "warnings": warnings,
    }
