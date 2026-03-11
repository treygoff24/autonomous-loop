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
)


class BootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = make_temp_repo(prefix="autonomous-loop-bootstrap-")
        self.addCleanup(lambda: shutil.rmtree(self.temp_dir, ignore_errors=True))
        self.codex_home = make_codex_home(self.temp_dir)
        self.runtime_root = self.codex_home / "autoloop"
        self.user_bin = make_user_bin(self.temp_dir)
        self.fake_cli_path = install_fake_cli(self.user_bin)
        self.env = build_cli_env(codex_home=self.codex_home, user_bin=self.user_bin)

    def test_doctor_reports_missing_machine_setup(self) -> None:
        completed = run_cli(["doctor"], env=self.env)

        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["ok"])
        self.assertIn("global_hooks", payload["checks"])
        self.assertIn("global_skill", payload["checks"])
        self.assertIn("cli_on_path", payload["checks"])

    def test_bootstrap_installs_global_hooks_and_skill(self) -> None:
        completed = run_cli(["bootstrap"], env=self.env)

        self.assertEqual(completed.returncode, 0)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue((self.codex_home / "hooks.json").is_file())
        self.assertTrue((self.codex_home / "skills" / "autonomous-loop" / "SKILL.md").is_file())
        machine = load_json(self.runtime_root / "machine.json")
        self.assertIsNotNone(machine)
        assert machine is not None
        self.assertEqual(machine["command_mode"], "absolute-cli")

    def test_install_repo_renders_hooks_from_bootstrap_machine_config(self) -> None:
        bootstrap = run_cli(["bootstrap"], env=self.env)
        self.assertEqual(bootstrap.returncode, 0)

        repo = make_node_repo(
            self.temp_dir / "repo",
            package_manager="npm@10.9.0",
            scripts={"lint": "eslint .", "test": "vitest run"},
            lockfiles=("package-lock.json",),
        )

        completed = run_cli(["install-repo", "--repo", str(repo)], env=self.env)

        self.assertEqual(completed.returncode, 0)
        hooks = load_json(repo / ".codex" / "hooks.json")
        self.assertIsNotNone(hooks)
        assert hooks is not None
        command = hooks["hooks"]["Stop"][0]["hooks"][0]["command"]
        self.assertIn(str(self.fake_cli_path), command)
