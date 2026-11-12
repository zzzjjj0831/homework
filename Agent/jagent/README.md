# jagent · 本地大模型终端 Agent

基于 Textual 的 TUI Agent：多轮工具调用、技能（Agent Skills）、MCP 客户端、会话持久化、
上下文压缩与归档检索、AGENT.md 长期规则注入。

```
tui/app.py ──► core/agent/agent_core.py ──► core/tools/registry.py ──► tools/{file,cli,web}_ops.py
   │                    │                          │
   │                    ├─► core/skills/manager.py（技能发现/创建/按需加载）
   │                    ├─► core/mcp/manager.py（stdio + streamable-http 客户端）
   │                    ├─► core/session/manager.py（JSONL 会话事件流）
   │                    └─► core/context/manager.py（压缩归档 + 全文检索）
   └─► core/config/settings.py（config.ini）+ core/logging_setup.py（结构化日志）
```

## 快速开始

```bash
pip install -r requirements.txt      # textual / openai / trafilatura / pyyaml / mcp / httpx / pydantic
python main.py                       # 首次运行生成 config.ini，改完 [llm] 后重启
```

启动后可用的斜杠命令：

| 命令 | 作用 |
| --- | --- |
| `/help` | 命令与快捷键 |
| `/new` | 新建会话（自动保存当前会话） |
| `/resume` | 列出历史会话并恢复（标题/时间/条数/预览） |
| `/save` | 立即保存当前会话 |
| `/compact` | 压缩上下文（归档原文 + 生成摘要，可 `recallContext` 检索） |
| `/context` | 上下文占用、会话编号、token 来源 |
| `/tools` | 当前全部可调用工具（含 MCP 注入的） |
| `/mcp` | MCP 服务器连接状态与失败原因 |
| `/agents` | AGENT.md 是否注入、来源文件、是否截断 |
| `/model` | 当前模型与关键配置 |
| `/clear` `/quit` | 清屏 / 保存并退出（`Ctrl+Q` 同样保存退出） |

## 工具契约

所有工具都声明在 `core/tools/registry.py`，参数带类型/范围/枚举；返回统一为 JSON：
成功 `{"ok": true, ...}`，失败 `{"ok": false, "error": {"code", "message", "details"}}`。

| 类别 | 工具 | 关键行为 |
| --- | --- | --- |
| 时间 | `get_date` | 本地时区当前时间，返回 `iso/date/time/weekday/timezone`，不依赖 shell |
| 时间 | `is_leap_year` | 4/100/400 规则，年份范围校验 |
| 文件 | `get_current_working_directory` / `list_directory` | 真实 cwd；目录项含类型与大小 |
| 文件 | `get_file_type` / `get_file_content` | 文件/目录/链接判定；文本分段读取（`offset`/`max_chars`/`next_offset`） |
| 文件 | `create_file` / `edit_file` | 真实落盘；默认拒绝覆盖（`overwrite=true` 才覆盖）；`append` 追加 |
| 文件 | `create_directory` / `remove_directory` / `remove_file` / `rename_path` | 真实建/删/移；删除与重命名需 `confirm=true`，递归删除需 `recursive=true` |
| 技能 | `loadSkill` / `createSkill` | 目录 + YAML frontmatter 的 SKILL.md；命名规范化、拒绝覆盖、附件限制在技能目录内、内容截断 |
| 终端 | `RunCli` | 超时、输出截断、退出码与 stderr 一并返回 |
| 网络 | `fetchWeb` / `searchWeb` | curl + trafilatura 提取正文；千帆搜索 API，缺 Key 返回 `CONFIG_MISSING` |
| 上下文 | `recallContext` | 检索 `.agents/context/*.jsonl` 归档原文 |
| 外部 | `server__tool` | MCP 工具按「服务器名__工具名」注入，来源可区分 |

## 主循环（多轮闭环）

`core/agent/agent_core.py::run_turn` 每次用户输入都会：

1. 流式请求模型（`tools` + `tool_choice=auto`），边收边把正文推给 TUI；
2. 若该轮产生 `tool_calls`：本地执行 → 把结果以 `role=tool` + `tool_call_id` 回填 → 回到第 1 步；
3. 直到模型不再要工具（给出最终答复）或达到 `[agent] max_steps`（默认 8）；
4. 触顶时明确提示"已达上限"，不会静默截断；工具错误（`error.code`）同样回填给模型，由模型决定补救。

## AGENT.md 长期规则

- 启动时按 `[agents] file` → `candidates`（默认 `AGENT.md,AGENTS.md,.agents/AGENT.md`）找到第一个存在的文件；
- 作为 **system 消息只注入一次**，带 `<!-- AGENTS.md -->` 标记写入会话事件日志，恢复会话不会重复注入；
- 超过 `[agents] max_chars`（默认 20000）截断并加标记；
- 文件缺失时静默跳过（`/agents` 会显示"不存在"）；可用 `[agents] enabled=false` 关闭。

## MCP 接入

`config.ini` 的 `[mcp] config_path`（默认 `.mcp.json`）：

```json
{
  "mcpServers": {
    "pet-hospital": {"type": "streamable_http", "url": "http://127.0.0.1:8000/mcp"},
    "local-demo": {
      "type": "stdio",
      "command": "python",
      "args": ["D:/path/to/server.py"],
      "env": {"DEMO_KEY": "xxx"}
    }
  }
}
```

- 支持 stdio（本地进程管道）与 streamable-http 两种传输；
- 启动在后台线程完成，单个 server 失败只记录错误、不阻塞主对话，`/mcp` 可见；
- 工具名冲突时自动加哈希后缀，`server__tool` 前缀标明来源；
- 未配置 `mcp` 依赖或缺 `.mcp.json` 时降级为本地工具集合。

## 技能

```bash
.agents/skills/
└── hello-skill/
    └── SKILL.md        # ---  name/description  ---  + 正文
```

- 启动时只把 `name` + `description` 注入系统提示（渐进加载），正文由 `loadSkill` 按需读取；
- `createSkill` 会校验命名（小写/数字/连字符）、长度、重复，已存在直接拒绝覆盖；
- 附件读取限制在技能目录内（越界返回 `OUTSIDE_SKILL_DIR`）；
- 仓库内 `libai/`、`office/.agents/skills/` 是第三方技能示例，非本项目产出。

## 日志

`main.py` 启动时初始化 `core/logging_setup.py`：文件 `.agents/logs/jagent.log`（2MB 轮转 3 份）
+ 控制台仅 WARNING 以上。日志行形如：

```
2026-11-12 10:00:01 level=INFO logger=jagent.tools tool=list_directory outcome=ok duration_ms=3 args=['path']
```

## 测试

```bash
python -m unittest discover -s tests -t .      # 在 Agent/jagent 下
python ../../run_tests.py jagent                # 或在仓库根目录
```

测试用 `tests/fakes.py` 的假模型客户端驱动主循环，覆盖：多轮工具闭环、步数上限、工具错误回填、
AGENT.md 注入/截断/缺失、路径越界、破坏性操作确认、技能创建与拒绝覆盖、会话保存与恢复。

## 常见问题

| 现象 | 原因与处理 |
| --- | --- |
| 启动只看到欢迎界面，提问报连接错误 | `config.ini` 的 `[llm] base_url/model` 仍是占位符 |
| `searchWeb` 返回 `CONFIG_MISSING` | 未填 `[search] baidu_qianfan_api_key` |
| 工具返回 `OUTSIDE_WORKSPACE` | 目标路径在工作区外；确认后可设 `[tools] allow_outside_workspace=true` |
| `/mcp` 显示 error | `.mcp.json` 的 command/url 不可用；错误原因直接显示在面板里 |
| 回答不再流式刷新 | 该轮一直在调工具，正文在最后一次模型响应时才输出 |
