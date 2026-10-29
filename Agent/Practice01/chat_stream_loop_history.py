import configparser
from pathlib import Path

from openai import OpenAI

config = configparser.ConfigParser()
config.read(Path(__file__).with_name("config.ini"), encoding="utf-8")
llm = config["llm"]

client = OpenAI(base_url=llm["base_url"], api_key=llm["api_key"])

history = []
print("循环聊天已启动，按 Ctrl+C 退出（历史对话已保留）")
try:
    while True:
        prompt = input("\n请输入问题: ")
        history.append({"role": "user", "content": prompt})
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
except KeyboardInterrupt:
    print("\n已退出")
