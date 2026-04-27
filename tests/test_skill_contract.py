from __future__ import annotations

import unittest
from pathlib import Path

from support import PROJECT_ROOT


SKILL_PATHS = (
    PROJECT_ROOT / "skills" / "autonomous-loop" / "SKILL.md",
    PROJECT_ROOT / "templates" / ".agents" / "skills" / "autonomous-loop" / "SKILL.md",
    PROJECT_ROOT
    / "src"
    / "autonomous_loop"
    / "resources"
    / "templates"
    / ".agents"
    / "skills"
    / "autonomous-loop"
    / "SKILL.md",
)

OPENAI_YAML_PATHS = tuple(path.parent / "agents" / "openai.yaml" for path in SKILL_PATHS)


class AutonomousLoopSkillContractTests(unittest.TestCase):
    def test_skill_frontmatter_has_trigger_language(self) -> None:
        for path in SKILL_PATHS:
            with self.subTest(path=path):
                text = path.read_text(encoding="utf-8")
                self.assertTrue(text.startswith("---\n"))
                self.assertIn("name: autonomous-loop", text)
                self.assertIn("/autonomous-loop", text)
                self.assertIn("use autonomous-loop", text)
                self.assertIn("update_plan", text)
                self.assertIn("quality gates pass", text)

    def test_skill_body_preserves_plan_enforcement_contract(self) -> None:
        required_phrases = (
            "Non-negotiable plan discipline",
            "The latest Codex task plan is an enforcement input",
            "Call `update_plan` with a concrete task list",
            "Keep exactly one task `in_progress`",
            "Stop hook reads transcript `update_plan` calls",
            "autonomous-loop doctor --cwd \"$PWD\"",
            ".codex/autoloop.project.json",
            "agent-instructions --cwd \"$PWD\"",
            "Fresh context recovery",
            "claim_token",
        )
        for path in SKILL_PATHS:
            with self.subTest(path=path):
                text = path.read_text(encoding="utf-8")
                for phrase in required_phrases:
                    self.assertIn(phrase, text)

    def test_packaged_skill_copies_stay_in_sync(self) -> None:
        canonical = SKILL_PATHS[0].read_text(encoding="utf-8")
        for path in SKILL_PATHS[1:]:
            with self.subTest(path=path):
                self.assertEqual(path.read_text(encoding="utf-8"), canonical)

    def test_openai_yaml_metadata_exists_for_every_skill_copy(self) -> None:
        required_phrases = (
            "display_name: Autonomous Loop",
            "short_description: Keep Codex working until plan items and gates pass.",
            "default_prompt: Use /autonomous-loop for this task.",
        )
        for path in OPENAI_YAML_PATHS:
            with self.subTest(path=path):
                text = path.read_text(encoding="utf-8")
                for phrase in required_phrases:
                    self.assertIn(phrase, text)

    def test_openai_yaml_copies_stay_in_sync(self) -> None:
        canonical = OPENAI_YAML_PATHS[0].read_text(encoding="utf-8")
        for path in OPENAI_YAML_PATHS[1:]:
            with self.subTest(path=path):
                self.assertEqual(path.read_text(encoding="utf-8"), canonical)


if __name__ == "__main__":
    unittest.main()
