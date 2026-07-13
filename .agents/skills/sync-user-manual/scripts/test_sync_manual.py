from __future__ import annotations

import json
import tempfile
import threading
import unittest
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import sync_manual as sync


class FakeClient:
    def __init__(self, folders=None, documents=None):
        self.folders = deepcopy(folders or [])
        self.documents = deepcopy(documents or [])
        self.writes: list[tuple[str, str]] = []
        self.uploads: list[str] = []
        self.login_count = 0
        self.next_folder_id = max((item["id"] for item in self.folders), default=0) + 1
        self.next_document_id = max((item["id"] for item in self.documents), default=0) + 1

    def login(self):
        self.login_count += 1

    def list_all(self, path):
        if path == "/admin/folders":
            return deepcopy(self.folders)
        if path == "/admin/documents":
            return deepcopy(self.documents)
        raise AssertionError(path)

    def upload(self, asset):
        self.writes.append(("POST", "/uploads"))
        self.uploads.append(asset.digest)
        return f"https://cdn.test/{asset.digest}{asset.path.suffix}"

    def request(self, method, path, payload=None, **_kwargs):
        self.writes.append((method, path))
        if method == "POST" and path == "/admin/folders":
            item = {"id": self.next_folder_id, **payload}
            self.next_folder_id += 1
            self.folders.append(item)
            return deepcopy(item)
        if method == "PUT" and path.startswith("/admin/folders/"):
            item = next(value for value in self.folders if value["id"] == int(path.rsplit("/", 1)[1]))
            item.update(payload)
            return deepcopy(item)
        if method == "POST" and path == "/admin/documents":
            item = {"id": self.next_document_id, **payload}
            self.next_document_id += 1
            self.documents.append(item)
            return deepcopy(item)
        if method == "PUT" and path.startswith("/admin/documents/"):
            item = next(value for value in self.documents if value["id"] == int(path.rsplit("/", 1)[1]))
            item.update(payload)
            return deepcopy(item)
        raise AssertionError((method, path, payload))


class SyncFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "使用说明"
        (self.source / "配置").mkdir(parents=True)
        (self.source / "images").mkdir()
        (self.source / "images" / "a.png").write_bytes(b"not-a-real-png-but-valid-upload-by-extension")
        (self.source / "配置" / "01-开始.md").write_text(
            "# 开始\n\n![图](../images/a.png)\n", encoding="utf-8"
        )
        self.state = self.root / ".sync-state.local.json"
        self.config = sync.Config("http://127.0.0.1/api", "admin@example.com", "password123")

    def tearDown(self):
        self.temporary.cleanup()

    def runner(self, client):
        return sync.SyncRunner(self.config, self.source, self.state, client)

    def test_preview_allows_login_but_has_no_write_calls_or_state_file(self):
        client = FakeClient()
        result = self.runner(client).preview()
        self.assertEqual(client.login_count, 1)
        self.assertEqual(client.writes, [])
        self.assertFalse(self.state.exists())
        self.assertEqual(result.images_upload, 1)
        self.assertEqual(result.folders_create, 1)
        self.assertEqual(result.documents_create, 1)

    def test_apply_then_second_apply_is_idempotent(self):
        client = FakeClient()
        first = self.runner(client).apply()
        self.assertEqual(first.images_upload, 1)
        self.assertEqual(first.folders_create, 1)
        self.assertEqual(first.documents_create, 1)
        self.assertTrue(self.state.exists())
        writes_after_first = len(client.writes)

        second = self.runner(client).apply()
        self.assertEqual(second.images_upload, 0)
        self.assertEqual(second.images_reuse, 1)
        self.assertEqual(second.folders_skip, 1)
        self.assertEqual(second.documents_skip, 1)
        self.assertEqual(len(client.writes), writes_after_first)

    def test_existing_folder_order_is_preserved(self):
        client = FakeClient(
            folders=[{"id": 7, "name": "配置", "parent_id": None, "sort_order": 999}]
        )
        preview = self.runner(client).preview()
        self.assertEqual(preview.folders_create, 0)
        self.assertEqual(preview.folders_skip, 1)
        self.assertEqual(client.writes, [])

        result = self.runner(client).apply()
        self.assertEqual(result.folders_create, 0)
        self.assertEqual(result.folders_skip, 1)
        self.assertNotIn(("PUT", "/admin/folders/7"), client.writes)
        self.assertEqual(client.folders[0]["sort_order"], 999)

    def test_markdown_change_updates_only_document(self):
        client = FakeClient()
        self.runner(client).apply()
        client.writes.clear()
        path = self.source / "配置" / "01-开始.md"
        path.write_text(path.read_text(encoding="utf-8") + "新增内容\n", encoding="utf-8")
        result = self.runner(client).apply()
        self.assertEqual(result.images_upload, 0)
        self.assertEqual(result.documents_update, 1)
        self.assertEqual(client.writes, [("PUT", "/admin/documents/1")])

    def test_changed_image_uploads_once_and_updates_document(self):
        client = FakeClient()
        self.runner(client).apply()
        client.writes.clear()
        (self.source / "images" / "a.png").write_bytes(b"changed")
        result = self.runner(client).apply()
        self.assertEqual(result.images_upload, 1)
        self.assertEqual(result.documents_update, 1)
        self.assertEqual([method for method, path in client.writes if path == "/uploads"], ["POST"])

    def test_duplicate_remote_folder_aborts_before_writes(self):
        client = FakeClient(
            folders=[
                {"id": 1, "parent_id": None, "name": "配置", "sort_order": 10},
                {"id": 2, "parent_id": None, "name": "配置", "sort_order": 20},
            ]
        )
        with self.assertRaisesRegex(sync.ValidationError, "文件夹重复"):
            self.runner(client).apply()
        self.assertEqual(client.writes, [])

    def test_inline_reference_and_html_images_share_one_asset(self):
        path = self.source / "配置" / "01-开始.md"
        path.write_text(
            "![行内](../images/a.png)\n![引用][pic]\n<img src='../images/a.png'>\n"
            "![远端](https://example.com/a.png)\n[pic]: ../images/a.png\n",
            encoding="utf-8",
        )
        catalog = sync.discover_local(self.source)
        self.assertEqual(len(catalog.assets), 1)
        self.assertEqual(len(catalog.documents[0].references), 3)
        digest = next(iter(catalog.assets))
        rendered = catalog.documents[0].render({digest: "https://cdn.test/a.png"})
        self.assertEqual(rendered.count("https://cdn.test/a.png"), 3)
        self.assertIn("https://example.com/a.png", rendered)

    def test_missing_and_outside_images_fail_preflight(self):
        outside = self.root / "outside.png"
        outside.write_bytes(b"outside")
        path = self.source / "配置" / "01-开始.md"
        path.write_text("![x](../../outside.png)\n![y](../images/missing.png)\n", encoding="utf-8")
        with self.assertRaises(sync.ValidationError) as raised:
            sync.discover_local(self.source)
        self.assertIn("超出使用说明目录", str(raised.exception))
        self.assertIn("引用图片不存在", str(raised.exception))


class LocalApiHandler(BaseHTTPRequestHandler):
    calls: list[tuple[str, str, str | None]] = []

    def log_message(self, *_args):
        return

    def _json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.__class__.calls.append(
            ("POST", self.path, self.headers.get("Authorization"), self.headers.get("User-Agent"))
        )
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        if self.path == "/api/auth/login":
            self._json(200, {"access_token": "secret-token", "user": {"role": "admin"}})
        else:
            self._json(404, {"detail": "not found"})

    def do_GET(self):
        self.__class__.calls.append(
            ("GET", self.path, self.headers.get("Authorization"), self.headers.get("User-Agent"))
        )
        if self.path.startswith("/api/admin/folders"):
            self._json(200, {"items": [], "page": 1, "page_size": 100, "pages": 1, "total": 0})
        else:
            self._json(404, {"detail": "not found"})


class ApiClientTests(unittest.TestCase):
    def test_local_http_login_pagination_and_bearer_header(self):
        LocalApiHandler.calls = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), LocalApiHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            config = sync.Config(
                f"http://127.0.0.1:{server.server_port}/api", "admin@example.com", "password123"
            )
            client = sync.ApiClient(config)
            client.login()
            self.assertEqual(client.list_all("/admin/folders"), [])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertEqual(LocalApiHandler.calls[0][0:2], ("POST", "/api/auth/login"))
        self.assertIsNone(LocalApiHandler.calls[0][2])
        self.assertEqual(LocalApiHandler.calls[0][3], sync.DEFAULT_USER_AGENT)
        self.assertEqual(LocalApiHandler.calls[1][2], "Bearer secret-token")


class RepositoryCorpusTests(unittest.TestCase):
    def test_current_corpus_counts(self):
        repository = Path(__file__).resolve().parents[4]
        catalog = sync.discover_local(repository / "使用说明")
        self.assertEqual(len(catalog.documents), 10)
        self.assertEqual(len(catalog.folders), 2)
        self.assertEqual(len(catalog.assets), 14)
        self.assertEqual(sync.state_path(), repository / ".sync-user-manual-state.local.json")


if __name__ == "__main__":
    unittest.main()
