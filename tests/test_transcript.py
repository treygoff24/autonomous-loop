from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

TESTS_ROOT = Path(__file__).resolve().parent
if str(TESTS_ROOT) not in sys.path:
    sys.path.insert(0, str(TESTS_ROOT))

SRC_ROOT = TESTS_ROOT.parent / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from autonomous_loop.transcript import describe_incomplete_plan, load_latest_plan_snapshot


class TranscriptPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="autonomous-loop-transcript-"))
        self.addCleanup(lambda: shutil.rmtree(self.temp_dir, ignore_errors=True))

    def write_transcript(self, *plans: list[dict[str, str]]) -> Path:
        transcript = self.temp_dir / "rollout.jsonl"
        lines = []
        for plan in plans:
            lines.append(
                json.dumps(
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "function_call",
                            "name": "update_plan",
                            "arguments": json.dumps({"plan": plan}),
                        },
                    }
                )
            )
        transcript.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return transcript

    def test_load_latest_plan_snapshot_uses_last_update_plan_call(self) -> None:
        transcript = self.write_transcript(
            [{"step": "First", "status": "in_progress"}],
            [
                {"step": "First", "status": "completed"},
                {"step": "Second", "status": "pending"},
            ],
        )

        snapshot = load_latest_plan_snapshot(str(transcript))

        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertFalse(snapshot.is_complete)
        self.assertEqual([item.step for item in snapshot.incomplete_items], ["Second"])
        self.assertIn("pending: Second", describe_incomplete_plan(snapshot))

    def test_complete_plan_snapshot_has_no_incomplete_items(self) -> None:
        transcript = self.write_transcript(
            [
                {"step": "First", "status": "completed"},
                {"step": "Second", "status": "completed"},
            ]
        )

        snapshot = load_latest_plan_snapshot(str(transcript))

        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertTrue(snapshot.is_complete)
        self.assertEqual(snapshot.incomplete_items, ())


if __name__ == "__main__":
    unittest.main()
