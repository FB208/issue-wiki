import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import PaymentChannel, PaymentStatus, SponsorOrder, Task

FEATURE_ID_PATTERN = re.compile(r"\bIW-TASK-(\d+)\b", re.IGNORECASE)


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


def parse_order_amount(value: Any) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("invalid total_amount") from exc


def resolve_task_from_remark(db: Session, remark: str | None) -> Task | None:
    task_id = parse_task_id_from_remark(remark)
    if task_id is None:
        return None
    return db.get(Task, task_id)


def string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
