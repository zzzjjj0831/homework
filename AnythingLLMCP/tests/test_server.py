"""AnythingLLMCP 单元测试（MockTransport，不需要真实 AnythingLLM）。

覆盖：工具覆盖面、鉴权与缺配置报错、分页、各 API 端点与请求体、
失败重试、聊天/检索结果解析、multipart 上传。
运行：python -m unittest discover -s AnythingLLMCP/tests -t AnythingLLMCP
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server  # noqa: E402

API_KEY = "TEST-KEY-0000"


def client_for(handler) -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(handler), base_url="http://anythingllm.test"
    )


class Base(unittest.TestCase):
    def setUp(self):
        os.environ["ANYTHINGLLM_API_KEY"] = API_KEY
        self._patcher = mock.patch.object(server, "_api_key", lambda: API_KEY)
        self._patcher.start()
        self.addCleanup(self._patcher.stop)
        self.addCleanup(mock.patch.stopall)

    def serve(self, handler):
        patcher = mock.patch.object(server, "_make_client", lambda: client_for(handler))
        patcher.start()
        self.addCleanup(patcher.stop)


class RegistryTest(Base):
    def test_registers_nine_tools(self):
        tools = {tool.name: tool for tool in server.mcp._tool_manager.list_tools()}
        self.assertEqual(
            set(tools),
            {
                "list_workspaces",
                "get_workspace",
                "create_workspace",
                "list_documents",
                "upload_document",
                "add_raw_text",
                "update_embeddings",
                "chat",
                "vector_search",
            },
        )

    def test_current_mode_has_enum_and_bounds(self):
        tools = {tool.name: tool for tool in server.mcp._tool_manager.list_tools()}
        chat_props = tools["chat"].parameters["properties"]
        self.assertEqual(chat_props["mode"]["enum"], ["chat", "query"])
        self.assertEqual(chat_props["message"]["maxLength"], 8000)
        vs = tools["vector_search"].parameters["properties"]
        self.assertEqual(vs["top_n"]["maximum"], 20)
        self.assertEqual(vs["similarity_threshold"]["maximum"], 1.0)


class AuthTest(Base):
    def test_missing_key_returns_config_error_and_no_request(self):
        called = {"n": 0}

        def handler(request):
            called["n"] += 1
            return httpx.Response(200, json={"workspaces": []})

        self.serve(handler)
        with mock.patch.object(server, "_api_key", lambda: None):
            result = server.list_workspaces()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "CONFIG_MISSING")
        self.assertEqual(called["n"], 0)

    def test_401_maps_to_auth_failed_without_retry(self):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            self.assertEqual(request.headers["Authorization"], f"Bearer {API_KEY}")
            return httpx.Response(401, json={"error": "invalid api key"})

        self.serve(handler)
        result = server.list_workspaces()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "AUTH_FAILED")
        self.assertEqual(calls["n"], 1)

    def test_5xx_is_retried(self):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(502, text="bad gateway")

        self.serve(handler)
        with mock.patch.object(server.time, "sleep", lambda _s: None):
            result = server.list_workspaces()
        self.assertEqual(result["error"]["code"], "UPSTREAM_HTTP_ERROR")
        self.assertEqual(calls["n"], server.RETRIES + 1)


class WorkspaceTest(Base):
    def test_list_workspaces_pagination(self):
        seen = {}

        def handler(request):
            seen["path"] = request.url.path
            return httpx.Response(
                200,
                json={
                    "workspaces": [
                        {"name": f"ws{i}", "slug": f"slug-{i}", "createdAt": f"2026-01-0{i + 1}"}
                        for i in range(5)
                    ]
                },
            )

        self.serve(handler)
        page = server.list_workspaces(offset=2, limit=2)
        self.assertTrue(page["ok"])
        self.assertEqual(seen["path"], "/api/v1/workspaces")
        self.assertEqual(page["total"], 5)
        self.assertTrue(page["has_more"])
        self.assertEqual([item["slug"] for item in page["items"]], ["slug-2", "slug-3"])

    def test_create_workspace_posts_name(self):
        seen = {}

        def handler(request):
            seen["path"] = request.url.path
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"workspace": {"name": "新工作区", "slug": "new-ws"}})

        self.serve(handler)
        result = server.create_workspace(name="新工作区")
        self.assertTrue(result["ok"])
        self.assertEqual(seen["path"], "/api/v1/workspace/new")
        self.assertEqual(seen["body"], {"name": "新工作区"})

    def test_get_workspace_reports_document_count(self):
        def handler(request):
            self.assertEqual(request.url.path, "/api/v1/workspace/demo")
            return httpx.Response(
                200,
                json={"workspace": [{"name": "demo", "slug": "demo",
                                     "documents": [{"title": "a.md"}, {"title": "b.md"}]}]},
            )

        self.serve(handler)
        result = server.get_workspace(slug="demo")
        self.assertEqual(result["documentCount"], 2)


class DocumentTest(Base):
    def test_list_documents_parses_local_files_dict(self):
        def handler(request):
            self.assertEqual(request.url.path, "/api/v1/documents")
            return httpx.Response(
                200,
                json={
                    "localFiles": {
                        "a.md": {"title": "a.md", "docSource": "upload", "wordCount": 10},
                        "b.md": {"title": "b.md", "docSource": "upload", "wordCount": 20},
                    }
                },
            )

        self.serve(handler)
        result = server.list_documents(limit=1)
        self.assertEqual(result["total"], 2)
        self.assertEqual(len(result["items"]), 1)

    def test_upload_document_sends_multipart(self):
        seen = {}

        def handler(request):
            seen["path"] = request.url.path
            seen["content_type"] = request.headers["content-type"]
            seen["body"] = request.content
            return httpx.Response(
                200,
                json={"success": True, "documents": [{"title": "t.md", "location": "custom-documents/t.md"}]},
            )

        path = Path(__file__).parent / "_upload_probe.md"
        path.write_text("# hello", encoding="utf-8")
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        self.serve(handler)
        result = server.upload_document(file_path=str(path), add_to_workspaces="demo")

        self.assertTrue(result["ok"])
        self.assertEqual(result["documents"][0]["location"], "custom-documents/t.md")
        self.assertEqual(seen["path"], "/api/v1/document/upload")
        self.assertIn("multipart/form-data", seen["content_type"])

    def test_upload_missing_file_returns_invalid_argument(self):
        result = server.upload_document(file_path="Z:/definitely/not/here.md")
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")

    def test_add_raw_text_posts_json(self):
        seen = {}

        def handler(request):
            seen["path"] = request.url.path
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"document": {"location": "raw/x.txt"}})

        self.serve(handler)
        result = server.add_raw_text(text="正文", title="x")
        self.assertTrue(result["ok"])
        self.assertEqual(seen["path"], "/api/v1/document/raw-text")
        self.assertEqual(seen["body"]["textContent"], "正文")


class EmbeddingTest(Base):
    def test_update_embeddings_requires_args(self):
        result = server.update_embeddings(slug="demo")
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENT")

    def test_update_embeddings_posts_adds_and_deletes(self):
        seen = {}

        def handler(request):
            seen["path"] = request.url.path
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"workspace": {"documents": [{"title": "a"}]}})

        self.serve(handler)
        result = server.update_embeddings(slug="demo", adds="loc-a,loc-b", deletes="old.md")
        self.assertTrue(result["ok"])
        self.assertEqual(seen["path"], "/api/v1/workspace/demo/update-embeddings")
        self.assertEqual(seen["body"], {"adds": ["loc-a", "loc-b"], "deletes": ["old.md"]})
        self.assertEqual(result["added"], 2)


class RetrievalTest(Base):
    def test_chat_returns_text_and_sources(self):
        seen = {}

        def handler(request):
            seen["path"] = request.url.path
            seen["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "id": "session-1",
                    "type": "textResponse",
                    "textResponse": "  答案正文  ",
                    "sources": [{"title": "a.md", "url": "http://x", "score": 0.8}],
                },
            )

        self.serve(handler)
        result = server.chat(slug="demo", message="问题", mode="chat", session_id="session-0")
        self.assertTrue(result["ok"])
        self.assertEqual(result["text"], "答案正文")
        self.assertEqual(result["sessionId"], "session-1")
        self.assertEqual(result["sources"][0]["title"], "a.md")
        self.assertEqual(seen["path"], "/api/v1/workspace/demo/chat")
        self.assertEqual(seen["body"]["sessionId"], "session-0")

    def test_vector_search_caps_and_trims(self):
        def handler(request):
            self.assertEqual(request.url.path, "/api/v1/workspace/demo/vector-search")
            return httpx.Response(
                200,
                json={"results": [{"score": 0.9, "text": "x" * 2000}, {"score": 0.1, "text": "y"}]},
            )

        self.serve(handler)
        result = server.vector_search(slug="demo", query="q", top_n=1)
        self.assertEqual(len(result["chunks"]), 1)
        self.assertTrue(result["chunks"][0]["truncated"])
        self.assertEqual(len(result["chunks"][0]["text"]), 1200)

    def test_unexpected_schema_is_reported(self):
        def handler(request):
            return httpx.Response(200, json={"unexpected": True})

        self.serve(handler)
        result = server.chat(slug="demo", message="q")
        self.assertEqual(result["error"]["code"], "UPSTREAM_UNEXPECTED_SCHEMA")


if __name__ == "__main__":
    unittest.main()
