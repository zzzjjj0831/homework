from . import cli_ops, file_ops, web_ops


class ToolRegistry:
    def __init__(self, config=None):
        self.config = config
        self.tools_def = [
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
            {
                "type": "function",
                "function": {
                    "name": "RunCli",
                    "description": "调用本地已安装的命令行程序（CLI），返回标准输出、标准错误和退出码，用于判断执行结果",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": "要执行的程序名称或路径，例如 python、git、ls",
                            },
                            "args": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "传给程序的参数列表，例如 [\"--version\"]",
                            },
                        },
                        "required": ["command"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "fetchWeb",
                    "description": "获取指定网页的主要内容，提取正文并转换为Markdown格式，自动去除导航栏、广告、页脚等无关内容",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "要获取内容的网页URL（仅支持http或https）"}
                        },
                        "required": ["url"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "searchWeb",
                    "description": "通过百度千帆搜索API在互联网上搜索最新信息，返回搜索摘要及参考来源的标题和URL",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "搜索关键词或问题，建议不超过72个字符"}
                        },
                        "required": ["query"],
                    },
                },
            },
        ]

    def get_tools(self):
        return self.tools_def

    def call(self, name: str, args: dict):
        if name == "get_date":
            return file_ops.get_date()
        elif name == "is_leap_year":
            return file_ops.is_leap_year(int(args.get("year") or 0))
        elif name == "get_current_working_directory":
            return file_ops.get_current_working_directory()
        elif name == "list_directory":
            return file_ops.list_directory(args.get("path") or ".")
        elif name == "get_file_type":
            return file_ops.get_file_type(args.get("path") or "")
        elif name == "get_file_content":
            return file_ops.get_file_content(args.get("path") or "")
        elif name == "create_file":
            return file_ops.create_file(
                args.get("dir_path") or ".",
                args.get("file_name") or "new.txt",
                args.get("content") or "",
            )
        elif name == "edit_file":
            return file_ops.edit_file(args.get("path") or "", args.get("content") or "")
        elif name == "create_directory":
            return file_ops.create_directory(args.get("path") or "")
        elif name == "remove_directory":
            return file_ops.remove_directory(args.get("path") or "")
        elif name == "remove_file":
            return file_ops.remove_file(args.get("path") or "")
        elif name == "rename_path":
            return file_ops.rename_path(args.get("old_path") or "", args.get("new_path") or "")
        elif name == "RunCli":
            return cli_ops.run_cli(args.get("command") or "", args.get("args") or [])
        elif name == "fetchWeb":
            return web_ops.fetch_web(args.get("url") or "")
        elif name == "searchWeb":
            api_key = self.config.get_search_api_key() if self.config else ""
            return web_ops.search_web(args.get("query") or "", api_key)
        else:
            import json

            return json.dumps({"error": "unknown tool"}, ensure_ascii=False)
