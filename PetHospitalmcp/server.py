import os

import httpx
from mcp.server.mcpserver import MCPServer

BASE_URL = os.environ.get("PET_HOSPITAL_URL", "http://127.0.0.1:8080")

mcp = MCPServer("pet-hospital", instructions="宠物医院数据查询。先运行 PetHospitalServer/pethospital.exe 再使用。")


@mcp.tool(description="查询宠物医院的宠物列表：支持关键词/种类/医生/状态筛选、排序、分页。返回精简摘要（不含病历和收费明细）。")
def list_pets(
    q: str = "",
    species: str = "",
    doctor: str = "",
    status: str = "",
    sortBy: str = "totalCost",
    order: str = "desc",
    page: int = 1,
    pageSize: int = 10,
) -> dict:
    """GET /api/v1/pets 的客户端封装。

    q: 关键词（跨字段检索）; species: 种类(如 犬/猫); doctor: 医生; status: 就诊状态
    sortBy: totalCost/visitCount/name/ageMonths 等; order: asc/desc
    """
    params = {
        k: v
        for k, v in {
            "q": q, "species": species, "doctor": doctor, "status": status,
            "sortBy": sortBy, "order": order, "page": page, "pageSize": pageSize,
        }.items()
        if v
    }
    resp = httpx.get(f"{BASE_URL}/api/v1/pets", params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()["data"]
    fields = (
        "id", "name", "species", "breed", "gender", "ageMonths",
        "ownerName", "ownerPhone", "doctor", "disease", "status",
        "totalCost", "visitCount",
    )
    return {
        "total": data["total"],
        "page": data["page"],
        "pageSize": data["pageSize"],
        "totalPages": data["totalPages"],
        "items": [{k: it.get(k) for k in fields} for it in data["items"]],
    }


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
