# 宠物医院 MCP

基于 Streamable HTTP 的最小 MCP 服务器，只有一个工具 `list_pets`，
查询 `PetHospitalServer` REST API（默认 `http://127.0.0.1:8080`）的宠物列表。

## 前置条件

1. 先启动医院服务：`PetHospitalServer\pethospital.exe`
2. 安装依赖：`pip install -r requirements.txt`

## 启动 MCP 服务器

```bash
python server.py
```

默认监听 `http://127.0.0.1:8000/mcp`。
医院服务地址可用环境变量覆盖：`PET_HOSPITAL_URL=http://127.0.0.1:9090 python server.py`

## 工具说明

`list_pets(q?, species?, doctor?, status?, sortBy?, order?, page?, pageSize?)`

- 返回精简摘要（每条约 13 个字段），不含病历与收费明细，节省上下文
- 示例：`list_pets(species="犬", order="desc")` → 按总花费倒序的犬类档案

## 接入配置

### Claude Code

```bash
claude mcp add pet-hospital -- python D:\zzzjjj\LLM-Course\PetHospitalmcp\server.py
```

### Claude Desktop

编辑 `claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "pet-hospital": {
      "command": "python",
      "args": ["D:\\zzzjjj\\LLM-Course\\PetHospitalmcp\\server.py"]
    }
  }
}
```

### 通用 Streamable HTTP 客户端

直接连接 `http://127.0.0.1:8000/mcp`（MCP Streamable HTTP 协议）。
