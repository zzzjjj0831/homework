import configparser
import json
import subprocess
from pathlib import Path

from openai import OpenAI

config = configparser.ConfigParser()
config.read(Path(__file__).with_name("config.ini"), encoding="utf-8")
llm = config["llm"]

client = OpenAI(base_url=llm["base_url"], api_key=llm["api_key"])


def get_date():
    try:
        result = subprocess.run(
            ["date"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=True,
            text=True,
            check=False,
        )
        output = result.stdout.strip() or result.stderr.strip()
        return json.dumps({"datetime": output})
    except Exception as e:
        return json.dumps({"error": str(e)})


tools = [
    {
        "type": "function",
        "function": {
            "name": "get_date",
            "description": "获取当前电脑的日期和时间",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    }
]

history = []
print("循环聊天已启动，按 Ctrl+C 退出（历史对话已保留）")
try:
    while True:
        prompt = input("\n请输入问题: ")
        history.append({"role": "user", "content": prompt})
        response = client.chat.completions.create(
            model=llm["model"],
            messages=history,
            tools=tools,
            tool_choice="auto",
        )
        message = response.choices[0].message
        if message.tool_calls:
            history.append(message)
            for tool_call in message.tool_calls:
                if tool_call.function.name == "get_date":
                    tool_result = get_date()
                    history.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": tool_result,
                        }
                    )
            stream = client.chat.completions.create(
                model=llm["model"],
                messages=history,
                stream=True,
            )
            reply = ""
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    reply += delta
                    print(delta, end="", flush=True)
            history.append({"role": "assistant", "content": reply})
            print()
        else:
            reply = message.content or ""
            history.append({"role": "assistant", "content": reply})
            print(reply)
except KeyboardInterrupt:
    print("\n已退出")
