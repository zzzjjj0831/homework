"""文件/目录工具与注册表的单元测试（真实副作用 + 边界 + 结构化错误）。"""

from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.tools import file_ops  # noqa: E402
from core.tools.paths import PathPolicy  # noqa: E402
from core.tools.registry import ToolRegistry  # noqa: E402


class StubConfig:
    def __init__(self, root: Path):
        self.root = root

    def get_workspace_root(self):
        return self.root

    def get_allow_outside_workspace(self):
        return False


class Base(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / "_tmp" / self._testMethodName
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        self.policy = PathPolicy(self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    @staticmethod
    def parse(text: str):
        return json.loads(text)


class TimeToolTest(Base):
    def test_get_date_returns_date_and_time(self):
        data = self.parse(file_ops.get_date())
        self.assertTrue(data["ok"])
        self.assertRegex(data["date"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertRegex(data["time"], r"^\d{2}:\d{2}:\d{2}$")
        self.assertIn("T", data["iso"])
        self.assertIn(data["weekday"], file_ops.WEEKDAYS)

    def test_leap_year_rules(self):
        for year, expected in ((2024, True), (2023, False), (1900, False), (2000, True), (0, True)):
            with self.subTest(year=year):
                data = self.parse(file_ops.is_leap_year(year))
                self.assertTrue(data["ok"])
                self.assertEqual(data["isLeapYear"], expected)

    def test_leap_year_rejects_non_integer(self):
        data = self.parse(file_ops.is_leap_year("20x4"))
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"]["code"], "INVALID_ARGUMENT")
        data = self.parse(file_ops.is_leap_year(100000))
        self.assertEqual(data["error"]["code"], "INVALID_ARGUMENT")


class FileOpsTest(Base):
    def test_create_read_append_cycle(self):
        created = self.parse(
            file_ops.create_file("notes", "a.txt", "hello", policy=self.policy)
        )
        self.assertTrue(created["ok"])
        target = self.root / "notes" / "a.txt"
        self.assertEqual(target.read_text(encoding="utf-8"), "hello")

        overwrite = self.parse(
            file_ops.create_file("notes", "a.txt", "again", policy=self.policy)
        )
        self.assertEqual(overwrite["error"]["code"], "FILE_EXISTS")
        self.assertEqual(target.read_text(encoding="utf-8"), "hello")

        replaced = self.parse(
            file_ops.create_file("notes", "a.txt", "again", overwrite=True, policy=self.policy)
        )
        self.assertTrue(replaced["ok"])

        appended = self.parse(
            file_ops.edit_file("notes/a.txt", "-more", mode="append", policy=self.policy)
        )
        self.assertTrue(appended["ok"])
        self.assertEqual(target.read_text(encoding="utf-8"), "again-more")

        content = self.parse(file_ops.get_file_content("notes/a.txt", policy=self.policy))
        self.assertTrue(content["ok"])
        self.assertEqual(content["content"], "again-more")

    def test_read_supports_paging(self):
        self.parse(file_ops.create_file(".", "big.txt", "x" * 5000, policy=self.policy))
        first = self.parse(
            file_ops.get_file_content("big.txt", max_chars=200, policy=self.policy)
        )
        self.assertTrue(first["truncated"])
        self.assertEqual(first["next_offset"], 200)
        second = self.parse(
            file_ops.get_file_content(
                "big.txt", offset=first["next_offset"], max_chars=200, policy=self.policy
            )
        )
        self.assertEqual(second["range"], [200, 400])

    def test_list_directory_and_file_type(self):
        self.parse(file_ops.create_file(".", "x.md", "a", policy=self.policy))
        self.parse(file_ops.create_directory("sub", policy=self.policy))
        listing = self.parse(file_ops.list_directory(".", policy=self.policy))
        names = {entry["name"]: entry["type"] for entry in listing["entries"]}
        self.assertEqual(names, {"x.md": "file", "sub": "dir"})

        kind = self.parse(file_ops.get_file_type("x.md", policy=self.policy))
        self.assertEqual(kind["type"], "file")
        self.assertEqual(kind["extension"], ".md")

    def test_destructive_operations_require_confirm(self):
        self.parse(file_ops.create_file(".", "y.txt", "a", policy=self.policy))
        denied = self.parse(file_ops.remove_file("y.txt", policy=self.policy))
        self.assertEqual(denied["error"]["code"], "CONFIRM_REQUIRED")
        self.assertTrue((self.root / "y.txt").exists())

        removed = self.parse(file_ops.remove_file("y.txt", confirm=True, policy=self.policy))
        self.assertTrue(removed["ok"])
        self.assertFalse((self.root / "y.txt").exists())

    def test_remove_directory_non_empty_requires_recursive(self):
        self.parse(file_ops.create_file("d", "a.txt", "a", policy=self.policy))
        flat = self.parse(
            file_ops.remove_directory("d", confirm=True, policy=self.policy)
        )
        self.assertEqual(flat["error"]["code"], "DIRECTORY_NOT_EMPTY")
        recursive = self.parse(
            file_ops.remove_directory("d", recursive=True, confirm=True, policy=self.policy)
        )
        self.assertTrue(recursive["ok"])
        self.assertFalse((self.root / "d").exists())

    def test_rename_reports_conflicts(self):
        self.parse(file_ops.create_file(".", "a.txt", "a", policy=self.policy))
        self.parse(file_ops.create_file(".", "b.txt", "b", policy=self.policy))
        conflict = self.parse(
            file_ops.rename_path("a.txt", "b.txt", confirm=True, policy=self.policy)
        )
        self.assertEqual(conflict["error"]["code"], "DEST_EXISTS")
        moved = self.parse(
            file_ops.rename_path("a.txt", "sub/c.txt", confirm=True, policy=self.policy)
        )
        self.assertTrue(moved["ok"])
        self.assertTrue((self.root / "sub" / "c.txt").exists())

    def test_path_outside_workspace_is_rejected(self):
        outside = Path("C:/Windows/win.ini") if Path("C:/").exists() else Path("/etc/hosts")
        data = self.parse(file_ops.get_file_content(str(outside), policy=self.policy))
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"]["code"], "OUTSIDE_WORKSPACE")

    def test_root_itself_is_protected(self):
        data = self.parse(
            file_ops.remove_directory(".", recursive=True, confirm=True, policy=self.policy)
        )
        self.assertEqual(data["error"]["code"], "FORBIDDEN_TARGET")
        self.assertTrue(self.root.exists())


class RegistryTest(Base):
    def setUp(self):
        super().setUp()
        self.registry = ToolRegistry(StubConfig(self.root))

    def test_create_file_goes_through_registry_and_stays_in_workspace(self):
        result = json.loads(
            self.registry.call(
                "create_file", {"dir_path": ".", "file_name": "r.txt", "content": "hi"}
            )
        )
        self.assertTrue(result["ok"])
        self.assertTrue((self.root / "r.txt").is_file())

    def test_unknown_tool_returns_code(self):
        result = json.loads(self.registry.call("nope", {}))
        self.assertEqual(result["error"]["code"], "UNKNOWN_TOOL")

    def test_tool_exception_is_caught(self):
        # year 传 None 会走 INVALID_ARGUMENT，而不是抛异常打断主循环
        result = json.loads(self.registry.call("is_leap_year", {"year": None}))
        self.assertFalse(result["ok"])

    def test_schema_declares_constraints(self):
        tools = {tool["function"]["name"]: tool for tool in self.registry.get_tools()}
        remove = tools["remove_file"]["function"]["parameters"]["properties"]
        self.assertEqual(remove["confirm"]["type"], "boolean")
        self.assertIn("enum", tools["edit_file"]["function"]["parameters"]["properties"]["mode"])
        self.assertEqual(
            tools["get_file_content"]["function"]["parameters"]["properties"]["max_chars"]["maximum"],
            200000,
        )
        self.assertIn("required", tools["get_file_type"]["function"]["parameters"])
        self.assertEqual(tools["get_file_type"]["function"]["parameters"]["required"], ["path"])


if __name__ == "__main__":
    unittest.main()
