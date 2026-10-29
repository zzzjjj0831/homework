import configparser
from pathlib import Path

from openai import OpenAI


class Config:
    def __init__(self, config_path: str | None = None):
        if config_path is None:
            config_path = Path(__file__).resolve().parents[2] / "config.ini"
        self.config = configparser.ConfigParser()
        self.config.read(config_path, encoding="utf-8")
        self.llm = self.config["llm"]

    def get_client(self) -> OpenAI:
        return OpenAI(base_url=self.llm["base_url"], api_key=self.llm["api_key"])

    def get_model(self) -> str:
        return self.llm["model"]

    def get_search_api_key(self) -> str:
        return self.config.get("search", "baidu_qianfan_api_key", fallback="").strip()
