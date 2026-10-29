import configparser
import json
import os
import shutil
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


def is_leap_year(year: int):
    try:
        if year % 400 == 0:
            is_leap = True
        elif year % 100 == 0:
            is_leap = False
        elif year % 4 == 0:
            is_leap = True
        else:
            is_leap = False
        return json.dumps({"year": year, "isLeapYear": is_leap})
    except Exception as e:
        return json.dumps({"error": str(e)})


def get_current_working_directory():
    try:
        cwd = os.getcwd()
        return json.dumps({"cwd": cwd})
    except Exception as e:
        return json.dumps({"error": str(e)})


def list_directory(path: str = "."):
    try:
        target = Path(path)
        if not target.exists():
            return json.dumps({"error": f"path not exists: {path}"})
        entries = []
        for entry in target.iterdir():
            entries.append(
                {
                    "name": entry.name,
                    "is_dir": entry.is_dir(),
                    "is_file": entry.is_file(),
                    "path": str(entry),
                }
            )
        return json.dumps({"path": str(target.resolve()), "entries": entries})
    except Exception as e:
        return json.dumps({"error": str(e)})


def get_file_type(path: str):
    try:
        target = Path(path)
        if not target.exists():
            return json.dumps({"error": f"path not exists: {path}"})
        if target.is_dir():
            return json.dumps({"path": str(target.resolve()), "type": "directory"})
        if target.is_file():
            return json.dumps({"path": str(target.resolve()), "type": "file"})
        return json.dumps({"path": str(target.resolve()), "type": "other"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def get_file_content(path: str):
    try:
        target = Path(path)
        if not target.exists():
            return json.dumps({"error": f"path not exists: {path}"})
        if not target.is_file():
            return json.dumps({"error": f"not a file: {path}"})
        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeError:
            return json.dumps({"error": "not plain text or unsupported encoding"})
        return json.dumps({"path": str(target.resolve()), "content": content})
    except Exception as e:
        return json.dumps({"error": str(e)})


def create_file(dir_path: str, file_name: str, content: str = ""):
    try:
        dir_target = Path(dir_path)
        dir_target.mkdir(parents=True, exist_ok=True)
        file_target = dir_target / file_name
        file_target.write_text(content, encoding="utf-8")
        return json.dumps({"path": str(file_target.resolve()), "created": True})
    except Exception as e:
        return json.dumps({"error": str(e)})


def edit_file(path: str, content: str):
    try:
        target = Path(path)
        if not target.exists():
            return json.dumps({"error": f"path not exists: {path}"})
        if not target.is_file():
            return json.dumps({"error": f"not a file: {path}"})
        try:
            target.write_text(content, encoding="utf-8")
        except Exception:
            return json.dumps({"error": "failed to write as plain text"})
        return json.dumps({"path": str(target.resolve()), "edited": True})
    except Exception as e:
        return json.dumps({"error": str(e)})


def create_directory(path: str):
    try:
        target = Path(path)
        target.mkdir(parents=True, exist_ok=False)
        return json.dumps({"path": str(target.resolve()), "created": True})
    except FileExistsError:
        return json.dumps({"error": "directory already exists"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def remove_directory(path: str):
    try:
        target = Path(path)
        if not target.exists():
            return json.dumps({"error": f"path not exists: {path}"})
        if not target.is_dir():
            return json.dumps({"error": f"not a directory: {path}"})
        try:
            target.rmdir()
            return json.dumps({"path": str(target.resolve()), "removed": True})
        except OSError:
            return json.dumps({"error": "directory not empty or cannot remove"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def remove_file(path: str):
    try:
        target = Path(path)
        if not target.exists():
            return json.dumps({"error": f"path not exists: {path}"})
        if not target.is_file():
            return json.dumps({"error": f"not a file: {path}"})
        target.unlink()
        return json.dumps({"path": str(target.resolve()), "removed": True})
    except Exception as e:
        return json.dumps({"error": str(e)})


def rename_path(old_path: str, new_path: str):
    try:
        old_target = Path(old_path)
        new_target = Path(new_path)
        if not old_target.exists():
            return json.dumps({"error": f"old path not exists: {old_path}"})
        shutil.move(str(old_target), str(new_target))
        return json.dumps({"old_path": str(old_target.resolve()), "new_path": str(new_target.resolve()), "renamed": True})
    except Exception as e:
        return json.dumps({"error": str(e)})


tools = [
    {
        "type": "function",
        "function": {
            "name": "get_date",
            "description": "获取当前电脑的日期和时间",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "is_leap_year",
            "description": "计算输入的年份是否为闰年",
            "parameters": {
                "type": "object",
                "properties": {"year": {"type": "integer", "description": "要计算的年份"}},
                "required": ["year"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_working_directory",
            "description": "获取当前工作目录",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "列出指定目录下所有文件和子目录",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "目录路径，默认为当前目录"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_file_type",
            "description": "获取指定文件的文件类型",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "文件或目录路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_file_content",
            "description": "获取指定文件的内容（仅支持纯文本格式文件）",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "文件路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_file",
            "description": "根据指定的目录和文件名创建新文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "dir_path": {"type": "string", "description": "目标目录路径"},
                    "file_name": {"type": "string", "description": "文件名"},
                    "content": {"type": "string", "description": "文件内容（可选）"},
                },
                "required": ["dir_path", "file_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "编辑指定文件的内容（仅支持纯文本格式文件）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "content": {"type": "string", "description": "新的文件内容"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_directory",
            "description": "创建新目录",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "目录路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_directory",
            "description": "删除目录（非空）",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "目录路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_file",
            "description": "删除文件",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "文件路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rename_path",
            "description": "重命名文件和目录",
            "parameters": {
                "type": "object",
                "properties": {
                    "old_path": {"type": "string", "description": "原路径"},
                    "new_path": {"type": "string", "description": "新路径"},
                },
                "required": ["old_path", "new_path"],
            },
        },
    },
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
                name = tool_call.function.name
                args = json.loads(tool_call.function.arguments or "{}")
                if name == "get_date":
                    tool_result = get_date()
                elif name == "is_leap_year":
                    tool_result = is_leap_year(int(args.get("year") or 0))
                elif name == "get_current_working_directory":
                    tool_result = get_current_working_directory()
                elif name == "list_directory":
                    tool_result = list_directory(args.get("path") or ".")
                elif name == "get_file_type":
                    tool_result = get_file_type(args.get("path") or "")
                elif name == "get_file_content":
                    tool_result = get_file_content(args.get("path") or "")
                elif name == "create_file":
                    tool_result = create_file(
                        args.get("dir_path") or ".",
                        args.get("file_name") or "new.txt",
                        args.get("content") or "",
                    )
                elif name == "edit_file":
                    tool_result = edit_file(args.get("path") or "", args.get("content") or "")
                elif name == "create_directory":
                    tool_result = create_directory(args.get("path") or "")
                elif name == "remove_directory":
                    tool_result = remove_directory(args.get("path") or "")
                elif name == "remove_file":
                    tool_result = remove_file(args.get("path") or "")
                elif name == "rename_path":
                    tool_result = rename_path(args.get("old_path") or "", args.get("new_path") or "")
                else:
                    tool_result = json.dumps({"error": "unknown tool"})
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
