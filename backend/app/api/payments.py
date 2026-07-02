from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.dependencies import get_current_user_optional, get_db
from app.models import PaymentChannel, PaymentStatus, SponsorOrder, User
from app.schemas import PaymentConfigOut, PaymentSummaryOut, SponsorCreate, SponsorIntentOut, SponsorOrderOut
from app.services.payment import (
    PaymentConfigError,
    PaymentProviderError,
    PaymentValidationError,
    active_payment_channel,
    afdian_order_is_paid,
    build_afdian_sponsor_url,
    build_xorpay_qr_image_url,
    create_xorpay_sponsor_order,
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


@router.get("/summary", response_model=PaymentSummaryOut)
def payment_summary(db: Session = Depends(get_db)) -> PaymentSummaryOut:
    paid_amount = db.query(func.coalesce(func.sum(SponsorOrder.amount), 0)).filter(
        SponsorOrder.status == PaymentStatus.paid.value,
    ).scalar()
    return PaymentSummaryOut(paid_amount=paid_amount or 0)


@router.get("/orders/{merchant_order_no}", response_model=SponsorOrderOut)
def get_payment_order(merchant_order_no: str, db: Session = Depends(get_db)) -> SponsorOrderOut:
    order = db.query(SponsorOrder).filter(SponsorOrder.merchant_order_no == merchant_order_no).first()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="订单不存在")
    return order


@router.post("/tip", response_model=SponsorIntentOut)
def create_author_tip_order(
    payload: SponsorCreate | None = None,
    user: User | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
) -> SponsorIntentOut:
    if user and user.is_banned:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已被封禁")

    try:
        channel = active_payment_channel()
    except PaymentConfigError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if channel == PaymentChannel.afdian.value:
        payment_url = build_afdian_sponsor_url()
        if not payment_url:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="爱发电赞助链接未配置")
        return SponsorIntentOut(
            channel=PaymentChannel.afdian.value,
            payment_url=payment_url,
            instructions="前往爱发电后可直接打赏作者，无需填写功能 ID。",
        )

    try:
        order, result = create_xorpay_sponsor_order(db, None, user, payload.amount if payload else None)
    except (PaymentConfigError, PaymentValidationError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except PaymentProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return SponsorIntentOut(
        channel=PaymentChannel.xorpay.value,
        instructions="请使用微信扫描二维码完成打赏，支付成功后系统会自动记录订单。",
        order_id=order.id,
        merchant_order_no=order.merchant_order_no,
        amount=order.amount,
        min_amount=xorpay_min_order_amount(),
        status=order.status,
        qr=order.xorpay_qr,
        qr_image_url=build_xorpay_qr_image_url(order.xorpay_qr),
        expires_in=int(result.get("expires_in") or result.get("expire_in") or 0) or None,
    )


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
