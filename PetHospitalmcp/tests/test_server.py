"""PetHospitalmcp 单元测试。

不依赖真实上游服务：用 httpx.MockTransport 模拟 PetHospitalServer 的响应，
覆盖 schema 约束、参数组装、成功解析、4xx/5xx/超时/非 JSON/结构异常等失败路径。
运行：python -m unittest discover -s PetHospitalmcp/tests -t PetHospitalmcp
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server  # noqa: E402


def make_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def ok_payload():
    return {
        "data": {
            "total": 1,
            "page": 1,
            "pageSize": 10,
            "totalPages": 1,
            "items": [
                {
                    "id": "PET-000001",
                    "name": "旺财",
                    "species": "犬",
                    "doctor": "李医生",
                    "totalCost": 1200,
                    "records": [{"note": "不应出现在摘要里"}],
                }
            ],
        }
    }


class ToolSchemaTest(unittest.TestCase):
    def setUp(self):
        self.tool = server.mcp._tool_manager.list_tools()[0]

    def test_registers_single_business_tool(self):
        names = [t.name for t in server.mcp._tool_manager.list_tools()]
        self.assertEqual(names, ["list_pets"])

    def test_schema_has_enum_and_range_constraints(self):
        props = self.tool.parameters["properties"]
        self.assertEqual(props["order"]["enum"], ["asc", "desc"])
        self.assertEqual(
            props["sortBy"]["enum"], ["totalCost", "visitCount", "name", "ageMonths"]
        )
        self.assertEqual(props["page"]["minimum"], 1)
        self.assertEqual(props["pageSize"]["maximum"], server.MAX_PAGE_SIZE)
        self.assertEqual(props["q"]["maxLength"], 64)

    def test_description_mentions_error_contract(self):
        self.assertIn("error.code", self.tool.description)


class FetchPetsTest(unittest.TestCase):
    def test_success_trims_to_summary_fields(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/api/v1/pets")
            self.assertEqual(request.url.params["pageSize"], "10")
            return httpx.Response(200, json=ok_payload())

        with make_client(handler) as client:
            result = server.fetch_pets({"page": 1, "pageSize": 10}, client=client)

        self.assertTrue(result["ok"])
        self.assertEqual(result["total"], 1)
        item = result["items"][0]
        self.assertEqual(item["name"], "旺财")
        self.assertNotIn("records", item)
        self.assertEqual(set(item), set(server.SUMMARY_FIELDS))

    def test_4xx_is_not_retried_and_returns_code(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(400, json={"error": "bad sortBy"})

        with make_client(handler) as client:
            result = server.fetch_pets({}, client=client)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "UPSTREAM_REJECTED")
        self.assertEqual(result["error"]["details"]["status_code"], 400)
        self.assertEqual(calls["n"], 1, "4xx 不应重试")

    def test_5xx_is_retried_then_reported(self):
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(503, text="upstream down")

        with make_client(handler) as client:
            with mock.patch.object(server.time, "sleep", lambda _s: None):
                result = server.fetch_pets({}, client=client)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "UPSTREAM_HTTP_ERROR")
        self.assertEqual(calls["n"], server.RETRIES + 1)

    def test_timeout_returns_structured_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("slow", request=request)

        with make_client(handler) as client:
            with mock.patch.object(server.time, "sleep", lambda _s: None):
                result = server.fetch_pets({}, client=client)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "UPSTREAM_TIMEOUT")

    def test_html_error_page_is_not_passed_through(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html><body>502 Bad Gateway</body></html>")

        with make_client(handler) as client:
            result = server.fetch_pets({}, client=client)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "UPSTREAM_BAD_PAYLOAD")
        self.assertFalse(json.dumps(result).startswith("<html"))

    def test_unexpected_schema_is_reported(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": {"rows": []}})

        with make_client(handler) as client:
            result = server.fetch_pets({}, client=client)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "UPSTREAM_UNEXPECTED_SCHEMA")

    def test_business_error_code_in_envelope_is_reported(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"code": 400, "message": "sortBy 不支持", "data": None}
            )

        with make_client(handler) as client:
            result = server.fetch_pets({}, client=client)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "UPSTREAM_REJECTED")
        self.assertEqual(result["error"]["details"]["business_code"], 400)


class ToolParamTest(unittest.TestCase):
    def test_list_pets_builds_params_and_drops_empty_filters(self):
        with mock.patch.object(server, "fetch_pets", return_value={"ok": True}) as spy:
            server.list_pets(q="  ", species="犬", page=2, pageSize=5)
        params = spy.call_args[0][0]
        self.assertNotIn("q", params)
        self.assertEqual(params["species"], "犬")
        self.assertEqual(params["page"], 2)
        self.assertEqual(params["pageSize"], 5)
        self.assertEqual(params["sortBy"], "totalCost")
        self.assertEqual(params["order"], "desc")


if __name__ == "__main__":
    unittest.main()
