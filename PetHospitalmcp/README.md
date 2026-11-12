# 宠物医院 MCP server

一个符合 MCP 协议的 server：把 `PetHospitalServer` 的 REST 接口封装成业务工具，
带参数约束、结构化错误码、超时与重试、结构化调用日志。

## 前置条件

1. 启动上游数据服务（默认 `http://127.0.0.1:8080`）：

   ```bash
   cd ../PetHospitalServer && ./pethospital.exe          # Windows 双击亦可
   ```

2. 安装依赖：

   ```bash
   pip install -r requirements.txt                      # mcp>=2.2,<3 / httpx / pydantic
   ```

## 启动与接入

```bash
# 方式一：Streamable HTTP（默认），端点 http://127.0.0.1:8000/mcp
python server.py

# 方式二：stdio（本地进程管道，Claude Desktop 等客户端用这种）
MCP_TRANSPORT=stdio python server.py
```

自定义端口与上游地址：

```bash
MCP_PORT=8100 PET_HOSPITAL_URL=http://127.0.0.1:9090 python server.py
```

客户端配置（Claude Desktop 类，stdio）：

```json
{
  "mcpServers": {
    "pet-hospital": {
      "command": "python",
      "args": ["D:/path/to/PetHospitalmcp/server.py"],
      "env": {"MCP_TRANSPORT": "stdio", "PET_HOSPITAL_URL": "http://127.0.0.1:8080"}
    }
  }
}
```

只支持 HTTP 的客户端直接连 `http://127.0.0.1:8000/mcp` 即可。

> 注意：路径请写你自己机器上的真实路径，不要照抄示例里的 `D:/path/...`。

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PET_HOSPITAL_URL` | `http://127.0.0.1:8080` | 上游服务地址 |
| `PET_HOSPITAL_TIMEOUT` / `PET_HOSPITAL_CONNECT_TIMEOUT` | `10` / `5` | 读超时 / 连接超时（秒） |
| `PET_HOSPITAL_RETRIES` | `2` | 对超时与 5xx 的重试次数（4xx 不重试） |
| `PET_HOSPITAL_LOG_LEVEL` | `INFO` | 日志级别（固定写 stderr，避免污染 stdio 协议通道） |
| `MCP_TRANSPORT` / `MCP_PORT` | `streamable-http` / `8000` | 传输方式与端口 |

## 工具：`list_pets`

查询 `/api/v1/pets`，返回精简摘要（不含病历与收费明细，控制上下文体积）。

| 参数 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `q` | string | ≤64 字符 | 关键词，跨字段检索 |
| `species` | string | ≤16 字符 | 种类，如 `犬` / `猫` |
| `doctor` | string | ≤32 字符 | 主治医生 |
| `status` | string | ≤16 字符 | 就诊状态 |
| `sortBy` | string | 枚举 `totalCost` `visitCount` `name` `ageMonths` | 排序字段，默认 `totalCost` |
| `order` | string | 枚举 `asc` `desc` | 排序方向，默认 `desc` |
| `page` | integer | 1–10000 | 页码，默认 1 |
| `pageSize` | integer | 1–100 | 每页条数，默认 10 |

这些约束会由 MCP SDK 依据函数签名生成 JSON Schema，客户端 `list_tools` 即可看到
`enum` / `minimum` / `maximum` / `maxLength`，非法取值在协议层被拒绝。

调用示例：

```
list_pets(species="犬", order="desc", pageSize=5)
```

返回：

```json
{
  "ok": true,
  "total": 308, "page": 1, "pageSize": 5, "totalPages": 62,
  "items": [{"id": "PET-000001", "name": "旺财", "species": "犬", "totalCost": 1280.0, "...": "..."}]
}
```

## 错误码

失败一律返回结构化 JSON（不会把上游 HTML 错误页直接透传）：

```json
{"ok": false, "error": {"code": "UPSTREAM_UNAVAILABLE", "message": "无法连接宠物医院服务：ConnectError", "details": {"hint": "请先启动 PetHospitalServer/pethospital.exe", "attempt": 3}}}
```

| code | 触发条件 |
| --- | --- |
| `UPSTREAM_TIMEOUT` | 超过 `PET_HOSPITAL_TIMEOUT` |
| `UPSTREAM_UNAVAILABLE` | 连不上上游（进程没起、端口不对） |
| `UPSTREAM_HTTP_ERROR` | 上游 5xx（重试后仍失败） |
| `UPSTREAM_REJECTED` | 上游 4xx 或响应信封里的业务错误 `code>=400` |
| `UPSTREAM_BAD_PAYLOAD` | 返回不是 JSON（例如 HTML 错误页） |
| `UPSTREAM_UNEXPECTED_SCHEMA` | JSON 里缺 `data.items` |

## 日志

固定输出到 stderr，key=value 形式，可用于排查与统计：

```
2026-11-12 10:00:01 INFO tool=list_pets outcome=ok total=308 returned=5 elapsed_ms=12
2026-11-12 10:00:05 WARNING tool=list_pets outcome=UPSTREAM_TIMEOUT attempt=1/3
```

## 测试

```bash
python ../../run_tests.py pet-hospital    # 11 个用例
```

覆盖：JSON Schema 的枚举/范围约束、参数组装、成功解析与字段裁剪、4xx 不重试、
5xx 重试次数、超时、HTML 错误页、业务错误码、缺少 `data.items`。

## 与上游的契约

上游统一信封为 `{"code": 200, "message": "ok", "data": {...}, "time": "..."}`
（见 `../PetHospitalServer/README.md` 的「接口一览」）。本 server 只读取 `data` 与
`code/message`，并对字段做白名单裁剪后返回。
