"""Agent 主循环测试：多轮工具闭环、步数保护、工具错误回填、AGENT.md 注入与会话持久化。

用 FakeClient 注入脚本化的模型响应，不访问真实 LLM。
"""

from __future__ import annotations

import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.agent.agent_core import AgentCore  # noqa: E402
from core.config.settings import Config  # noqa: E402
from tests.fakes import FakeClient, answer_step, tool_step  # noqa: E402


class AgentLoopTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parent / "_tmp" / self._testMethodName
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def make_config(self, ini: str = "") -> Config:
        path = self.root / "config.ini"
        if ini:
            path.write_text(ini, encoding="utf-8")
        return Config(config_path=path)

    def make_agent(self, steps, ini: str = "") -> AgentCore:
        agent = AgentCore(self.make_config(ini))
        agent.client = FakeClient(steps)
        return agent

    # 1) 一轮工具 + 一轮回答：结果必须回填并再次请求
    def test_single_tool_round_feeds_result_back(self):
        agent = self.make_agent(
            [
                tool_step(("call_1", "get_date", "{}")),
                answer_step("今天是 ", "2026-11-12"),
            ]
        )
        output = "".join(agent.run_turn("今天几号"))

        self.assertEqual(output, "今天是 2026-11-12")
        self.assertEqual(len(agent.client.calls), 2)

        messages = agent.client.calls[1]["messages"]
        tool_message = next(m for m in messages if m.get("role") == "tool")
        self.assertEqual(tool_message["tool_call_id"], "call_1")
        self.assertIn('"ok": true', tool_message["content"])
        assistant_with_calls = [
            m for m in messages if m.get("role") == "assistant" and m.get("tool_calls")
        ]
        self.assertEqual(
            assistant_with_calls[0]["tool_calls"][0]["function"]["name"], "get_date"
        )
        # 每一轮都必须带 tools，否则模型无法继续调用工具
        self.assertTrue(all("tools" in call for call in agent.client.calls))

    # 2) 连续两轮工具 + 回答：这是"多轮闭环"的关键判据
    def test_two_tool_rounds_form_a_loop(self):
        agent = self.make_agent(
            [
                tool_step(("c1", "get_current_working_directory", "{}")),
                tool_step(("c2", "list_directory", '{"path": "."}')),
                answer_step("目录已列出"),
            ]
        )
        output = "".join(agent.run_turn("先看 cwd 再列目录"))

        self.assertEqual(output, "目录已列出")
        self.assertEqual(len(agent.client.calls), 3)
        tool_ids = [m["tool_call_id"] for m in agent.history if m.get("role") == "tool"]
        self.assertEqual(tool_ids, ["c1", "c2"])

    # 3) 步数上限保护：不允许无限循环
    def test_max_steps_stops_the_loop(self):
        agent = self.make_agent(
            [
                tool_step(("c1", "get_date", "{}")),
                tool_step(("c2", "get_date", "{}")),
                answer_step("不应走到这里"),
            ],
            ini="[agent]\nmax_steps = 2\n",
        )
        output = "".join(agent.run_turn("一直调用工具"))

        self.assertIn("上限", output)
        self.assertEqual(len(agent.client.calls), 2)
        self.assertEqual(agent.config.get_agent_max_steps(), 2)

    # 4) 工具失败要能让模型看到（结构化错误码回填到 tool 消息）
    def test_tool_error_is_visible_to_model(self):
        agent = self.make_agent(
            [
                tool_step(("c1", "get_file_content", '{"path": "missing.txt"}')),
                answer_step("文件不存在"),
            ]
        )
        "".join(agent.run_turn("读一个不存在的文件"))

        tool_message = next(m for m in agent.history if m.get("role") == "tool")
        self.assertIn("NOT_FOUND", tool_message["content"])
        payload = json.loads(tool_message["content"])
        self.assertFalse(payload["ok"])

    # 5) 参数不是合法 JSON 时也不能崩，返回 BAD_ARGUMENTS
    def test_bad_json_arguments_are_reported(self):
        agent = self.make_agent(
            [tool_step(("c1", "get_date", "{not-json")), answer_step("重试")]
        )
        "".join(agent.run_turn("乱传参数"))

        tool_message = next(m for m in agent.history if m.get("role") == "tool")
        self.assertIn("BAD_ARGUMENTS", tool_message["content"])

    # 6) AGENT.md 兼容命名：配置写 AGENT.md，实际只存在 AGENTS.md 也能读到
    def test_agents_md_fallback_and_injection_once(self):
        (self.root / "AGENTS.md").write_text("规则：回答必须简洁。", encoding="utf-8")
        agent = self.make_agent(
            [answer_step("好"), answer_step("好")],
            ini="[agents]\nfile = AGENT.md\n",
        )

        self.assertTrue(agent.agents_md_injected)
        status = agent.get_agents_status()
        self.assertTrue(status["exists"])
        self.assertTrue(status["resolved_path"].endswith("AGENTS.md"))
        injected = [m for m in agent.history if str(m.get("content", "")).startswith("<!-- AGENTS.md -->")]
        self.assertEqual(len(injected), 1)
        self.assertIn("规则：回答必须简洁。", injected[0]["content"])

        "".join(agent.run_turn("第一问"))
        "".join(agent.run_turn("第二问"))
        injected = [m for m in agent.history if str(m.get("content", "")).startswith("<!-- AGENTS.md -->")]
        self.assertEqual(len(injected), 1, "AGENT 文件只应注入一次")

    # 7) 超长 AGENT.md 需要截断，避免一次注入撑爆上下文
    def test_agents_md_is_truncated(self):
        (self.root / "AGENT.md").write_text("x" * 800, encoding="utf-8")
        agent = AgentCore(self.make_config("[agents]\nmax_chars = 200\n"))

        self.assertTrue(agent.agents_md_injected)
        self.assertTrue(agent.agents_truncated)
        content = agent.history[1]["content"]
        self.assertIn("已截断", content)
        self.assertLess(len(content), 800)

    # 8) 没有规则文件时静默跳过
    def test_missing_agents_file_is_silent(self):
        agent = self.make_agent([answer_step("ok")])
        self.assertFalse(agent.agents_md_injected)
        status = agent.get_agents_status()
        self.assertFalse(status["exists"])
        self.assertIsNone(status["resolved_path"])

    # 9) 会话持久化：一轮问答后可列出并恢复
    def test_session_is_persisted_and_listable(self):
        agent = self.make_agent([answer_step("你好呀")])
        "".join(agent.run_turn("打个招呼"))

        sessions = agent.list_sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["id"], agent.session_id)

        reloaded = AgentCore(self.make_config())
        data = reloaded.load_session(sessions[0]["id"])
        self.assertGreaterEqual(data["message_count"], 3)
        self.assertIn("打个招呼", json.dumps(data["messages"], ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
