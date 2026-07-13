#!/usr/bin/env python3
"""Preview or apply synchronization of 使用说明 to a deployed issue-wiki API."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import mimetypes
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
MAX_IMAGE_SIZE = 10 * 1024 * 1024
PAGE_SIZE = 100
DEFAULT_AUTHOR = "生产力Mark"
STATE_VERSION = 1


class SyncError(Exception):
    """Base error safe to display without secrets."""


class ConfigError(SyncError):
    pass


class ValidationError(SyncError):
    pass


class ApiError(SyncError):
    pass


def normalized(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def natural_key(value: str) -> tuple[Any, ...]:
    value = unicodedata.normalize("NFC", value)
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in re.split(r"(\d+)", value)
    )


def parse_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        raise ConfigError(f"无法读取配置文件：{path}") from exc
    values: dict[str, str] = {}
    for number, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ConfigError(f"配置文件第 {number} 行缺少等号")
        key, raw_value = line.split("=", 1)
        key, raw_value = key.strip(), raw_value.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ConfigError(f"配置文件第 {number} 行变量名无效")
        if raw_value[:1] in {"'", '"'}:
            try:
                value = ast.literal_eval(raw_value)
            except (SyntaxError, ValueError) as exc:
                raise ConfigError(f"配置文件第 {number} 行引号无效") from exc
            if not isinstance(value, str):
                raise ConfigError(f"配置文件第 {number} 行必须是字符串")
        else:
            value = re.split(r"\s+#", raw_value, maxsplit=1)[0].rstrip()
        values[key] = value
    return values


@dataclass(frozen=True)
class Config:
    api_base_url: str
    account: str
    password: str
    author: str = DEFAULT_AUTHOR

    @classmethod
    def load(cls, path: Path) -> "Config":
        file_values = parse_dotenv(path)

        def get(name: str, default: str = "") -> str:
            return os.environ.get(name, file_values.get(name, default)).strip()

        api_base_url = get("ISSUE_WIKI_API_BASE_URL").rstrip("/")
        account = get("ISSUE_WIKI_ADMIN_ACCOUNT")
        password = get("ISSUE_WIKI_ADMIN_PASSWORD")
        author = get("ISSUE_WIKI_DOCUMENT_AUTHOR", DEFAULT_AUTHOR) or DEFAULT_AUTHOR
        missing = [
            name
            for name, value in (
                ("ISSUE_WIKI_API_BASE_URL", api_base_url),
                ("ISSUE_WIKI_ADMIN_ACCOUNT", account),
                ("ISSUE_WIKI_ADMIN_PASSWORD", password),
            )
            if not value
        ]
        if missing:
            raise ConfigError("缺少配置项：" + "、".join(missing))
        parsed = urllib.parse.urlsplit(api_base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ConfigError("ISSUE_WIKI_API_BASE_URL 必须是完整的 http(s) API 地址")
        if not parsed.path.rstrip("/").endswith("/api"):
            raise ConfigError("ISSUE_WIKI_API_BASE_URL 应以 /api 结尾")
        return cls(api_base_url, account, password, author)


@dataclass(frozen=True)
class ImageAsset:
    path: Path
    relative_path: str
    digest: str
    mime_type: str
    size: int


@dataclass(frozen=True)
class ImageReference:
    start: int
    end: int
    asset_digest: str


@dataclass
class LocalDocument:
    path: Path
    relative_path: str
    folder_parts: tuple[str, ...]
    title: str
    source_content: str
    references: list[ImageReference]
    sort_order: int = 0

    def render(self, image_urls: dict[str, str]) -> str:
        content = self.source_content
        for reference in sorted(self.references, key=lambda item: item.start, reverse=True):
            try:
                url = image_urls[reference.asset_digest]
            except KeyError as exc:
                raise ValidationError(f"图片尚未上传：{self.relative_path}") from exc
            content = content[: reference.start] + url + content[reference.end :]
        return content


@dataclass(frozen=True)
class FolderSpec:
    parts: tuple[str, ...]
    sort_order: int


@dataclass
class LocalCatalog:
    documents: list[LocalDocument]
    folders: list[FolderSpec]
    assets: dict[str, ImageAsset]


INLINE_IMAGE_RE = re.compile(
    r"!\[[^\]\n]*\]\(\s*(?:<(?P<angle>[^>\n]+)>|(?P<plain>(?:\\.|[^)\s])+))"
)
HTML_IMAGE_RE = re.compile(
    r"<img\b[^>]*?\bsrc\s*=\s*(?P<quote>['\"])(?P<src>.*?)(?P=quote)", re.IGNORECASE | re.DOTALL
)
REFERENCE_USE_RE = re.compile(r"!\[(?P<alt>[^\]\n]*)\]\[(?P<label>[^\]\n]*)\]")
SHORTCUT_IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]\n]+)\](?![\[(])")
REFERENCE_DEF_RE = re.compile(
    r"(?m)^[ \t]{0,3}\[(?P<label>[^\]\n]+)\]:[ \t]*(?:<(?P<angle>[^>\n]+)>|(?P<plain>\S+))"
)


def reference_label(value: str) -> str:
    return normalized(" ".join(value.split()))


def raw_image_targets(content: str) -> list[tuple[int, int, str]]:
    found: list[tuple[int, int, str]] = []
    for match in INLINE_IMAGE_RE.finditer(content):
        group = "angle" if match.group("angle") is not None else "plain"
        found.append((match.start(group), match.end(group), match.group(group)))
    for match in HTML_IMAGE_RE.finditer(content):
        found.append((match.start("src"), match.end("src"), match.group("src")))
    definitions: dict[str, list[tuple[int, int, str]]] = {}
    for match in REFERENCE_DEF_RE.finditer(content):
        group = "angle" if match.group("angle") is not None else "plain"
        definitions.setdefault(reference_label(match.group("label")), []).append(
            (match.start(group), match.end(group), match.group(group))
        )
    used_labels = {
        reference_label(match.group("label") or match.group("alt"))
        for match in REFERENCE_USE_RE.finditer(content)
    }
    used_labels.update(reference_label(match.group("alt")) for match in SHORTCUT_IMAGE_RE.finditer(content))
    for label in used_labels:
        found.extend(definitions.get(label, []))
    return sorted({(item[0], item[1]): item for item in found}.values())


def is_remote_target(target: str) -> bool:
    lowered = target.strip().casefold()
    return (
        not lowered
        or lowered.startswith(("http://", "https://", "//", "data:", "#", "/", "mailto:"))
    )


def resolve_image(target: str, document_path: Path, source_root: Path) -> ImageAsset | None:
    target = target.strip()
    if is_remote_target(target):
        return None
    if re.match(r"^[A-Za-z]:[\\/]", target):
        raise ValidationError(f"图片不能使用绝对路径：{target}")
    parsed = urllib.parse.urlsplit(target)
    if parsed.scheme or parsed.netloc:
        return None
    relative = urllib.parse.unquote(parsed.path).replace("\\", "/")
    try:
        resolved = (document_path.parent / relative).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValidationError(f"引用图片不存在：{document_path.name} -> {target}") from exc
    root = source_root.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValidationError(f"图片路径超出使用说明目录：{document_path.name} -> {target}") from exc
    if not resolved.is_file():
        raise ValidationError(f"图片引用不是文件：{document_path.name} -> {target}")
    if resolved.suffix.casefold() not in ALLOWED_IMAGE_SUFFIXES:
        raise ValidationError(f"不支持的图片类型：{resolved.name}")
    size = resolved.stat().st_size
    if size > MAX_IMAGE_SIZE:
        raise ValidationError(f"图片超过 10MB：{resolved.name}")
    mime_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
    if not mime_type.startswith("image/"):
        raise ValidationError(f"无法识别图片 MIME 类型：{resolved.name}")
    digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    return ImageAsset(resolved, resolved.relative_to(root).as_posix(), digest, mime_type, size)


def discover_local(source_root: Path) -> LocalCatalog:
    if not source_root.is_dir():
        raise ValidationError(f"使用说明目录不存在：{source_root}")
    markdown_paths = sorted(
        (path for path in source_root.rglob("*") if path.is_file() and path.suffix.casefold() == ".md"),
        key=lambda path: natural_key(path.relative_to(source_root).as_posix()),
    )
    if not markdown_paths:
        raise ValidationError("使用说明目录中没有 Markdown 文档")
    documents: list[LocalDocument] = []
    assets: dict[str, ImageAsset] = {}
    local_keys: set[tuple[tuple[str, ...], str]] = set()
    folder_parts_set: set[tuple[str, ...]] = set()
    errors: list[str] = []
    for path in markdown_paths:
        relative = path.relative_to(source_root)
        folder_parts = tuple(relative.parent.parts) if relative.parent != Path(".") else ()
        title = path.stem
        key = (tuple(normalized(part) for part in folder_parts), normalized(title))
        if key in local_keys:
            errors.append(f"本地文档标识重复：{relative.as_posix()}")
            continue
        local_keys.add(key)
        try:
            content = path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            errors.append(f"无法以 UTF-8 读取：{relative.as_posix()} ({exc})")
            continue
        references: list[ImageReference] = []
        for start, end, target in raw_image_targets(content):
            try:
                asset = resolve_image(target, path, source_root)
            except ValidationError as exc:
                errors.append(str(exc))
                continue
            if asset is not None:
                assets.setdefault(asset.digest, asset)
                references.append(ImageReference(start, end, asset.digest))
        documents.append(LocalDocument(path, relative.as_posix(), folder_parts, title, content, references))
        for depth in range(1, len(folder_parts) + 1):
            folder_parts_set.add(folder_parts[:depth])
    if errors:
        raise ValidationError("本地预检失败：\n- " + "\n- ".join(errors))
    docs_by_folder: dict[tuple[str, ...], list[LocalDocument]] = {}
    for document in documents:
        docs_by_folder.setdefault(document.folder_parts, []).append(document)
    for group in docs_by_folder.values():
        group.sort(key=lambda item: natural_key(item.title))
        for index, document in enumerate(group, 1):
            document.sort_order = index * 10
    children: dict[tuple[str, ...], list[tuple[str, ...]]] = {}
    for parts in folder_parts_set:
        children.setdefault(parts[:-1], []).append(parts)
    folder_orders: dict[tuple[str, ...], int] = {}
    for group in children.values():
        group.sort(key=lambda parts: natural_key(parts[-1]))
        for index, parts in enumerate(group, 1):
            folder_orders[parts] = index * 10
    folders = [
        FolderSpec(parts, folder_orders[parts])
        for parts in sorted(folder_parts_set, key=lambda item: (len(item), tuple(natural_key(p) for p in item)))
    ]
    return LocalCatalog(documents, folders, assets)


class StateStore:
    def __init__(self, path: Path, api_base_url: str):
        self.path = path
        self.environment = api_base_url.rstrip("/")
        self.data: dict[str, Any] = {"version": STATE_VERSION, "environments": {}}
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValidationError(f"同步状态文件无效：{path}") from exc
            if not isinstance(loaded, dict) or loaded.get("version") != STATE_VERSION:
                raise ValidationError(f"同步状态文件版本无效：{path}")
            self.data = loaded

    @property
    def images(self) -> dict[str, dict[str, str]]:
        environment = self.data.setdefault("environments", {}).setdefault(self.environment, {})
        return environment.setdefault("images", {})

    def urls(self) -> dict[str, str]:
        return {
            digest: item["url"]
            for digest, item in self.images.items()
            if isinstance(item, dict) and isinstance(item.get("url"), str) and item["url"]
        }

    def remember(self, asset: ImageAsset, url: str) -> None:
        self.images[asset.digest] = {"url": url, "source": asset.relative_path}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(json.dumps(self.data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)


class ApiClient:
    def __init__(self, config: Config, timeout: float = 30.0):
        self.config, self.timeout, self.token = config, timeout, ""

    def _url(self, path: str, query: dict[str, Any] | None = None) -> str:
        url = self.config.api_base_url + "/" + path.lstrip("/")
        return url + ("?" + urllib.parse.urlencode(query) if query else "")

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        body: bytes | None = None,
        content_type: str | None = None,
    ) -> Any:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            content_type = "application/json; charset=utf-8"
        if content_type:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(self._url(path, query), data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = f"HTTP {exc.code}"
            try:
                body_data = json.loads(exc.read().decode("utf-8"))
                if isinstance(body_data, dict) and isinstance(body_data.get("detail"), str):
                    detail += "：" + body_data["detail"][:300]
            except (UnicodeError, json.JSONDecodeError):
                pass
            raise ApiError(f"接口请求失败 {method} {path}（{detail}）") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ApiError(f"无法连接接口 {method} {path}") from exc
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ApiError(f"接口返回了无效 JSON：{method} {path}") from exc

    def login(self) -> None:
        result = self.request("POST", "/auth/login", {"account": self.config.account, "password": self.config.password})
        token = result.get("access_token") if isinstance(result, dict) else None
        role = result.get("user", {}).get("role") if isinstance(result, dict) else None
        if not isinstance(token, str) or not token:
            raise ApiError("登录响应中缺少访问令牌")
        if role != "admin":
            raise ApiError("登录账号不是管理员")
        self.token = token

    def list_all(self, path: str) -> list[dict[str, Any]]:
        page, items = 1, []
        while True:
            result = self.request("GET", path, query={"page": page, "page_size": PAGE_SIZE})
            if not isinstance(result, dict) or not isinstance(result.get("items"), list):
                raise ApiError(f"分页接口响应无效：{path}")
            items.extend(item for item in result["items"] if isinstance(item, dict))
            pages = result.get("pages", 1)
            if not isinstance(pages, int) or pages < 1:
                raise ApiError(f"分页接口页数无效：{path}")
            if page >= pages:
                return items
            page += 1

    def upload(self, asset: ImageAsset) -> str:
        boundary = "----issue-wiki-" + uuid.uuid4().hex
        disposition = (
            'Content-Disposition: form-data; name="file"; filename="upload'
            + asset.path.suffix.casefold()
            + '"; filename*=UTF-8\'\''
            + urllib.parse.quote(asset.path.name)
        )
        body = (
            f"--{boundary}\r\n{disposition}\r\nContent-Type: {asset.mime_type}\r\n\r\n".encode("ascii")
            + asset.path.read_bytes()
            + f"\r\n--{boundary}--\r\n".encode("ascii")
        )
        result = self.request("POST", "/uploads", body=body, content_type=f"multipart/form-data; boundary={boundary}")
        url = result.get("url") if isinstance(result, dict) else None
        if not isinstance(url, str) or not url:
            raise ApiError(f"图片上传响应缺少 URL：{asset.relative_path}")
        return url


@dataclass
class RemoteIndex:
    folders_by_path: dict[tuple[str, ...], list[dict[str, Any]]]
    documents_by_key: dict[tuple[int | None, str], list[dict[str, Any]]]


def build_remote_index(folders: list[dict[str, Any]], documents: list[dict[str, Any]]) -> RemoteIndex:
    by_id = {item.get("id"): item for item in folders if isinstance(item.get("id"), int)}
    cache: dict[int, tuple[str, ...]] = {}

    def folder_path(folder_id: int, stack: set[int] | None = None) -> tuple[str, ...]:
        if folder_id in cache:
            return cache[folder_id]
        stack = set() if stack is None else set(stack)
        if folder_id in stack:
            raise ValidationError("远端文件夹存在父级循环")
        stack.add(folder_id)
        folder = by_id.get(folder_id)
        if folder is None or not isinstance(folder.get("name"), str):
            raise ValidationError(f"远端文件夹数据无效：ID {folder_id}")
        parent_id = folder.get("parent_id")
        if parent_id is None:
            parts = (folder["name"],)
        elif isinstance(parent_id, int) and parent_id in by_id:
            parts = folder_path(parent_id, stack) + (folder["name"],)
        else:
            raise ValidationError(f"远端文件夹父级不存在：ID {folder_id}")
        cache[folder_id] = parts
        return parts

    folders_by_path: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for folder_id in by_id:
        key = tuple(normalized(part) for part in folder_path(folder_id))
        folders_by_path.setdefault(key, []).append(by_id[folder_id])
    documents_by_key: dict[tuple[int | None, str], list[dict[str, Any]]] = {}
    for document in documents:
        document_id, title, folder_id = document.get("id"), document.get("title"), document.get("folder_id")
        if not isinstance(document_id, int) or not isinstance(title, str):
            raise ValidationError("远端文档数据无效")
        if folder_id is not None and not isinstance(folder_id, int):
            raise ValidationError(f"远端文档文件夹 ID 无效：ID {document_id}")
        documents_by_key.setdefault((folder_id, normalized(title)), []).append(document)
    return RemoteIndex(folders_by_path, documents_by_key)


@dataclass
class Preview:
    folders_create: int = 0
    folders_update: int = 0
    folders_skip: int = 0
    documents_create: int = 0
    documents_update: int = 0
    documents_skip: int = 0
    images_upload: int = 0
    images_reuse: int = 0
    details: list[str] = field(default_factory=list)


class SyncRunner:
    def __init__(self, config: Config, source_root: Path, state_path: Path, client: ApiClient):
        self.config = config
        self.catalog = discover_local(source_root)
        self.state = StateStore(state_path, config.api_base_url)
        self.client = client
        self.remote: RemoteIndex | None = None

    def load_remote(self) -> None:
        self.client.login()
        self.remote = build_remote_index(self.client.list_all("/admin/folders"), self.client.list_all("/admin/documents"))

    @staticmethod
    def path_key(parts: Iterable[str]) -> tuple[str, ...]:
        return tuple(normalized(part) for part in parts)

    def existing_folder(self, parts: tuple[str, ...]) -> dict[str, Any] | None:
        assert self.remote is not None
        matches = self.remote.folders_by_path.get(self.path_key(parts), [])
        if len(matches) > 1:
            raise ValidationError("远端同路径文件夹重复：" + "/".join(parts))
        return matches[0] if matches else None

    def validate_remote_conflicts(self) -> None:
        assert self.remote is not None
        for folder in self.catalog.folders:
            self.existing_folder(folder.parts)
        for document in self.catalog.documents:
            folder = self.existing_folder(document.folder_parts) if document.folder_parts else None
            if document.folder_parts and folder is None:
                continue
            folder_id = folder.get("id") if folder else None
            if len(self.remote.documents_by_key.get((folder_id, normalized(document.title)), [])) > 1:
                raise ValidationError("远端同标识文档重复：" + "/".join((*document.folder_parts, document.title)))

    def preview(self) -> Preview:
        self.load_remote()
        self.validate_remote_conflicts()
        assert self.remote is not None
        result, urls = Preview(), self.state.urls()
        result.images_reuse = sum(digest in urls for digest in self.catalog.assets)
        result.images_upload = len(self.catalog.assets) - result.images_reuse
        for folder in self.catalog.folders:
            existing = self.existing_folder(folder.parts)
            if existing is None:
                result.folders_create += 1
                result.details.append("创建文件夹 " + "/".join(folder.parts))
            elif existing.get("sort_order") != folder.sort_order:
                result.folders_update += 1
                result.details.append("更新文件夹排序 " + "/".join(folder.parts))
            else:
                result.folders_skip += 1
        for document in self.catalog.documents:
            folder = self.existing_folder(document.folder_parts) if document.folder_parts else None
            folder_id = folder.get("id") if folder else None
            matches = [] if document.folder_parts and folder is None else self.remote.documents_by_key.get(
                (folder_id, normalized(document.title)), []
            )
            existing = matches[0] if matches else None
            missing_url = any(reference.asset_digest not in urls for reference in document.references)
            rendered = None if missing_url else document.render(urls)
            if existing is None:
                result.documents_create += 1
                result.details.append("创建文档 " + document.relative_path)
            elif missing_url or existing.get("content") != rendered or existing.get("sort_order") != document.sort_order:
                result.documents_update += 1
                result.details.append("更新文档 " + document.relative_path)
            else:
                result.documents_skip += 1
        return result

    def apply(self) -> Preview:
        self.load_remote()
        self.validate_remote_conflicts()
        assert self.remote is not None
        result, urls = Preview(), self.state.urls()
        for digest, asset in self.catalog.assets.items():
            if digest in urls:
                result.images_reuse += 1
                continue
            url = self.client.upload(asset)
            self.state.remember(asset, url)
            urls[digest] = url
            result.images_upload += 1
            result.details.append("上传图片 " + asset.relative_path)
        folder_ids: dict[tuple[str, ...], int | None] = {(): None}
        for folder in self.catalog.folders:
            parent_id = folder_ids[folder.parts[:-1]]
            existing = self.existing_folder(folder.parts)
            if existing is None:
                created = self.client.request(
                    "POST", "/admin/folders", {"name": folder.parts[-1], "parent_id": parent_id, "sort_order": folder.sort_order}
                )
                if not isinstance(created, dict) or not isinstance(created.get("id"), int):
                    raise ApiError("创建文件夹响应无效：" + "/".join(folder.parts))
                existing = created
                self.remote.folders_by_path[self.path_key(folder.parts)] = [created]
                result.folders_create += 1
                result.details.append("创建文件夹 " + "/".join(folder.parts))
            elif existing.get("sort_order") != folder.sort_order:
                updated = self.client.request("PUT", f"/admin/folders/{existing['id']}", {"sort_order": folder.sort_order})
                if isinstance(updated, dict):
                    existing = updated
                    self.remote.folders_by_path[self.path_key(folder.parts)] = [updated]
                result.folders_update += 1
                result.details.append("更新文件夹排序 " + "/".join(folder.parts))
            else:
                result.folders_skip += 1
            folder_ids[folder.parts] = existing["id"]
        for document in self.catalog.documents:
            folder_id = folder_ids[document.folder_parts]
            key = (folder_id, normalized(document.title))
            matches = self.remote.documents_by_key.get(key, [])
            if len(matches) > 1:
                raise ValidationError("远端同标识文档重复：" + document.relative_path)
            existing, content = (matches[0] if matches else None), document.render(urls)
            if existing is None:
                created = self.client.request(
                    "POST",
                    "/admin/documents",
                    {"title": document.title, "content": content, "folder_id": folder_id, "author": self.config.author, "sort_order": document.sort_order},
                )
                if not isinstance(created, dict) or not isinstance(created.get("id"), int):
                    raise ApiError("创建文档响应无效：" + document.relative_path)
                self.remote.documents_by_key[key] = [created]
                result.documents_create += 1
                result.details.append("创建文档 " + document.relative_path)
            elif existing.get("content") != content or existing.get("sort_order") != document.sort_order:
                updated = self.client.request(
                    "PUT", f"/admin/documents/{existing['id']}", {"content": content, "sort_order": document.sort_order}
                )
                if isinstance(updated, dict):
                    self.remote.documents_by_key[key] = [updated]
                result.documents_update += 1
                result.details.append("更新文档 " + document.relative_path)
            else:
                result.documents_skip += 1
        return result


def print_summary(mode: str, catalog: LocalCatalog, result: Preview) -> None:
    print(f"{mode}完成：本地文档 {len(catalog.documents)}，文件夹 {len(catalog.folders)}，引用图片 {len(catalog.assets)}")
    print(
        "图片：上传 {0.images_upload}，复用 {0.images_reuse}；"
        "文件夹：创建 {0.folders_create}，更新 {0.folders_update}，跳过 {0.folders_skip}；"
        "文档：创建 {0.documents_create}，更新 {0.documents_update}，跳过 {0.documents_skip}".format(result)
    )
    for detail in result.details:
        print("- " + detail)


def repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="预览或同步使用说明到部署后的 issue-wiki 网站")
    parser.add_argument("--apply", action="store_true", help="执行写入；省略时仅预览")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    skill_root = Path(__file__).resolve().parents[1]
    try:
        config = Config.load(skill_root / ".env.local")
        runner = SyncRunner(config, repository_root() / "使用说明", skill_root / ".sync-state.local.json", ApiClient(config))
        result = runner.apply() if args.apply else runner.preview()
        print_summary("正式同步" if args.apply else "预览", runner.catalog, result)
        if not args.apply:
            print("预览未调用上传、管理员创建或更新接口；确认后使用 --apply 正式同步。")
        return 0
    except ConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2
    except ValidationError as exc:
        print(f"校验失败：{exc}", file=sys.stderr)
        return 2
    except ApiError as exc:
        print(f"同步失败：{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("操作已取消", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
