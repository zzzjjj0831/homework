import os

import httpx
from mcp.server.mcpserver import MCPServer

BASE_URL = os.environ.get("ANYTHINGLLM_URL", "http://127.0.0.1:3001")
API_KEY = os.environ.get("ANYTHINGLLM_API_KEY", "47EF28B-25SMNWF-Q9JEH7R-FRN3A16")

mcp = MCPServer("anythingllm", instructions="AnythingLLM 工作区查询。")


@mcp.tool(description="列出 AnythingLLM 的全部工作区（名称、slug、创建时间）")
def list_workspaces() -> dict:
    resp = httpx.get(
        f"{BASE_URL}/api/v1/workspaces",
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=10,
    )
    resp.raise_for_status()
    ws = resp.json()["workspaces"]
    return {
        "count": len(ws),
        "workspaces": [
            {"name": w["name"], "slug": w["slug"], "createdAt": w.get("createdAt")}
            for w in ws
        ],
    }


if __name__ == "__main__":
    mcp.run(transport="streamable-http", port=8091)
