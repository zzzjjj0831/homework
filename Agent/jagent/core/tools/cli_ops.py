import json
import shlex
import shutil
import subprocess


DEFAULT_TIMEOUT = 30
MAX_OUTPUT_CHARS = 4000


def _decode_output(data):
    if not data:
        return ""
    if isinstance(data, str):
        return data
    for encoding in ("utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", errors="replace")


def _truncate(text, limit=MAX_OUTPUT_CHARS):
    if len(text) <= limit:
        return text, False, len(text)
    omitted = len(text) - limit
    return (
        f"{text[:limit]}\n...[输出已截断：共 {len(text)} 字符，省略后续 {omitted} 字符]",
        True,
        len(text),
    )


def _normalize_args(args):
    if args is None:
        return []
    if isinstance(args, str):
        return shlex.split(args)
    if isinstance(args, (list, tuple)):
        return [str(arg) for arg in args]
    raise ValueError("args 必须是字符串列表")


def run_cli(command: str, args=None, timeout: int = DEFAULT_TIMEOUT) -> str:
    command = (command or "").strip()
    if not command:
        return json.dumps({"error": "command 不能为空"}, ensure_ascii=False)

    try:
        arg_list = _normalize_args(args)
    except ValueError as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)

    try:
        timeout = max(1, min(int(timeout), 300))
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT

    program = shutil.which(command)
    if not program:
        return json.dumps(
            {"command": command, "args": arg_list, "error": f"未找到命令：{command}"},
            ensure_ascii=False,
        )

    try:
        result = subprocess.run(
            [program, *arg_list],
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        stdout, stdout_truncated, stdout_length = _truncate(_decode_output(e.stdout))
        stderr, stderr_truncated, stderr_length = _truncate(_decode_output(e.stderr))
        return json.dumps(
            {
                "command": command,
                "args": arg_list,
                "exit_code": None,
                "timed_out": True,
                "timeout_seconds": timeout,
                "stdout": stdout,
                "stderr": stderr,
                "stdout_length": stdout_length,
                "stderr_length": stderr_length,
                "stdout_truncated": stdout_truncated,
                "stderr_truncated": stderr_truncated,
                "error": f"命令执行超时（超过 {timeout} 秒），进程已被终止",
            },
            ensure_ascii=False,
        )
    except OSError as e:
        return json.dumps(
            {"command": command, "args": arg_list, "error": f"命令启动失败：{e}"},
            ensure_ascii=False,
        )

    stdout, stdout_truncated, stdout_length = _truncate(_decode_output(result.stdout))
    stderr, stderr_truncated, stderr_length = _truncate(_decode_output(result.stderr))

    return json.dumps(
        {
            "command": command,
            "args": arg_list,
            "exit_code": result.returncode,
            "timed_out": False,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_length": stdout_length,
            "stderr_length": stderr_length,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
        },
        ensure_ascii=False,
    )
