# LLM 技术与应用 · 课程项目总仓库

本仓库是课程期末项目的完整交付：一个可用的本地 Agent（`jagent`）、两个 MCP server
（宠物医院 / AnythingLLM）、一个 AnythingLLM 网页上传器，以及配套的文档、配置模板与测试。

```
┌──────────────┐   MCP / streamable-http   ┌────────────────────┐
│  jagent TUI  │ ────────────────────────► │ PetHospitalmcp     │ ──HTTP──► pethospital.exe :8080
│ (Agent 主程序)│ ────────────────────────► │ AnythingLLMCP      │ ──HTTP──► AnythingLLM :3001
│              │ ──读取──► AGENT.md         └────────────────────┘
│              │ ──读写──► .agents/{skills,sessions,context,logs}
└──────────────┘
```

## 项目地图

| 目录 | 内容 | 文档 | 启动方式 |
| --- | --- | --- | --- |
| `Agent/jagent/` | 定制 Agent：工具调用主循环、技能、MCP 客户端、会话、上下文压缩、TUI | [README](Agent/jagent/README.md) | `python main.py` |
| `PetHospitalmcp/` | 宠物医院 MCP server（1 个业务工具，含参数约束与结构化错误） | [README](PetHospitalmcp/README.md) | `python server.py` |
| `PetHospitalServer/` | 上游 REST 服务（预编译二进制 + 示例数据库） | [README](PetHospitalServer/README.md) | `pethospital.exe` |
| `AnythingLLMCP/` | AnythingLLM MCP server（工作区/文档/向量化/检索问答） | [README](AnythingLLMCP/README.md) | `python server.py` |
| `AnythingLLMWebpage/` | 单文件网页：上传文档并向量化 | [README](AnythingLLMWebpage/README.md) | 浏览器打开 `index.html` |
| `libai/`、`office/` | 第三方技能包（非本项目产出，仅作技能示例，来源见各目录 README） | — | 由 jagent 按需扫描 |
| `Agent/Practice01/`、`Agent/Practice02/` | 课程练习（流式对话、工具调用、文件操作） | [README](Agent/Practice02/README.md) | `python <脚本>` |

## 环境要求

- Python **3.11+**（开发环境为 3.13.7）
- 可选：AnythingLLM（本地默认 `http://127.0.0.1:3001`）与其 API Key
- 可选：宠物医院服务 `PetHospitalServer/pethospital.exe`（默认 `http://127.0.0.1:8080`）
- 一个 OpenAI 兼容的模型服务（本地 LM Studio / Ollama / 云端均可）

## 快速开始（5 分钟）

```bash
# 1. 安装依赖（三个子项目各自独立）
pip install -r Agent/jagent/requirements.txt
pip install -r PetHospitalmcp/requirements.txt
pip install -r AnythingLLMCP/requirements.txt

# 2. 跑测试（不依赖网络与真实模型）
python run_tests.py

# 3. 启动 Agent：首次运行会在当前目录生成 config.ini（模板来自代码内 CONFIG_TEMPLATE）
cd Agent/jagent
python main.py
#   编辑 config.ini 里的 [llm] base_url / model / api_key 后重启

# 4.（可选）启动两个 MCP server
cd PetHospitalServer && ./pethospital.exe            # 上游数据服务 :8080
cd PetHospitalmcp   && python server.py              # MCP :8000/mcp
cd AnythingLLMCP    && python server.py              # MCP :8091/mcp
```

## 配置矩阵

Agent 的配置全部在 `config.ini`（**不入库**，首次运行自动生成；模板见
[`config.example.ini`](config.example.ini)）。关键字段：

| 小节 | 字段 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `llm` | `base_url` / `model` / `api_key` | `http://127.0.0.1:1234/v1` / `your-model-name` / `DUMMY` | OpenAI 兼容接口 |
| `llm` | `context_window` | `auto` | 支持 `auto`、`131072`、`128k` |
| `agent` | `max_steps` | `8` | 单轮最多几轮"模型→工具→模型" |
| `agents` | `file` / `candidates` / `max_chars` | `AGENTS.md` / `AGENT.md,AGENTS.md,...` / `20000` | 长期规则文件与截断上限 |
| `tools` | `workspace_root` / `allow_outside_workspace` | 空（项目根）/ `false` | 文件工具的路径白名单 |
| `tools` | `search_api_url` + `search.baidu_qianfan_api_key` | 千帆搜索 | 联网搜索工具 |
| `sessions` / `context` | `dir` / `archive_dir` | `.agents/sessions` / `.agents/context` | 会话与压缩归档 |
| `logging` | `file` / `level` | `.agents/logs/jagent.log` / `INFO` | 结构化日志 |

两个 MCP server 只读环境变量：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PET_HOSPITAL_URL` | `http://127.0.0.1:8080` | 上游宠物医院服务地址 |
| `PET_HOSPITAL_TIMEOUT` / `PET_HOSPITAL_RETRIES` | `10` / `2` | 超时与重试次数 |
| `MCP_TRANSPORT` / `MCP_PORT` | `streamable-http` / `8000`、`8091` | 传输方式（可切 `stdio`） |
| `ANYTHINGLLM_URL` | `http://127.0.0.1:3001` | AnythingLLM 地址 |
| `ANYTHINGLLM_API_KEY` | 无（**必填**） | 缺失时工具返回 `CONFIG_MISSING`，不内置任何 Key |

## 密钥与安全（必读）

1. **密钥不入库**：`config.ini`、`.env` 已在 `.gitignore` 中；示例只用占位符。
2. **MCP server 只认环境变量**：`ANYTHINGLLM_API_KEY` 没有默认值，缺失时明确报错。
3. **网页不落密钥**：`AnythingLLMWebpage/index.html` 的地址与 Key 由用户在页面填写，
   只存在 `sessionStorage`，刷新即失效；源码中不含任何 Key。
4. **文件工具默认限制在工作区内**：`PathPolicy` 拒绝越界路径；删除/重命名需要
   `confirm=true`；删目录需 `recursive=true` 才递归。

## 验证清单

自动化（无网络、无模型）：

```bash
python run_tests.py          # 三个子项目共 60+ 个用例，覆盖工具副作用、错误码、Agent 主循环
```

手工验收：

| 场景 | 步骤 | 预期 |
| --- | --- | --- |
| Agent 工具闭环 | 启动 jagent → 输入"现在几点，然后列出当前目录" | 连续两次工具调用后给出回答，`/context` 显示 token 增长 |
| 路径边界 | 输入"读取 C:\\Windows\\win.ini" | 工具返回 `OUTSIDE_WORKSPACE`，不读取 |
| 破坏性确认 | 输入"删除 data 目录" | 先返回 `CONFIRM_REQUIRED`，确认后才删除 |
| 技能 | `/tools` → 让模型"创建一个叫 hello-skill 的技能" | `.agents/skills/hello-skill/SKILL.md` 落盘，重启后可被列举 |
| 长期规则 | 在项目根写 `AGENT.md` → 重启 | 首条 system 消息带 `<!-- AGENTS.md -->` 标记，`/agents` 显示已注入 |
| MCP 降级 | 把 `.mcp.json` 的 command 改错 → 启动 | `/mcp` 显示 error，主对话仍可用 |
| 会话 | 聊几句 → `/new` → `/resume` | 能列出并恢复历史会话 |
| 压缩 | `/compact` | 生成摘要与 `.agents/context/<id>.jsonl` 归档，`recallContext` 可检索 |
| 医院 MCP | 启动上游 + `server.py` → 客户端 list tools | 枚举到 `list_pets`，参数带 enum/min/max |
| AnythingLLM MCP | 配置 Key 后 ask 工作区 | 9 个工具可枚举，`chat` 返回正文与来源 |
| 网页 | 打开 `index.html` → 填地址与 Key | 上传→嵌入全流程有 loading/成功/失败三态 |

## 目录结构（本仓库实际内容）

```
.
├── AGENT.md                     长期规则（仓库级）
├── config.example.ini           Agent 配置模板（无真实密钥）
├── run_tests.py                 一键跑三个子项目的测试
├── Agent/
│   ├── jagent/                  Agent 主体（core/{agent,tools,mcp,skills,session,context,config} + tui + tests）
│   ├── Practice01/              课程练习：流式对话
│   └── Practice02/              课程练习：工具调用与文件操作
├── PetHospitalServer/           上游 REST 服务（预编译 exe + 示例 db，**源码不在本仓库**）
├── PetHospitalmcp/              宠物医院 MCP server + tests
├── AnythingLLMCP/               AnythingLLM MCP server + tests
├── AnythingLLMWebpage/          单文件网页
├── libai/                       第三方技能包（来源见 libai/README.md）
└── office/                      第三方 officecli 技能与二进制（来源见 office/)
```

## 已知限制

- 上游宠物医院服务与 `office/` 的二进制、`data/pet.db` 属于**必要运行产物**，一并提交；
  若需减小仓库体积，可用 `git rm --cached` 保留在本地（见各 README 说明）。
- 两个 MCP server 只做上游能力封装，不额外提供鉴权；请只绑定 `127.0.0.1`。
- AnythingLLM 的向量化效果取决于其嵌入引擎配置，本仓库不负责该部分。
