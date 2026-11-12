# AnythingLLM MCP server

把 AnythingLLM 的 HTTP API 封装成 MCP 工具，覆盖四类能力：工作区管理、文档接入、向量化、检索问答。

## 前置条件

1. 已安装并启动 AnythingLLM（默认 `http://127.0.0.1:3001`）；
2. 在 AnythingLLM → Settings → **API Keys** 生成一个 Key；
3. `pip install -r requirements.txt`（`mcp>=2.2,<3`、`httpx`、`pydantic`）。

## 配置（全部走环境变量，无内置密钥）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `ANYTHINGLLM_URL` | `http://127.0.0.1:3001` | 服务地址 |
| `ANYTHINGLLM_API_KEY` | **无，必填** | 缺失时工具返回 `CONFIG_MISSING`，不会使用任何内置 Key |
| `ANYTHINGLLM_TIMEOUT` / `ANYTHINGLLM_RETRIES` | `30` / `2` | 读超时与重试次数（429/5xx 才重试） |
| `MCP_TRANSPORT` | `streamable-http` | 可设为 `stdio` |
| `MCP_PORT` | `8091` | HTTP 端口 |

## 启动

```bash
# Streamable HTTP（默认，端点 http://127.0.0.1:8091/mcp）
export ANYTHINGLLM_API_KEY=你的Key        # Windows: set ANYTHINGLLM_API_KEY=...
python server.py

# stdio（给 Claude Desktop 等只支持进程管道的客户端）
MCP_TRANSPORT=stdio python server.py
```

客户端配置示例（Claude Desktop 类）：

```json
{
  "mcpServers": {
    "anythingllm": {
      "command": "python",
      "args": ["D:/path/to/AnythingLLMCP/server.py"],
      "env": {"ANYTHINGLLM_API_KEY": "你的Key", "ANYTHINGLLM_URL": "http://127.0.0.1:3001"}
    }
  }
}
```

## 工具（9 个）

| 能力 | 工具 | 打到的 API | 关键参数 |
| --- | --- | --- | --- |
| 工作区 | `list_workspaces` | `GET /api/v1/workspaces` | `offset` `limit`（1–100，客户端分页） |
| 工作区 | `get_workspace` | `GET /api/v1/workspace/{slug}` | `slug` |
| 工作区 | `create_workspace` | `POST /api/v1/workspace/new` | `name` |
| 文档 | `list_documents` | `GET /api/v1/documents` | `offset` `limit` |
| 文档 | `upload_document` | `POST /api/v1/document/upload`（multipart） | `file_path` `add_to_workspaces` |
| 文档 | `add_raw_text` | `POST /api/v1/document/raw-text` | `text` `title` `add_to_workspaces` |
| 向量化 | `update_embeddings` | `POST /api/v1/workspace/{slug}/update-embeddings` | `slug` `adds` `deletes`（逗号分隔） |
| 检索问答 | `chat` | `POST /api/v1/workspace/{slug}/chat` | `slug` `message` `mode=chat\|query` `session_id` |
| 检索问答 | `vector_search` | `POST /api/v1/workspace/{slug}/vector-search` | `slug` `query` `top_n` `similarity_threshold` |

典型调用链：

```
list_workspaces → upload_document(file_path="notes.md") → update_embeddings(slug, adds="<location>")
→ chat(slug, "文档讲了什么")   # mode=chat 保留会话，sessionId 用于多轮
```

## 返回与错误

成功：`{"ok": true, ...}`（列表类带 `total/offset/limit/has_more`；`chat` 带 `text/sources/sessionId`）。

失败统一：

```json
{"ok": false, "error": {"code": "AUTH_FAILED", "message": "AnythingLLM 拒绝了该 API Key", "details": {"hint": "..."}}}
```

| code | 含义 |
| --- | --- |
| `CONFIG_MISSING` | 未设置 `ANYTHINGLLM_API_KEY` |
| `AUTH_FAILED` | 401/403，Key 无效 |
| `UPSTREAM_REJECTED` | 4xx，参数/对象不存在（消息里带上游原因） |
| `UPSTREAM_HTTP_ERROR` | 429/5xx，已重试仍失败 |
| `UPSTREAM_TIMEOUT` / `UPSTREAM_UNAVAILABLE` | 超时 / 连不上 |
| `UPSTREAM_BAD_PAYLOAD` / `UPSTREAM_UNEXPECTED_SCHEMA` | 返回非 JSON 或缺关键字段 |
| `INVALID_ARGUMENT` | 本地参数校验失败（空参数、文件不存在、超限） |

## 验证

```bash
python ../../run_tests.py anythingllm     # 17 个用例，MockTransport，无需真实 AnythingLLM
MCP_TRANSPORT=stdio python server.py      # 用任意 MCP 客户端 list tools，应枚举到 9 个
```
