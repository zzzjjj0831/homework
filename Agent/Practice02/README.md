# Agent/Practice02 README

## 文件说明
- `config.ini` - LLM 配置
- `chat_stream_loop_history_tool.py` - 带 get_date 工具的流式循环聊天
- `main-stream-tool-getDate-leapYear.py` - 带 get_date、is_leap_year 工具的流式循环聊天
- `main-stream-tool-file-ops.py` - 带日期、闰年、本地文件操作工具的流式循环聊天（保留历史对话）
- `main-stream-tool-file-operations-architecture.mmd` - 代码架构图（Mermaid）

## 功能
### 工具列表
- `get_date()` - 通过 `date` 命令获取当前日期和时间
- `is_leap_year(year)` - Python 判断闰年
- `get_current_working_directory()` - 获取当前工作目录
- `list_directory(path='.')` - 列出目录内容
- `get_file_type(path)` - 获取文件/目录类型
- `get_file_content(path)` - 获取纯文本文件内容
- `create_file(dir_path, file_name, content='')` - 创建新文件
- `edit_file(path, content)` - 编辑纯文本文件内容
- `create_directory(path)` - 创建新目录
- `remove_directory(path)` - 删除空目录
- `remove_file(path)` - 删除文件
- `rename_path(old_path, new_path)` - 重命名文件或目录

## 架构图
见 `main-stream-tool-file-operations-architecture.mmd`

## 使用方式
1. 配置 `config.ini`
2. 运行 `python main-stream-tool-file-ops.py`
3. 按提示输入问题，可触发上述工具调用
4. 按 Ctrl+C 退出
