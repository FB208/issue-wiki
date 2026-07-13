from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import sync_manual as sync


class IssueWikiMockHandler(BaseHTTPRequestHandler):
    folders = []
    documents = []
    uploads = 0
    calls = []

    @classmethod
    def reset(cls):
        cls.folders, cls.documents, cls.uploads, cls.calls = [], [], 0, []

    def log_message(self, *_args):
        return

    def read_body(self):
        return self.rfile.read(int(self.headers.get("Content-Length", "0")))

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authenticated(self):
        if self.headers.get("Authorization") == "Bearer mock-token":
            return True
        self.send_json(401, {"detail": "unauthorized"})
        return False

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        self.__class__.calls.append(("GET", parsed.path))
        if not self.authenticated():
            return
        query = urllib.parse.parse_qs(parsed.query)
        page = int(query.get("page", ["1"])[0])
        if parsed.path == "/api/admin/folders":
            # Force an empty second page during the first fetch to exercise pagination.
            items = self.__class__.folders if page == 1 else []
            pages = 2 if not self.__class__.folders else 1
            self.send_json(200, {"items": items, "total": len(items), "page": page, "page_size": 100, "pages": pages})
            return
        if parsed.path == "/api/admin/documents":
            items = self.__class__.documents
            self.send_json(200, {"items": items, "total": len(items), "page": 1, "page_size": 100, "pages": 1})
            return
        self.send_json(404, {"detail": "not found"})

    def do_POST(self):
        parsed = urllib.parse.urlsplit(self.path)
        self.__class__.calls.append(("POST", parsed.path))
        body = self.read_body()
        if parsed.path == "/api/auth/login":
            self.send_json(200, {"access_token": "mock-token", "user": {"role": "admin"}})
            return
        if not self.authenticated():
            return
        if parsed.path == "/api/uploads":
            self.assert_multipart(body)
            self.__class__.uploads += 1
            self.send_json(200, {"url": f"https://cdn.test/{self.__class__.uploads}.png"})
            return
        payload = json.loads(body.decode("utf-8"))
        if parsed.path == "/api/admin/folders":
            item = {"id": len(self.__class__.folders) + 1, **payload}
            self.__class__.folders.append(item)
            self.send_json(200, item)
            return
        if parsed.path == "/api/admin/documents":
            item = {"id": len(self.__class__.documents) + 1, **payload}
            self.__class__.documents.append(item)
            self.send_json(200, item)
            return
        self.send_json(404, {"detail": "not found"})

    def do_PUT(self):
        parsed = urllib.parse.urlsplit(self.path)
        self.__class__.calls.append(("PUT", parsed.path))
        body = self.read_body()
        if not self.authenticated():
            return
        payload = json.loads(body.decode("utf-8"))
        if parsed.path.startswith("/api/admin/folders/"):
            item = next(value for value in self.__class__.folders if value["id"] == int(parsed.path.rsplit("/", 1)[1]))
        elif parsed.path.startswith("/api/admin/documents/"):
            item = next(value for value in self.__class__.documents if value["id"] == int(parsed.path.rsplit("/", 1)[1]))
        else:
            self.send_json(404, {"detail": "not found"})
            return
        item.update(payload)
        self.send_json(200, item)

    def assert_multipart(self, body):
        content_type = self.headers.get("Content-Type", "")
        if not content_type.startswith("multipart/form-data; boundary=") or b'name="file"' not in body:
            raise AssertionError("invalid multipart upload")


class FullHttpFlow(unittest.TestCase):
    def test_apply_and_second_apply_through_http_api(self):
        IssueWikiMockHandler.reset()
        server = ThreadingHTTPServer(("127.0.0.1", 0), IssueWikiMockHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        temporary = tempfile.TemporaryDirectory()
        try:
            root = Path(temporary.name)
            source = root / "使用说明"
            (source / "配置").mkdir(parents=True)
            (source / "images").mkdir()
            (source / "images" / "a.png").write_bytes(b"image")
            (source / "配置" / "01.md").write_text("![a](../images/a.png)\n", encoding="utf-8")
            state = root / "state.json"
            config = sync.Config(f"http://127.0.0.1:{server.server_port}/api", "admin", "password")

            first = sync.SyncRunner(config, source, state, sync.ApiClient(config)).apply()
            self.assertEqual((first.images_upload, first.folders_create, first.documents_create), (1, 1, 1))
            self.assertIn(("GET", "/api/admin/folders"), IssueWikiMockHandler.calls)
            self.assertGreaterEqual(IssueWikiMockHandler.calls.count(("GET", "/api/admin/folders")), 2)
            self.assertIn(("POST", "/api/uploads"), IssueWikiMockHandler.calls)
            self.assertIn(("POST", "/api/admin/folders"), IssueWikiMockHandler.calls)
            self.assertIn(("POST", "/api/admin/documents"), IssueWikiMockHandler.calls)

            writes_before = [call for call in IssueWikiMockHandler.calls if call[0] in {"PUT", "POST"} and call[1] != "/api/auth/login"]
            second = sync.SyncRunner(config, source, state, sync.ApiClient(config)).apply()
            writes_after = [call for call in IssueWikiMockHandler.calls if call[0] in {"PUT", "POST"} and call[1] != "/api/auth/login"]
            self.assertEqual((second.images_reuse, second.folders_skip, second.documents_skip), (1, 1, 1))
            self.assertEqual(writes_after, writes_before)
        finally:
            temporary.cleanup()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
