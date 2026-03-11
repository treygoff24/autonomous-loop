from __future__ import annotations

import json
import os
import shutil
import sys
import unittest
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from support import (
    PROJECT_ROOT,
    RuntimeAdapter,
    build_cli_env,
    install_fake_cli,
    load_installed_project_config,
    load_json,
    make_codex_home,
    make_node_repo,
    make_temp_repo,
    make_user_bin,
    run_cli,
    run_install_repo_cli,
)
from autonomous_loop.gates import run_gate_profile
from autonomous_loop.install_repo import (
    InstallRepoFailure,
    build_project_config,
    detect_package_manager,
)


class InstallRepoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._env_backup = {
            "CODEX_HOME": os.environ.get("CODEX_HOME"),
            "AUTONOMOUS_LOOP_HOME": os.environ.get("AUTONOMOUS_LOOP_HOME"),
            "PATH": os.environ.get("PATH", ""),
        }
        cls._bootstrap_root = make_temp_repo(prefix="autonomous-loop-install-home-")
        cls._codex_home = make_codex_home(cls._bootstrap_root)
        cls._user_bin = make_user_bin(cls._bootstrap_root)
        cls._fake_cli_path = install_fake_cli(cls._user_bin)
        cls._cli_env = build_cli_env(codex_home=cls._codex_home, user_bin=cls._user_bin)

        os.environ["CODEX_HOME"] = cls._cli_env["CODEX_HOME"]
        os.environ["AUTONOMOUS_LOOP_HOME"] = cls._cli_env["AUTONOMOUS_LOOP_HOME"]
        os.environ["PATH"] = cls._cli_env["PATH"]

        bootstrap = run_cli(["bootstrap"], env=cls._cli_env)
        if bootstrap.returncode != 0:
            raise AssertionError(f"bootstrap failed in test setup: {bootstrap.stdout}\n{bootstrap.stderr}")

        cls.runtime = RuntimeAdapter()

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls._bootstrap_root, ignore_errors=True)
        for key in ("CODEX_HOME", "AUTONOMOUS_LOOP_HOME"):
            original = cls._env_backup.get(key)
            if original is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original
        os.environ["PATH"] = cls._env_backup["PATH"]

    def setUp(self) -> None:
        self.temp_dir = make_temp_repo(prefix="autonomous-loop-install-")
        self.addCleanup(lambda: shutil.rmtree(self.temp_dir, ignore_errors=True))

    def make_repo(
        self,
        name: str,
        *,
        package_manager: str | None = None,
        scripts: dict[str, str] | None = None,
        lockfiles: tuple[str, ...] = (),
    ) -> Path:
        return make_node_repo(
            self.temp_dir / name,
            package_manager=package_manager,
            scripts=scripts,
            lockfiles=lockfiles,
        )

    def test_install_repo_generates_npm_commands(self) -> None:
        repo = self.make_repo(
            "npm-app",
            package_manager="npm@10.9.0",
            scripts={"lint": "eslint .", "test": "vitest run"},
            lockfiles=("package-lock.json",),
        )

        result = self.runtime.call("install_repo", repo_root=repo)
        config = load_installed_project_config(repo)

        self.assertTrue(result["ok"])
        self.assertEqual(result["package_manager_detected"], "npm")
        self.assertEqual(result["scripts_detected"], ["lint", "test"])
        self.assertEqual(config["commands"]["lint"], ["npm", "run", "lint"])
        self.assertEqual(config["commands"]["test"], ["npm", "test"])
        self.assertEqual(config["gateProfiles"]["fast"], ["lint"])
        self.assertEqual(config["gateProfiles"]["default"], ["lint", "test"])

    def test_install_repo_cli_succeeds_for_supported_repo(self) -> None:
        repo = self.make_repo(
            "npm-cli-app",
            package_manager="npm@10.9.0",
            scripts={"lint": "eslint .", "test": "vitest run"},
            lockfiles=("package-lock.json",),
        )

        completed = run_install_repo_cli(repo)
        payload = json.loads(completed.stdout)
        config = load_installed_project_config(repo)

        self.assertEqual(completed.returncode, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["package_manager_detected"], "npm")
        self.assertEqual(config["commands"]["lint"], ["npm", "run", "lint"])

    def test_install_repo_generates_pnpm_profiles_in_stable_order(self) -> None:
        repo = self.make_repo(
            "pnpm-app",
            package_manager="pnpm@10.0.0",
            scripts={"typecheck": "tsc --noEmit", "lint": "eslint .", "test": "vitest run"},
            lockfiles=("pnpm-lock.yaml",),
        )

        result = self.runtime.call("install_repo", repo_root=repo)
        config = load_installed_project_config(repo)

        self.assertTrue(result["ok"])
        self.assertEqual(result["scripts_detected"], ["typecheck", "lint", "test"])
        self.assertEqual(config["gateProfiles"]["fast"], ["typecheck"])
        self.assertEqual(config["gateProfiles"]["default"], ["typecheck", "lint", "test"])
        self.assertEqual(config["gateProfiles"]["final"], ["typecheck", "lint", "test"])

    def test_install_repo_collapses_profiles_for_single_script_repo(self) -> None:
        repo = self.make_repo(
            "lint-only",
            package_manager="npm@10.9.0",
            scripts={"lint": "eslint ."},
            lockfiles=("package-lock.json",),
        )

        result = self.runtime.call("install_repo", repo_root=repo)
        config = load_installed_project_config(repo)

        self.assertTrue(result["ok"])
        self.assertEqual(result["warnings"], ["Only one verification script was detected; all gate profiles use the same command."])
        self.assertEqual(config["gateProfiles"]["fast"], ["lint"])
        self.assertEqual(config["gateProfiles"]["default"], ["lint"])
        self.assertEqual(config["gateProfiles"]["final"], ["lint"])

    def test_install_repo_fails_closed_when_no_supported_scripts(self) -> None:
        repo = self.make_repo(
            "missing-scripts",
            package_manager="npm@10.9.0",
            scripts={"dev": "vite"},
            lockfiles=("package-lock.json",),
        )

        completed = run_install_repo_cli(repo)
        payload = json.loads(completed.stdout)

        self.assertEqual(completed.returncode, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error_code"], "missing_verification_scripts")
        self.assertEqual(payload["repo_root"], str(repo.resolve()))
        self.assertEqual(payload["evidence"]["scripts_found"], ["dev"])
        self.assertIsNone(load_installed_project_config(repo))

    def test_install_repo_preserves_existing_project_config_without_force(self) -> None:
        repo = self.make_repo(
            "preserve-config",
            package_manager="npm@10.9.0",
            scripts={"lint": "eslint .", "test": "vitest run"},
            lockfiles=("package-lock.json",),
        )
        existing = repo / ".codex" / "autoloop.project.json"
        existing.parent.mkdir(parents=True, exist_ok=True)
        existing.write_text(
            json.dumps({"version": "0.1", "commands": {"custom": ["echo", "keep-me"]}}, indent=2) + "\n",
            encoding="utf-8",
        )

        result = self.runtime.call("install_repo", repo_root=repo)

        self.assertTrue(result["ok"])
        self.assertEqual(load_json(existing), {"version": "0.1", "commands": {"custom": ["echo", "keep-me"]}})
        self.assertNotIn(str(existing), result["copied"])
        self.assertIn("Existing .codex/autoloop.project.json was preserved; rerun with --force to overwrite it.", result["warnings"])
        self.assertTrue((repo / ".codex" / "hooks.json").is_file())
        self.assertTrue((repo / ".agents" / "skills" / "autonomous-loop" / "SKILL.md").is_file())

    def test_install_repo_preserves_and_forces_repo_support_files_per_artifact(self) -> None:
        repo = self.make_repo(
            "support-files",
            package_manager="npm@10.9.0",
            scripts={"lint": "eslint .", "test": "vitest run"},
            lockfiles=("package-lock.json",),
        )
        hooks_path = repo / ".codex" / "hooks.json"
        skill_path = repo / ".agents" / "skills" / "autonomous-loop" / "SKILL.md"
        hooks_path.parent.mkdir(parents=True, exist_ok=True)
        skill_path.parent.mkdir(parents=True, exist_ok=True)
        hooks_path.write_text("{\"custom\": true}\n", encoding="utf-8")
        skill_path.write_text("custom skill\n", encoding="utf-8")

        result_without_force = self.runtime.call("install_repo", repo_root=repo)

        self.assertTrue(result_without_force["ok"])
        self.assertEqual(hooks_path.read_text(encoding="utf-8"), "{\"custom\": true}\n")
        self.assertEqual(skill_path.read_text(encoding="utf-8"), "custom skill\n")

        result_with_force = self.runtime.call("install_repo", repo_root=repo, force=True)

        self.assertTrue(result_with_force["ok"])
        rendered_hooks = load_json(hooks_path)
        self.assertIsNotNone(rendered_hooks)
        assert rendered_hooks is not None
        stop_command = rendered_hooks["hooks"]["Stop"][0]["hooks"][0]["command"]
        self.assertEqual(stop_command, f"{self._fake_cli_path} hook stop")
        self.assertEqual(
            skill_path.read_text(encoding="utf-8"),
            (
                PROJECT_ROOT
                / "src"
                / "autonomous_loop"
                / "resources"
                / "templates"
                / ".agents"
                / "skills"
                / "autonomous-loop"
                / "SKILL.md"
            ).read_text(encoding="utf-8"),
        )

    def test_detect_package_manager_prefers_cli_override(self) -> None:
        package_json = {"packageManager": "pnpm@10.0.0"}
        detected = detect_package_manager(package_json, {"package-lock.json"}, override="npm")
        self.assertEqual(detected, "npm")

    def test_detect_package_manager_prefers_package_json_over_lockfiles(self) -> None:
        package_json = {"packageManager": "yarn@4.6.0"}
        detected = detect_package_manager(package_json, {"pnpm-lock.yaml"}, override=None)
        self.assertEqual(detected, "yarn")

    def test_detect_package_manager_fails_for_ambiguous_lockfiles(self) -> None:
        with self.assertRaises(InstallRepoFailure) as context:
            detect_package_manager({}, {"package-lock.json", "pnpm-lock.yaml"}, override=None)
        self.assertEqual(context.exception.error_code, "ambiguous_package_manager")

    def test_prefer_scripts_requires_present_script(self) -> None:
        repo = self.make_repo(
            "prefer-missing",
            package_manager="npm@10.9.0",
            scripts={"lint": "eslint ."},
            lockfiles=("package-lock.json",),
        )

        completed = run_install_repo_cli(repo, prefer_scripts=["lint", "test"])
        payload = json.loads(completed.stdout)

        self.assertEqual(completed.returncode, 1)
        self.assertEqual(payload["error_code"], "missing_preferred_script")
        self.assertEqual(payload["evidence"]["preferred_scripts"], ["lint", "test"])

    def test_yarn_and_bun_command_generation_smoke(self) -> None:
        cases = {
            "yarn": {
                "lint": ["yarn", "lint"],
                "typecheck": ["yarn", "typecheck"],
                "test": ["yarn", "test"],
            },
            "bun": {
                "lint": ["bun", "run", "lint"],
                "typecheck": ["bun", "run", "typecheck"],
                "test": ["bun", "run", "test"],
            },
        }
        for package_manager, expected in cases.items():
            with self.subTest(package_manager=package_manager):
                config = build_project_config(package_manager, ["typecheck", "lint", "test"])
                self.assertEqual(config["commands"], expected)

    def test_generated_config_is_consumable_by_gate_runner(self) -> None:
        repo = self.make_repo(
            "gate-runner",
            package_manager="npm@10.9.0",
            scripts={"lint": "python3 -c \"print('lint ok')\""},
            lockfiles=("package-lock.json",),
        )

        result = self.runtime.call("install_repo", repo_root=repo)
        config = load_installed_project_config(repo)
        gate_result = run_gate_profile("default", config, repo)

        self.assertTrue(result["ok"])
        self.assertTrue(gate_result["passed"])
        self.assertEqual(gate_result["failures"], [])


if __name__ == "__main__":
    unittest.main()
