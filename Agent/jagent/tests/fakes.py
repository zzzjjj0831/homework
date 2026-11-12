"""测试用的假 OpenAI 客户端：按脚本返回流式 chunk，不访问网络。

每个 step 是一串 chunk：正文用 chunk(content=...)，工具调用用
chunk(tool_calls=[tool_delta(index, call_id, name, arguments)])。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, List


def _delta(content: str | None = None, tool_calls: List[Any] | None = None):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def chunk(content: str | None = None, tool_calls: List[Any] | None = None):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=_delta(content, tool_calls))], usage=None
    )


def tool_delta(index: int = 0, call_id: str | None = None, name: str | None = None, arguments: str | None = None):
    return SimpleNamespace(
        index=index,
        id=call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def answer_step(*parts: str) -> List[Any]:
    return [chunk(content=part) for part in parts]


def tool_step(*calls) -> List[Any]:
    """calls: (call_id, tool_name, arguments_json)"""
    chunks: List[Any] = []
    for index, (call_id, name, arguments) in enumerate(calls):
        chunks.append(chunk(tool_calls=[tool_delta(index=index, call_id=call_id, name=name)]))
        chunks.append(chunk(tool_calls=[tool_delta(index=index, arguments=arguments)]))
    return chunks


class FakeCompletions:
    def __init__(self, steps):
        self.steps = [list(step) for step in steps]
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self.steps:
            raise AssertionError("模型被多调用了一次：脚本已用尽")
        return iter(self.steps.pop(0))


class FakeClient:
    def __init__(self, steps):
        self.completions = FakeCompletions(steps)
        self.chat = SimpleNamespace(completions=self.completions)

    @property
    def calls(self):
        return self.completions.calls
