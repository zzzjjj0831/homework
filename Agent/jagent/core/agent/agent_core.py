import json
from typing import List, Dict, Any

from openai import OpenAI

from core.config.settings import Config
from core.tools.registry import ToolRegistry


class AgentCore:
    def __init__(self):
        self.config = Config()
        self.client: OpenAI = self.config.get_client()
        self.model = self.config.get_model()
        self.tools_registry = ToolRegistry(self.config)
        self.history: List[Dict[str, Any]] = []

    def get_tools(self):
        return self.tools_registry.get_tools()

    def run_turn(self, user_message: str):
        self.history.append({"role": "user", "content": user_message})
        response = self.client.chat.completions.create(
            model=self.model,
            messages=self.history,
            tools=self.get_tools(),
            tool_choice="auto",
        )
        message = response.choices[0].message
        if message.tool_calls:
            self.history.append(message)
            for tool_call in message.tool_calls:
                name = tool_call.function.name
                try:
                    args = json.loads(tool_call.function.arguments or "{}")
                except Exception:
                    args = {}
                tool_result = self.tools_registry.call(name, args)
                self.history.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": tool_result,
                    }
                )
            stream = self.client.chat.completions.create(
                model=self.model,
                messages=self.history,
                stream=True,
            )
            reply = ""
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    reply += delta
                    yield delta
            self.history.append({"role": "assistant", "content": reply})
        else:
            reply = message.content or ""
            self.history.append({"role": "assistant", "content": reply})
            yield reply
