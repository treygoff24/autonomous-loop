from __future__ import annotations

import shutil
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

SRC_ROOT = TESTS_ROOT.parent / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autonomous_loop.controller import AutonomousLoopRuntime
from autonomous_loop.paths import repo_hash_for
from autonomous_loop.storage import atomic_write_json, read_json

from support import build_cli_env, make_codex_home, make_node_repo, make_temp_repo, make_user_bin, run_cli


def _hours_ago(hours: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


class CleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = make_temp_repo(prefix="autonomous-loop-cleanup-")
        self.addCleanup(lambda: shutil.rmtree(self.temp_dir, ignore_errors=True))
        self.codex_home = make_codex_home(self.temp_dir)
        self.runtime_root = self.codex_home / "autoloop"
        self.user_bin = make_user_bin(self.temp_dir)
        self.env = build_cli_env(codex_home=self.codex_home, user_bin=self.user_bin)
        self.repo = make_node_repo(
            self.temp_dir / "repo",
            package_manager="npm@10.9.0",
            scripts={"typecheck": "tsc --noEmit", "lint": "eslint .", "test": "vitest run"},
            lockfiles=("package-lock.json",),
        )
        self.runtime = AutonomousLoopRuntime(root=self.runtime_root)

    def _bootstrap_and_install(self) -> None:
        bootstrap = run_cli(["bootstrap"], env=self.env)
        self.assertEqual(bootstrap.returncode, 0, bootstrap.stdout)
        install = run_cli(["install-repo", "--repo", str(self.repo)], env=self.env)
        self.assertEqual(install.returncode, 0, install.stdout)

    def test_cleanup_archives_stale_live_sessions_and_old_requests(self) -> None:
        self._bootstrap_and_install()

        with patch.dict("os.environ", {"CODEX_THREAD_ID": "stale-session"}, clear=False):
            result = self.runtime.request_enable(cwd=self.repo, objective="Stale session")
        self.assertEqual(result["activation_mode"], "direct-env")
        repo_hash = repo_hash_for(self.runtime.paths.resolve_repo_root(self.repo))

        session_dir = self.runtime.paths.session_dir(self.runtime.paths.namespace(self.repo, "stale-session"))
        state_path = session_dir / "state.json"
        state_payload = read_json(state_path, {})
        state_payload["heartbeat_at"] = _hours_ago(72)
        state_payload["updated_at"] = _hours_ago(72)
        atomic_write_json(state_path, state_payload)

        request_files = sorted(self.runtime.paths.pending_requests_dir(repo_hash).glob("*.json"))
        self.assertEqual(len(request_files), 1)
        request_payload = read_json(request_files[0], {})
        request_payload["applied_at"] = _hours_ago(72)
        atomic_write_json(request_files[0], request_payload)

        with patch.dict("os.environ", {}, clear=False):
            queued = self.runtime.request_action("release", cwd=self.repo, reason="old pending release")
        self.assertIn("claim_token", queued)
        pending_path = self.runtime.paths.pending_request_path(repo_hash, queued["request_id"])
        pending_payload = read_json(pending_path, {})
        pending_payload["created_at"] = _hours_ago(72)
        atomic_write_json(pending_path, pending_payload)

        cleanup = self.runtime.cleanup(cwd=self.repo, stale_hours=24, retention_hours=24)

        self.assertTrue(cleanup["ok"])
        self.assertEqual(len(cleanup["archived_sessions"]), 1)
        self.assertEqual(len(cleanup["archived_requests"]), 2)

        live_status = self.runtime.status(self.repo)
        self.assertEqual(live_status["sessions"], [])
        self.assertEqual(live_status["pending_requests"], [])

        archived_session_state = read_json(
            self.runtime.paths.archived_sessions_dir(repo_hash) / "stale-session" / "state.json",
            {},
        )
        self.assertEqual(archived_session_state["state"], "stale")
        self.assertFalse(archived_session_state["active"])

    def test_cleanup_preserves_current_session(self) -> None:
        self._bootstrap_and_install()

        with patch.dict("os.environ", {"CODEX_THREAD_ID": "current-session"}, clear=False):
            self.runtime.request_enable(cwd=self.repo, objective="Current session")
            cleanup = self.runtime.cleanup(cwd=self.repo, stale_hours=1, retention_hours=1)

        self.assertTrue(cleanup["ok"])
        self.assertEqual(cleanup["archived_sessions"], [])

        live_status = self.runtime.status(self.repo, session_id="current-session")
        self.assertEqual(len(live_status["sessions"]), 1)
        self.assertEqual(live_status["sessions"][0]["state"], "active")

    def test_direct_enable_archives_stale_previous_active_session(self) -> None:
        self._bootstrap_and_install()

        with patch.dict("os.environ", {"CODEX_THREAD_ID": "old-session"}, clear=False):
            self.runtime.request_enable(cwd=self.repo, objective="Old session")

        old_state_path = self.runtime.paths.session_dir(self.runtime.paths.namespace(self.repo, "old-session")) / "state.json"
        old_state = read_json(old_state_path, {})
        old_state["heartbeat_at"] = _hours_ago(72)
        old_state["updated_at"] = _hours_ago(72)
        atomic_write_json(old_state_path, old_state)

        with patch.dict("os.environ", {"CODEX_THREAD_ID": "current-session"}, clear=False):
            result = self.runtime.request_enable(cwd=self.repo, objective="Current session")

        self.assertEqual(result["activation_mode"], "direct-env")
        status = self.runtime.status(self.repo)
        self.assertEqual([item["session_id"] for item in status["sessions"]], ["current-session"])
        archived_old_state = self.runtime.paths.archived_sessions_dir(repo_hash_for(self.runtime.paths.resolve_repo_root(self.repo))) / "old-session" / "state.json"
        self.assertTrue(archived_old_state.exists())

    def test_session_start_refreshes_heartbeat_and_archives_old_requests(self) -> None:
        self._bootstrap_and_install()

        with patch.dict("os.environ", {"CODEX_THREAD_ID": "current-session"}, clear=False):
            self.runtime.request_enable(cwd=self.repo, objective="Current session")

        current_state_path = self.runtime.paths.session_dir(self.runtime.paths.namespace(self.repo, "current-session")) / "state.json"
        current_state = read_json(current_state_path, {})
        current_state["heartbeat_at"] = _hours_ago(48)
        current_state["updated_at"] = _hours_ago(48)
        atomic_write_json(current_state_path, current_state)

        with patch.dict("os.environ", {}, clear=False):
            queued = self.runtime.request_action("release", cwd=self.repo, reason="old pending release")
        repo_hash = repo_hash_for(self.runtime.paths.resolve_repo_root(self.repo))
        pending_path = self.runtime.paths.pending_request_path(repo_hash, queued["request_id"])
        pending_payload = read_json(pending_path, {})
        pending_payload["created_at"] = _hours_ago(48)
        atomic_write_json(pending_path, pending_payload)

        context = self.runtime.handle_session_start_payload({"cwd": str(self.repo), "session_id": "current-session"})

        self.assertIsNotNone(context)
        refreshed_state = read_json(current_state_path, {})
        self.assertNotEqual(refreshed_state["heartbeat_at"], current_state["heartbeat_at"])
        status = self.runtime.status(self.repo, session_id="current-session")
        self.assertEqual(status["archived_counts"]["requests"], 1)
        self.assertEqual(
            [item["action"] for item in status["pending_requests"]],
            ["enable"],
        )


if __name__ == "__main__":
    unittest.main()
