import hashlib
import hmac
import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.dependencies import get_db
from app.services.github_sync import finish_sync_event, process_github_webhook, start_sync_event

router = APIRouter(prefix="/github", tags=["github"])


@router.post("/webhook")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    x_github_event: str | None = Header(default=None, alias="X-GitHub-Event"),
    x_github_delivery: str | None = Header(default=None, alias="X-GitHub-Delivery"),
    db: Session = Depends(get_db),
) -> dict:
    body = await request.body()
    if not settings.github_sync_enabled:
        return {"status": "ignored", "message": "GitHub 同步未启用"}
    verify_signature(body, x_hub_signature_256)
    if not x_github_event:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少 X-GitHub-Event")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="payload 不是合法 JSON") from exc

    event_record, should_process = start_sync_event(db, x_github_delivery, x_github_event, payload.get("action"))
    if not should_process:
        return {"status": "ignored", "message": "重复 webhook delivery"}

    try:
        result = process_github_webhook(db, x_github_event, payload)
        finish_sync_event(
            db,
            event_record,
            "ignored" if result.get("status") == "ignored" else "success",
            result.get("target_type"),
            result.get("target_id"),
            result.get("message"),
        )
        return result
    except Exception as exc:
        finish_sync_event(db, event_record, "failed", error=str(exc))
        return {"status": "failed", "message": str(exc)}


def verify_signature(body: bytes, signature: str | None) -> None:
    if not settings.github_webhook_secret:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="GITHUB_WEBHOOK_SECRET 未配置")
    if not signature:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="缺少 GitHub webhook 签名")
    expected = "sha256=" + hmac.new(settings.github_webhook_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="GitHub webhook 签名校验失败")
