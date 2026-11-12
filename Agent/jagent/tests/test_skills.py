"""技能机制的单元测试：创建落盘/命名校验/拒绝覆盖/按需加载/路径限制/截断。"""

from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.skills.manager import MAX_SKILL_CONTENT_CHARS, SkillManager  # noqa: E402


class SkillTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / "_tmp" / self._testMethodName
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        self.skills_dir = self.root / ".agents" / "skills"
        self.manager = SkillManager(project_root=self.root, skills_dir=self.skills_dir)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    @staticmethod
    def parse(text: str):
        return json.loads(text)

    def create(self, name="demo-skill", body="# Demo\n\n步骤一。\n"):
        return self.parse(self.manager.create_skill(name, body))

    def test_create_writes_frontmatter_and_is_discovered(self):
        result = self.create()
        self.assertTrue(result["ok"])
        skill_file = self.skills_dir / "demo-skill" / "SKILL.md"
        text = skill_file.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        self.assertIn("name: demo-skill", text)
        self.assertIn("description:", text)

        self.assertEqual([skill.name for skill in self.manager.get_skills()], ["demo-skill"])
        self.assertTrue(self.manager.get_skills()[0].description)

    def test_duplicate_is_rejected_without_overwrite(self):
        self.assertTrue(self.create()["ok"])
        original = (self.skills_dir / "demo-skill" / "SKILL.md").read_text(encoding="utf-8")
        second = self.create(body="# 覆盖\n\n新内容\n")
        self.assertFalse(second["ok"])
        self.assertEqual(second["error"]["code"], "SKILL_EXISTS")
        self.assertEqual(
            (self.skills_dir / "demo-skill" / "SKILL.md").read_text(encoding="utf-8"),
            original,
        )

    def test_unsafe_names_are_rejected(self):
        for bad in ("../escape", "a/b", "  ", "!!!"):
            with self.subTest(name=bad):
                result = self.parse(self.manager.create_skill(bad, "# x\n\nbody\n"))
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")
        self.assertFalse((self.root.parent / "escape").exists())

    def test_names_are_normalized_to_kebab_case(self):
        result = self.parse(self.manager.create_skill("Has Space", "# x\n\nbody\n"))
        self.assertTrue(result["ok"])
        self.assertEqual(result["name"], "has-space")
        self.assertTrue((self.skills_dir / "has-space" / "SKILL.md").is_file())

    def test_empty_body_is_rejected(self):
        result = self.parse(self.manager.create_skill("empty-skill", "   "))
        self.assertFalse(result["ok"])

    def test_load_returns_content_and_truncates(self):
        big = "# Big\n\n" + ("x" * (MAX_SKILL_CONTENT_CHARS + 500))
        self.assertTrue(self.create("big-skill", big)["ok"])
        loaded = self.parse(self.manager.load_skill("big-skill"))
        self.assertTrue(loaded["ok"])
        self.assertTrue(loaded["truncated"])
        self.assertLessEqual(len(loaded["content"]), MAX_SKILL_CONTENT_CHARS + 120)

    def test_load_attachment_is_confined_to_skill_dir(self):
        self.assertTrue(self.create()["ok"])
        (self.skills_dir / "demo-skill" / "ref.md").write_text("ref", encoding="utf-8")
        inside = self.parse(self.manager.load_skill("demo-skill", "ref.md"))
        self.assertTrue(inside["ok"])
        self.assertEqual(inside["relative_path"], "ref.md")

        (self.root / "secret.md").write_text("secret", encoding="utf-8")
        outside = self.parse(self.manager.load_skill("demo-skill", "../../secret.md"))
        self.assertFalse(outside["ok"])
        self.assertIn(outside["error"]["code"], {"OUTSIDE_SKILL_DIR", "NOT_FOUND"})

    def test_unknown_skill_reports_available(self):
        result = self.parse(self.manager.load_skill("missing"))
        self.assertEqual(result["error"]["code"], "SKILL_NOT_FOUND")
        self.assertEqual(result["details"]["available"], [])


if __name__ == "__main__":
    unittest.main()
