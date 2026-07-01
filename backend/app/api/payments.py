from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.dependencies import get_db
from app.services.payment import afdian_order_is_paid, extract_afdian_order, process_afdian_order

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("/afdian/webhook")
def afdian_webhook(
    payload: dict[str, Any],
    secret: str | None = Query(default=None),
    x_afdian_webhook_secret: str | None = Header(default=None, alias="X-Afdian-Webhook-Secret"),
    db: Session = Depends(get_db),
) -> dict[str, int | str]:
    expected_secret = settings.afdian_webhook_secret.strip()
    provided_secret = secret or x_afdian_webhook_secret or ""
    if expected_secret and provided_secret != expected_secret:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid webhook secret")

    order_payload = extract_afdian_order(payload)
    if not order_payload:
        return {"ec": 200, "em": ""}
    if not afdian_order_is_paid(order_payload):
        return {"ec": 200, "em": ""}

    try:
        process_afdian_order(db, order_payload)
    except ValueError as exc:
        return {"ec": 400, "em": str(exc)}

    return {"ec": 200, "em": ""}
