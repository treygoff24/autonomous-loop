from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from support import (
    build_cli_env,
    install_fake_cli,
    load_json,
    make_codex_home,
    make_node_repo,
    make_temp_repo,
    make_user_bin,
    run_cli,
    write_codex_hooks,
)


class DoctorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = make_temp_repo(prefix="autonomous-loop-doctor-")
        self.addCleanup(lambda: shutil.rmtree(self.temp_dir, ignore_errors=True))
        self.codex_home = make_codex_home(self.temp_dir)
        self.runtime_root = self.codex_home / "autoloop"
        self.user_bin = make_user_bin(self.temp_dir)
        self.fake_cli_path = install_fake_cli(self.user_bin)
        self.env = build_cli_env(codex_home=self.codex_home, user_bin=self.user_bin)

    def _bootstrap(self) -> None:
        result = run_cli(["bootstrap"], env=self.env)
        self.assertEqual(result.returncode, 0, f"bootstrap failed: {result.stdout}\n{result.stderr}")

    def test_happy_path_returns_ok_true(self) -> None:
        self._bootstrap()

        completed = run_cli(["doctor"], env=self.env)

        self.assertEqual(completed.returncode, 0)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["checks"]["machine_config"]["ok"])
        self.assertTrue(payload["checks"]["global_hooks"]["ok"])
        self.assertTrue(payload["checks"]["global_skill"]["ok"])
        self.assertTrue(payload["checks"]["cli_on_path"]["ok"])

    def test_missing_machine_config_reports_machine_config_check_failed(self) -> None:
        # Only create codex_home, no bootstrap
        completed = run_cli(["doctor"], env=self.env)

        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["checks"]["machine_config"]["ok"])

    def test_missing_global_hooks_reports_global_hooks_check_failed(self) -> None:
        self._bootstrap()
        # Remove global hooks file
        hooks_path = self.codex_home / "hooks.json"
        hooks_path.unlink()

        completed = run_cli(["doctor"], env=self.env)

        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["checks"]["global_hooks"]["ok"])

    def test_stale_global_hooks_reports_mismatch(self) -> None:
        self._bootstrap()
        # Write a global hooks file with a different stop command
        stale_hooks = {
            "hooks": {
                "Stop": [{"hooks": [{"type": "command", "command": "/old/path/autonomous-loop hook stop", "timeout": 60}]}],
                "SessionStart": [{"matcher": "startup|resume", "hooks": [{"type": "command", "command": "/old/path/autonomous-loop hook session-start", "timeout": 15}]}],
            }
        }
        write_codex_hooks(self.codex_home, stale_hooks)

        completed = run_cli(["doctor"], env=self.env)

        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["checks"]["global_hooks"]["ok"])
        self.assertIn("stop command does not match", payload["checks"]["global_hooks"]["reason"])

    def test_with_cwd_missing_repo_install_reports_repo_install_check_failed(self) -> None:
        self._bootstrap()
        repo = make_node_repo(
            self.temp_dir / "repo",
            package_manager="npm@10.9.0",
            scripts={"lint": "eslint .", "test": "vitest run"},
            lockfiles=("package-lock.json",),
        )

        completed = run_cli(["doctor", "--cwd", str(repo)], env=self.env)

        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["checks"]["repo_install"]["ok"])

    def test_with_cwd_stale_repo_hooks_reports_mismatch_with_remediation(self) -> None:
        self._bootstrap()
        repo = make_node_repo(
            self.temp_dir / "repo",
            package_manager="npm@10.9.0",
            scripts={"lint": "eslint .", "test": "vitest run"},
            lockfiles=("package-lock.json",),
        )
        # Run install-repo first so config is present
        install = run_cli(["install-repo", "--repo", str(repo)], env=self.env)
        self.assertEqual(install.returncode, 0, f"install-repo failed: {install.stdout}\n{install.stderr}")

        # Overwrite repo hooks with stale data
        stale_hooks = {
            "hooks": {
                "Stop": [{"hooks": [{"type": "command", "command": "/old/path/autonomous-loop hook stop", "timeout": 60}]}],
                "SessionStart": [{"matcher": "startup|resume", "hooks": [{"type": "command", "command": "/old/path/autonomous-loop hook session-start", "timeout": 15}]}],
            }
        }
        repo_hooks_path = repo / ".codex" / "hooks.json"
        repo_hooks_path.write_text(json.dumps(stale_hooks, indent=2) + "\n", encoding="utf-8")

        completed = run_cli(["doctor", "--cwd", str(repo)], env=self.env)

        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["ok"])
        check = payload["checks"]["repo_install"]
        self.assertFalse(check["ok"])
        self.assertIn("stop command does not match", check["reason"])
        self.assertIn("remediation", check)

    def test_with_cwd_fully_installed_repo_passes(self) -> None:
        self._bootstrap()
        repo = make_node_repo(
            self.temp_dir / "repo",
            package_manager="npm@10.9.0",
            scripts={"lint": "eslint .", "test": "vitest run"},
            lockfiles=("package-lock.json",),
        )
        install = run_cli(["install-repo", "--repo", str(repo)], env=self.env)
        self.assertEqual(install.returncode, 0, f"install-repo failed: {install.stdout}\n{install.stderr}")

        completed = run_cli(["doctor", "--cwd", str(repo)], env=self.env)

        self.assertEqual(completed.returncode, 0)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["checks"]["repo_install"]["ok"])


if __name__ == "__main__":
    unittest.main()
