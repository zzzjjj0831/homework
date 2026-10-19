import configparser
from pathlib import Path

from openai import OpenAI

config = configparser.ConfigParser()
config.read(Path(__file__).with_name("config.ini"), encoding="utf-8")
llm = config["llm"]

client = OpenAI(base_url=llm["base_url"], api_key=llm["api_key"])

prompt = input("请输入问题: ")
resp = client.chat.completions.create(
    model=llm["model"],
    messages=[{"role": "user", "content": prompt}],
)
print(resp.choices[0].message.content)
