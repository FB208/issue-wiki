from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import sync_manual as sync
from test_sync_manual import FakeClient


class EdgeCases(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "使用说明"
        self.source.mkdir()
        self.state = self.root / "state.json"
        self.config = sync.Config("http://127.0.0.1/api", "admin@example.com", "password123")

    def tearDown(self):
        self.temporary.cleanup()

    def test_same_filename_in_different_nested_folders_is_allowed(self):
        (self.source / "配置" / "进阶").mkdir(parents=True)
        (self.source / "使用 空格").mkdir()
        (self.source / "配置" / "进阶" / "01-开始.md").write_text("# A\n", encoding="utf-8")
        (self.source / "使用 空格" / "01-开始.md").write_text("# B\n", encoding="utf-8")
        client = FakeClient()
        result = sync.SyncRunner(self.config, self.source, self.state, client).apply()
        self.assertEqual(result.folders_create, 3)
        self.assertEqual(result.documents_create, 2)
        self.assertEqual({item["title"] for item in client.documents}, {"01-开始"})
        self.assertEqual(len({item["folder_id"] for item in client.documents}), 2)

    def test_duplicate_remote_document_aborts_before_writes(self):
        (self.source / "配置").mkdir()
        (self.source / "配置" / "01-开始.md").write_text("# A\n", encoding="utf-8")
        folder = {"id": 1, "parent_id": None, "name": "配置", "sort_order": 10}
        document = {"folder_id": 1, "title": "01-开始", "content": "old", "sort_order": 10}
        client = FakeClient(
            folders=[folder],
            documents=[{"id": 1, **document}, {"id": 2, **document}],
        )
        with self.assertRaisesRegex(sync.ValidationError, "文档重复"):
            sync.SyncRunner(self.config, self.source, self.state, client).apply()
        self.assertEqual(client.writes, [])

    def test_unsupported_image_and_oversized_image_fail_preflight(self):
        (self.source / "配置").mkdir()
        (self.source / "images").mkdir()
        (self.source / "images" / "bad.svg").write_text("<svg/>", encoding="utf-8")
        oversized = self.source / "images" / "large.png"
        with oversized.open("wb") as file:
            file.truncate(sync.MAX_IMAGE_SIZE + 1)
        (self.source / "配置" / "01.md").write_text(
            "![bad](../images/bad.svg)\n![large](../images/large.png)\n", encoding="utf-8"
        )
        with self.assertRaises(sync.ValidationError) as raised:
            sync.discover_local(self.source)
        self.assertIn("不支持的图片类型", str(raised.exception))
        self.assertIn("超过 10MB", str(raised.exception))

    def test_upload_failure_stops_before_folder_or_document_writes(self):
        (self.source / "配置").mkdir()
        (self.source / "images").mkdir()
        (self.source / "images" / "a.png").write_bytes(b"a")
        (self.source / "配置" / "01.md").write_text("![a](../images/a.png)\n", encoding="utf-8")

        class FailingUploadClient(FakeClient):
            def upload(self, _asset):
                self.writes.append(("POST", "/uploads"))
                raise sync.ApiError("模拟上传失败")

        client = FailingUploadClient()
        with self.assertRaisesRegex(sync.ApiError, "模拟上传失败"):
            sync.SyncRunner(self.config, self.source, self.state, client).apply()
        self.assertEqual(client.writes, [("POST", "/uploads")])
        self.assertFalse(self.state.exists())

    def test_natural_sort_handles_numeric_and_non_numeric_names(self):
        values = ["说明", "10-后", "2-先"]
        self.assertEqual(sorted(values, key=sync.natural_key), ["2-先", "10-后", "说明"])


class AuthHandler(BaseHTTPRequestHandler):
    role = "user"
    status = 200

    def log_message(self, *_args):
        return

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        if self.status != 200:
            payload = {"detail": "账号或密码错误"}
        else:
            payload = {"access_token": "token", "user": {"role": self.role}}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class AuthenticationFailures(unittest.TestCase):
    def run_login(self, role="user", status=200):
        AuthHandler.role, AuthHandler.status = role, status
        server = ThreadingHTTPServer(("127.0.0.1", 0), AuthHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        config = sync.Config(f"http://127.0.0.1:{server.server_port}/api", "account", "password")
        try:
            sync.ApiClient(config).login()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_non_admin_login_is_rejected(self):
        with self.assertRaisesRegex(sync.ApiError, "不是管理员"):
            self.run_login(role="user")

    def test_bad_credentials_are_reported_without_request_secrets(self):
        with self.assertRaises(sync.ApiError) as raised:
            self.run_login(status=401)
        message = str(raised.exception)
        self.assertIn("HTTP 401", message)
        self.assertNotIn("password", message)
        self.assertNotIn("account", message)


if __name__ == "__main__":
    unittest.main()
