import hashlib
import hmac
import json
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import PaymentChannel, PaymentStatus, SponsorOrder, Task

FEATURE_ID_PATTERN = re.compile(r"\bIW-TASK-(\d+)\b", re.IGNORECASE)
XORPAY_PAY_TYPE = "native"
XORPAY_PAID_STATUSES = {"payed", "success"}


class PaymentConfigError(ValueError):
    pass


class PaymentValidationError(ValueError):
    pass


class PaymentProviderError(RuntimeError):
    pass


def active_payment_channel() -> str:
    channel = (settings.payment_channel or PaymentChannel.afdian.value).strip().lower()
    allowed = {PaymentChannel.afdian.value, PaymentChannel.xorpay.value}
    if channel not in allowed:
        raise PaymentConfigError("PAYMENT_CHANNEL 只能配置为 xorpay 或 afdian")
    return channel


def build_task_feature_id(task_id: int) -> str:
    return f"IW-TASK-{task_id}"


def parse_task_id_from_remark(remark: str | None) -> int | None:
    if not remark:
        return None
    match = FEATURE_ID_PATTERN.search(remark)
    return int(match.group(1)) if match else None


def build_afdian_sponsor_url() -> str | None:
    return settings.afdian_sponsor_url.strip() or None


def sponsor_instructions(feature_id: str) -> str:
    return f"去爱发电赞助时，请在备注/留言中填写功能 ID：{feature_id}。不填写时会记录为赞助作者，不会增加到具体功能的已赞助金额。"


def extract_afdian_order(payload: dict[str, Any]) -> dict[str, Any] | None:
    data = payload.get("data")
    if isinstance(data, dict):
        if data.get("type") and data.get("type") != "order":
            return None
        order = data.get("order")
        if isinstance(order, dict):
            return order
    order = payload.get("order")
    if isinstance(order, dict):
        return order
    return payload if payload.get("out_trade_no") else None


def afdian_order_is_paid(order_payload: dict[str, Any]) -> bool:
    try:
        return int(order_payload.get("status") or 0) == 2
    except (TypeError, ValueError):
        return False


def process_afdian_order(db: Session, order_payload: dict[str, Any]) -> SponsorOrder:
    out_trade_no = str(order_payload.get("out_trade_no") or "").strip()
    if not out_trade_no:
        raise ValueError("missing out_trade_no")

    amount = parse_order_amount(order_payload.get("total_amount"))
    remark = str(order_payload.get("remark") or "")
    task = resolve_task_from_remark(db, remark)
    now = datetime.now(timezone.utc)

    order = (
        db.query(SponsorOrder)
        .filter(or_(SponsorOrder.afdian_order_no == out_trade_no, SponsorOrder.merchant_order_no == out_trade_no))
        .first()
    )
    if order is None:
        order = SponsorOrder(
            task_id=task.id if task else None,
            user_id=None,
            is_guest=True,
            merchant_order_no=out_trade_no,
            afdian_order_no=out_trade_no,
            amount=amount,
            channel=PaymentChannel.afdian.value,
            status=PaymentStatus.paid.value,
            paid_at=now,
            callback_at=now,
        )
        db.add(order)
    else:
        order.task_id = task.id if task else None
        order.amount = amount
        order.channel = PaymentChannel.afdian.value
        order.status = PaymentStatus.paid.value
        order.paid_at = order.paid_at or now
        order.callback_at = now

    order.afdian_order_no = out_trade_no
    order.afdian_user_id = string_or_none(order_payload.get("user_id"))
    order.afdian_user_private_id = string_or_none(order_payload.get("user_private_id"))
    order.afdian_plan_id = string_or_none(order_payload.get("plan_id"))
    order.afdian_remark = remark
    db.commit()
    db.refresh(order)
    return order


def create_xorpay_sponsor_order(db: Session, task: Task, user: Any, amount_value: Any) -> tuple[SponsorOrder, dict[str, Any]]:
    if amount_value is None:
        raise PaymentValidationError("请输入赞助金额")
    amount = parse_order_amount(amount_value)
    if amount <= 0:
        raise PaymentValidationError("赞助金额必须大于 0")
    min_amount = xorpay_min_order_amount()
    if amount < min_amount:
        raise PaymentValidationError(f"赞助金额不能低于 ¥{format_amount(min_amount)}")
    validate_xorpay_settings()

    order = SponsorOrder(
        task_id=task.id,
        user_id=getattr(user, "id", None),
        is_guest=user is None,
        merchant_order_no=generate_merchant_order_no(task.id),
        amount=amount,
        channel=PaymentChannel.xorpay.value,
        status=PaymentStatus.pending.value,
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    payload = build_xorpay_pay_payload(task, order, user)
    try:
        result = call_xorpay_pay(payload)
    except PaymentProviderError as exc:
        mark_xorpay_order_failed(db, order, str(exc))
        raise

    if result.get("status") != "ok":
        mark_xorpay_order_failed(db, order, json_dumps(result))
        raise PaymentProviderError(xorpay_error_message(result))

    qr = string_or_none((result.get("info") or {}).get("qr") if isinstance(result.get("info"), dict) else None)
    if not qr:
        mark_xorpay_order_failed(db, order, json_dumps(result))
        raise PaymentProviderError("XorPay 未返回支付二维码")

    order.xorpay_aoid = string_or_none(result.get("aoid"))
    order.xorpay_qr = qr
    order.xorpay_detail = json_dumps(result)
    order.status = PaymentStatus.pending.value
    db.commit()
    db.refresh(order)
    return order, result


def process_xorpay_notify(db: Session, form: dict[str, Any]) -> SponsorOrder:
    validate_xorpay_settings()
    aoid = required_text(form, "aoid")
    merchant_order_no = required_text(form, "order_id")
    pay_price_text = required_text(form, "pay_price")
    pay_time_text = required_text(form, "pay_time")
    provided_sign = required_text(form, "sign")
    expected_sign = xorpay_sign(aoid, merchant_order_no, pay_price_text, pay_time_text, settings.xorpay_app_secret)
    if not hmac.compare_digest(provided_sign, expected_sign):
        raise PaymentValidationError("XorPay 回调签名错误")

    order = db.query(SponsorOrder).filter(SponsorOrder.merchant_order_no == merchant_order_no).first()
    if order is None:
        raise PaymentValidationError("本地订单不存在")
    if order.channel != PaymentChannel.xorpay.value:
        raise PaymentValidationError("订单渠道不匹配")

    paid_amount = parse_order_amount(pay_price_text)
    if paid_amount != parse_order_amount(order.amount):
        raise PaymentValidationError("XorPay 回调金额与本地订单不一致")

    query_result = query_xorpay_order(merchant_order_no)
    if query_result.get("status") not in XORPAY_PAID_STATUSES:
        raise PaymentProviderError(f"XorPay 订单尚未确认支付：{query_result.get('status') or 'unknown'}")

    now = datetime.now(timezone.utc)
    order.status = PaymentStatus.paid.value
    order.paid_at = order.paid_at or parse_xorpay_pay_time(pay_time_text) or now
    order.callback_at = now
    order.xorpay_aoid = aoid
    order.xorpay_pay_time = parse_xorpay_pay_time(pay_time_text)
    order.xorpay_detail = string_or_none(form.get("detail")) or json_dumps(query_result)
    db.commit()
    db.refresh(order)
    return order


def build_xorpay_qr_image_url(qr: str | None) -> str | None:
    if not qr:
        return None
    return f"{xorpay_base_url()}/qr?data={quote(qr, safe='')}"


def xorpay_min_order_amount() -> Decimal:
    amount = parse_order_amount(settings.xorpay_min_order_amount)
    return amount if amount > 0 else Decimal("0.01")


def parse_order_amount(value: Any) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("invalid amount") from exc


def resolve_task_from_remark(db: Session, remark: str | None) -> Task | None:
    task_id = parse_task_id_from_remark(remark)
    if task_id is None:
        return None
    return db.get(Task, task_id)


def validate_xorpay_settings() -> None:
    missing = []
    if not settings.xorpay_aid.strip():
        missing.append("XORPAY_AID")
    if not settings.xorpay_app_secret.strip():
        missing.append("XORPAY_APP_SECRET")
    if not settings.xorpay_notify_url.strip():
        missing.append("XORPAY_NOTIFY_URL")
    if missing:
        raise PaymentConfigError(f"XorPay 配置不完整：{', '.join(missing)}")


def build_xorpay_pay_payload(task: Task, order: SponsorOrder, user: Any) -> dict[str, str]:
    name = f"赞助：{task.name}"[:120]
    price = format_amount(parse_order_amount(order.amount))
    notify_url = settings.xorpay_notify_url.strip()
    payload = {
        "name": name,
        "pay_type": XORPAY_PAY_TYPE,
        "price": price,
        "order_id": order.merchant_order_no,
        "notify_url": notify_url,
        "more": build_task_feature_id(task.id),
        "expire": str(max(60, settings.xorpay_order_expire_seconds)),
    }
    order_uid = xorpay_order_uid(user)
    if order_uid:
        payload["order_uid"] = order_uid
    payload["sign"] = xorpay_sign(name, XORPAY_PAY_TYPE, price, order.merchant_order_no, notify_url, settings.xorpay_app_secret)
    return payload


def call_xorpay_pay(payload: dict[str, str]) -> dict[str, Any]:
    url = f"{xorpay_base_url()}/api/pay/{settings.xorpay_aid.strip()}"
    try:
        response = httpx.post(url, data=payload, timeout=15)
        data = response.json()
    except httpx.HTTPError as exc:
        raise PaymentProviderError(f"XorPay 下单请求失败：{exc}") from exc
    except ValueError as exc:
        raise PaymentProviderError("XorPay 下单返回不是 JSON") from exc
    if response.status_code >= 400:
        raise PaymentProviderError(f"XorPay 下单 HTTP {response.status_code}：{json_dumps(data)}")
    return data if isinstance(data, dict) else {"status": "invalid_response", "raw": data}


def query_xorpay_order(merchant_order_no: str) -> dict[str, Any]:
    sign = xorpay_sign(merchant_order_no, settings.xorpay_app_secret)
    url = f"{xorpay_base_url()}/api/query2/{settings.xorpay_aid.strip()}"
    try:
        response = httpx.get(url, params={"order_id": merchant_order_no, "sign": sign}, timeout=15)
        data = response.json()
    except httpx.HTTPError as exc:
        raise PaymentProviderError(f"XorPay 订单查询失败：{exc}") from exc
    except ValueError as exc:
        raise PaymentProviderError("XorPay 订单查询返回不是 JSON") from exc
    if response.status_code >= 400:
        raise PaymentProviderError(f"XorPay 订单查询 HTTP {response.status_code}：{json_dumps(data)}")
    return data if isinstance(data, dict) else {"status": "invalid_response", "raw": data}


def mark_xorpay_order_failed(db: Session, order: SponsorOrder, detail: str) -> None:
    order.status = PaymentStatus.failed.value
    order.xorpay_detail = detail
    db.commit()


def xorpay_sign(*parts: Any) -> str:
    text = "".join(str(part) for part in parts)
    return hashlib.md5(text.encode("utf-8")).hexdigest().lower()


def generate_merchant_order_no(task_id: int) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"IWX-{task_id}-{timestamp}-{uuid.uuid4().hex[:10]}"


def xorpay_order_uid(user: Any) -> str | None:
    if user is None:
        return None
    return string_or_none(getattr(user, "email", None)) or string_or_none(getattr(user, "phone", None)) or f"user-{user.id}"


def xorpay_base_url() -> str:
    return (settings.xorpay_api_base_url or "https://xorpay.com").strip().rstrip("/")


def format_amount(amount: Decimal) -> str:
    return format(amount.quantize(Decimal("0.01")), ".2f")


def parse_xorpay_pay_time(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def required_text(payload: dict[str, Any], key: str) -> str:
    value = string_or_none(payload.get(key))
    if not value:
        raise PaymentValidationError(f"XorPay 回调缺少参数：{key}")
    return value


def xorpay_error_message(result: dict[str, Any]) -> str:
    status = result.get("status") or "unknown"
    info = result.get("info")
    return f"XorPay 下单失败：{status}{f'，{info}' if info else ''}"


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
