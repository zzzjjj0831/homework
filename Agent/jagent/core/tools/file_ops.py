import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


class ToolError(Exception):
    pass


def get_date() -> str:
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
        return json.dumps({"datetime": output}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def is_leap_year(year: int) -> str:
    try:
        if year % 400 == 0:
            is_leap = True
        elif year % 100 == 0:
            is_leap = False
        elif year % 4 == 0:
            is_leap = True
        else:
            is_leap = False
        return json.dumps({"year": year, "isLeapYear": is_leap}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def get_current_working_directory() -> str:
    try:
        cwd = os.getcwd()
        return json.dumps({"cwd": cwd}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def list_directory(path: str = ".") -> str:
    try:
        target = Path(path)
        if not target.exists():
            return json.dumps({"error": f"path not exists: {path}"}, ensure_ascii=False)
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
        return json.dumps({"path": str(target.resolve()), "entries": entries}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def get_file_type(path: str) -> str:
    try:
        target = Path(path)
        if not target.exists():
            return json.dumps({"error": f"path not exists: {path}"}, ensure_ascii=False)
        if target.is_dir():
            return json.dumps({"path": str(target.resolve()), "type": "directory"}, ensure_ascii=False)
        if target.is_file():
            return json.dumps({"path": str(target.resolve()), "type": "file"}, ensure_ascii=False)
        return json.dumps({"path": str(target.resolve()), "type": "other"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def get_file_content(path: str) -> str:
    try:
        target = Path(path)
        if not target.exists():
            return json.dumps({"error": f"path not exists: {path}"}, ensure_ascii=False)
        if not target.is_file():
            return json.dumps({"error": f"not a file: {path}"}, ensure_ascii=False)
        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeError:
            return json.dumps({"error": "not plain text or unsupported encoding"}, ensure_ascii=False)
        return json.dumps({"path": str(target.resolve()), "content": content}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def create_file(dir_path: str, file_name: str, content: str = "") -> str:
    try:
        dir_target = Path(dir_path)
        dir_target.mkdir(parents=True, exist_ok=True)
        file_target = dir_target / file_name
        file_target.write_text(content, encoding="utf-8")
        return json.dumps({"path": str(file_target.resolve()), "created": True}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def edit_file(path: str, content: str) -> str:
    try:
        target = Path(path)
        if not target.exists():
            return json.dumps({"error": f"path not exists: {path}"}, ensure_ascii=False)
        if not target.is_file():
            return json.dumps({"error": f"not a file: {path}"}, ensure_ascii=False)
        try:
            target.write_text(content, encoding="utf-8")
        except Exception:
            return json.dumps({"error": "failed to write as plain text"}, ensure_ascii=False)
        return json.dumps({"path": str(target.resolve()), "edited": True}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def create_directory(path: str) -> str:
    try:
        target = Path(path)
        target.mkdir(parents=True, exist_ok=False)
        return json.dumps({"path": str(target.resolve()), "created": True}, ensure_ascii=False)
    except FileExistsError:
        return json.dumps({"error": "directory already exists"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def remove_directory(path: str) -> str:
    try:
        target = Path(path)
        if not target.exists():
            return json.dumps({"error": f"path not exists: {path}"}, ensure_ascii=False)
        if not target.is_dir():
            return json.dumps({"error": f"not a directory: {path}"}, ensure_ascii=False)
        try:
            target.rmdir()
            return json.dumps({"path": str(target.resolve()), "removed": True}, ensure_ascii=False)
        except OSError:
            return json.dumps({"error": "directory not empty or cannot remove"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def remove_file(path: str) -> str:
    try:
        target = Path(path)
        if not target.exists():
            return json.dumps({"error": f"path not exists: {path}"}, ensure_ascii=False)
        if not target.is_file():
            return json.dumps({"error": f"not a file: {path}"}, ensure_ascii=False)
        target.unlink()
        return json.dumps({"path": str(target.resolve()), "removed": True}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def rename_path(old_path: str, new_path: str) -> str:
    try:
        old_target = Path(old_path)
        new_target = Path(new_path)
        if not old_target.exists():
            return json.dumps({"error": f"old path not exists: {old_path}"}, ensure_ascii=False)
        shutil.move(str(old_target), str(new_target))
        return json.dumps(
            {"old_path": str(old_target.resolve()), "new_path": str(new_target.resolve()), "renamed": True},
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
