from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import boto3
from fastapi import HTTPException, UploadFile, status

from app.core.config import settings


def validate_upload_file(filename: str, content_type: str, size: int) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in settings.allowed_extension_set:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不支持的文件类型")

    mime = (content_type or "").lower()
    allowed_by_exact = mime in settings.allowed_mime_type_set
    allowed_by_prefix = any(mime.startswith(prefix) for prefix in settings.allowed_mime_prefix_list)
    if not allowed_by_exact and not allowed_by_prefix:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不支持的 MIME 类型")

    if size > settings.upload_max_size:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件大小不能超过 10MB")
    return suffix


def upload_to_rustfs(file: UploadFile, data: bytes, suffix: str) -> tuple[str, str]:
    if not all([settings.rustfs_endpoint_url, settings.rustfs_access_key_id, settings.rustfs_secret_access_key, settings.rustfs_bucket]):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="RustFS 文件存储未配置")

    object_key = f"issue-wiki/{uuid4().hex}{suffix}"
    client = boto3.client(
        "s3",
        endpoint_url=settings.rustfs_endpoint_url,
        aws_access_key_id=settings.rustfs_access_key_id,
        aws_secret_access_key=settings.rustfs_secret_access_key,
    )
    client.put_object(Bucket=settings.rustfs_bucket, Key=object_key, Body=data, ContentType=file.content_type)

    url = build_public_url(object_key)
    return object_key, url


def build_public_url(object_key: str) -> str:
    base_url = settings.rustfs_public_base_url or settings.rustfs_endpoint_url
    base = base_url.rstrip("/")
    path_parts = [part for part in urlparse(base).path.split("/") if part]
    if path_parts and path_parts[-1] == settings.rustfs_bucket:
        return f"{base}/{object_key}"
    return f"{base}/{settings.rustfs_bucket}/{object_key}"
