from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.dependencies import get_db
from app.models import SponsorOrder
from app.schemas import PaymentConfigOut, SponsorOrderOut
from app.services.payment import (
    PaymentConfigError,
    PaymentProviderError,
    PaymentValidationError,
    active_payment_channel,
    afdian_order_is_paid,
    extract_afdian_order,
    process_afdian_order,
    process_xorpay_notify,
    xorpay_min_order_amount,
)

router = APIRouter(prefix="/payments", tags=["payments"])


@router.get("/config", response_model=PaymentConfigOut)
def payment_config() -> PaymentConfigOut:
    try:
        channel = active_payment_channel()
    except PaymentConfigError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return PaymentConfigOut(channel=channel, xorpay_min_order_amount=xorpay_min_order_amount())


@router.get("/orders/{merchant_order_no}", response_model=SponsorOrderOut)
def get_payment_order(merchant_order_no: str, db: Session = Depends(get_db)) -> SponsorOrderOut:
    order = db.query(SponsorOrder).filter(SponsorOrder.merchant_order_no == merchant_order_no).first()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订单不存在")
    return order


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


@router.post("/xorpay/notify")
async def xorpay_notify(request: Request, db: Session = Depends(get_db)) -> PlainTextResponse:
    form = dict(await request.form())
    try:
        process_xorpay_notify(db, form)
    except (PaymentConfigError, PaymentValidationError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except PaymentProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return PlainTextResponse("ok")
