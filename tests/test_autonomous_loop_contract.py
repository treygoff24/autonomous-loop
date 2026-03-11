from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TESTS_ROOT = Path(__file__).resolve().parent
import sys
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

from support import (
    BIN_ROOT,
    ContractError,
    PROJECT_ROOT,
    RuntimeAdapter,
    artifact_contract_hash,
    artifact_run_id,
    discover_artifacts,
    json_files_under,
    meaningful_text,
    normalize_action,
    state_is_active,
)
from autonomous_loop.controller import AutonomousLoopRuntime


class AutonomousLoopContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = RuntimeAdapter()
        required = ("enable", "stop", "pause", "resume")
        missing = [name for name in required if not cls.runtime.has_capability(name)]
        if missing:
            raise ContractError(
                "Autonomous-loop runtime is missing required capabilities: "
                + ", ".join(missing)
            )

    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="autonomous-loop-contract-"))
        self.addCleanup(lambda: shutil.rmtree(self.temp_dir, ignore_errors=True))

    def enable_run(self, *, enabled: bool = True, goal: str = "Ship the autonomous loop") -> dict[str, dict]:
        before = set(json_files_under(self.temp_dir))
        self.runtime.call(
            "enable",
            project_dir=self.temp_dir,
            goal=goal,
            enabled=enabled,
            max_iterations=8,
        )
        after = set(json_files_under(self.temp_dir))

        if not enabled:
            self.assertEqual(
                after,
                before,
                "Disabled mode should be a no-op and should not persist state or contract artifacts",
            )
            return {}

        artifacts = discover_artifacts(self.temp_dir)
        self.assertGreaterEqual(
            len(after - before),
            2,
            "Enable should create separate state and contract artifacts",
        )
        return artifacts

    def stop_run(
        self,
        *,
        run_id: str | None,
        contract_hash: str | None,
        tasks_complete: bool,
        final_gate_passed: bool,
        failure_signature: str | None = None,
    ) -> str:
        result = self.runtime.call(
            "stop",
            project_dir=self.temp_dir,
            run_id=run_id,
            contract_hash=contract_hash,
            tasks_complete=tasks_complete,
            final_gate_passed=final_gate_passed,
            failure_signature=failure_signature,
        )
        return normalize_action(result)

    def test_disabled_mode_is_a_noop(self) -> None:
        result = self.runtime.call(
            "enable",
            project_dir=self.temp_dir,
            goal="Disabled run",
            enabled=False,
            max_iterations=5,
        )
        action = normalize_action(result)
        self.assertIn(action, {"noop", "unknown"}, "Disabled enable should report a noop-style outcome")
        self.assertEqual(
            json_files_under(self.temp_dir),
            [],
            "Disabled mode must not leave runtime artifacts behind",
        )

    def test_enable_creates_state_and_contract_with_matching_identity(self) -> None:
        artifacts = self.enable_run()

        state_run_id = artifact_run_id(artifacts["state"])
        contract_run_id = artifact_run_id(artifacts["contract"])
        state_hash = artifact_contract_hash(artifacts["state"])
        contract_hash = artifact_contract_hash(artifacts["contract"])

        self.assertTrue(state_run_id, "State artifact should record a run identity")
        self.assertTrue(contract_run_id, "Contract artifact should record a run identity")
        self.assertEqual(state_run_id, contract_run_id, "State and contract should refer to the same run")
        self.assertTrue(contract_hash, "Contract artifact should record a contract hash")
        self.assertEqual(
            state_hash,
            contract_hash,
            "State should carry the active contract hash so stop-time validation can fail closed",
        )

    def test_stop_blocks_when_tasks_are_incomplete(self) -> None:
        artifacts = self.enable_run()
        action = self.stop_run(
            run_id=artifact_run_id(artifacts["state"]),
            contract_hash=artifact_contract_hash(artifacts["contract"]),
            tasks_complete=False,
            final_gate_passed=True,
        )
        self.assertEqual(action, "block")
        self.assertTrue(state_is_active(self.temp_dir), "Blocked stop should keep the run active")

    def test_stop_blocks_when_final_gate_fails(self) -> None:
        artifacts = self.enable_run()
        action = self.stop_run(
            run_id=artifact_run_id(artifacts["state"]),
            contract_hash=artifact_contract_hash(artifacts["contract"]),
            tasks_complete=True,
            final_gate_passed=False,
            failure_signature="final-gate:test-failed",
        )
        self.assertEqual(action, "block")
        self.assertTrue(state_is_active(self.temp_dir), "A failed final gate should not release the run")

    def test_stop_releases_when_all_completion_conditions_are_green(self) -> None:
        artifacts = self.enable_run()
        action = self.stop_run(
            run_id=artifact_run_id(artifacts["state"]),
            contract_hash=artifact_contract_hash(artifacts["contract"]),
            tasks_complete=True,
            final_gate_passed=True,
        )
        self.assertEqual(action, "allow")
        self.assertFalse(
            state_is_active(self.temp_dir),
            "A green stop decision should clear or deactivate the run state",
        )

    def test_contract_hash_mismatch_fails_closed(self) -> None:
        artifacts = self.enable_run()
        action = self.stop_run(
            run_id=artifact_run_id(artifacts["state"]),
            contract_hash="mismatched-contract-hash",
            tasks_complete=True,
            final_gate_passed=True,
        )
        self.assertIn(action, {"block", "hard_stop"})
        self.assertTrue(
            state_is_active(self.temp_dir),
            "A contract hash mismatch must not allow the run to release",
        )

    def test_each_run_is_isolated_from_other_runs(self) -> None:
        first_dir = self.temp_dir / "run-a"
        second_dir = self.temp_dir / "run-b"
        first_dir.mkdir()
        second_dir.mkdir()

        self.runtime.call("enable", project_dir=first_dir, goal="Run A", enabled=True, max_iterations=8)
        self.runtime.call("enable", project_dir=second_dir, goal="Run B", enabled=True, max_iterations=8)

        first_artifacts = discover_artifacts(first_dir)
        second_artifacts = discover_artifacts(second_dir)

        self.assertNotEqual(
            artifact_run_id(first_artifacts["state"]),
            artifact_run_id(second_artifacts["state"]),
            "Separate runs should not share a run identity",
        )
        self.assertNotEqual(
            artifact_contract_hash(first_artifacts["contract"]),
            artifact_contract_hash(second_artifacts["contract"]),
            "Separate runs should not share a contract hash",
        )

        first_result = self.runtime.call(
            "stop",
            project_dir=first_dir,
            run_id=artifact_run_id(first_artifacts["state"]),
            contract_hash=artifact_contract_hash(first_artifacts["contract"]),
            tasks_complete=True,
            final_gate_passed=True,
        )
        self.assertEqual(normalize_action(first_result), "allow")
        self.assertFalse(state_is_active(first_dir))
        self.assertTrue(
            state_is_active(second_dir),
            "Releasing one run must not clear or pause the other run",
        )

    def test_pause_then_resume_round_trips_the_active_run(self) -> None:
        artifacts = self.enable_run()

        pause_result = self.runtime.call(
            "pause",
            project_dir=self.temp_dir,
            run_id=artifact_run_id(artifacts["state"]),
        )
        self.assertIn(normalize_action(pause_result), {"allow", "noop", "unknown"})

        paused_artifacts = discover_artifacts(self.temp_dir)
        self.assertTrue(
            paused_artifacts["state"]["data"].get("paused") is True,
            "Pause should persist paused=true in the active run state",
        )

        resume_result = self.runtime.call(
            "resume",
            project_dir=self.temp_dir,
            run_id=artifact_run_id(paused_artifacts["state"]),
        )
        self.assertIn(normalize_action(resume_result), {"allow", "noop", "unknown"})

        resumed_artifacts = discover_artifacts(self.temp_dir)
        self.assertFalse(
            resumed_artifacts["state"]["data"].get("paused", False),
            "Resume should clear the paused flag so stop-gate evaluation can continue",
        )

    def test_repeated_failure_signature_escalates_to_hard_stop(self) -> None:
        artifacts = self.enable_run()
        run_id = artifact_run_id(artifacts["state"])
        contract_hash = artifact_contract_hash(artifacts["contract"])

        last_action = "unknown"
        for _ in range(6):
            last_action = self.stop_run(
                run_id=run_id,
                contract_hash=contract_hash,
                tasks_complete=False,
                final_gate_passed=False,
                failure_signature="lint:E999:no-progress",
            )
            if last_action == "hard_stop":
                break

        self.assertEqual(
            last_action,
            "hard_stop",
            "Repeated identical failure signatures should escalate to a hard-stop/manual-intervention state",
        )

    def test_request_enable_binds_directly_when_codex_thread_id_is_available(self) -> None:
        runtime_root = self.temp_dir / "runtime-root"
        runtime = AutonomousLoopRuntime(root=runtime_root)

        with patch.dict(os.environ, {"CODEX_THREAD_ID": "direct-thread-123"}, clear=False):
            result = runtime.request_enable(
                cwd=self.temp_dir,
                objective="Bind directly without stop-hook claim",
            )

        self.assertEqual(result["activation_mode"], "direct-env")
        self.assertEqual(result["session_id"], "direct-thread-123")
        status = runtime.status(self.temp_dir, session_id="direct-thread-123")
        self.assertEqual(len(status["sessions"]), 1)
        self.assertEqual(status["sessions"][0]["state"], "active")


class HookWrapperContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = RuntimeAdapter()
        if not cls.runtime.has_capability("wrap_hook"):
            raise ContractError(
                f"Could not resolve a hook-wrapper capability from {cls.runtime.modules}. "
                f"Expected a callable under {BIN_ROOT} or {PROJECT_ROOT / 'src' / 'autonomous_loop'}."
            )

    def test_wrapper_suppresses_empty_success_noise(self) -> None:
        result = self.runtime.call("wrap_hook", exit_code=0, stdout="", stderr="")
        text = meaningful_text(result).strip()
        self.assertEqual(text, "", "Wrapper should be silent on successful empty hook output")
        self.assertNotIn("no stderr output", text.lower())
        self.assertNotIn("no stdout output", text.lower())


if __name__ == "__main__":
    unittest.main()
