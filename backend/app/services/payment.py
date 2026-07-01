import hashlib
import time
from decimal import Decimal
from urllib.parse import urlencode
from uuid import uuid4

from app.core.config import settings
from app.models import SponsorOrder


def build_merchant_order_no() -> str:
    return f"IW{int(time.time() * 1000)}{uuid4().hex[:8].upper()}"


def build_zpay_payment_url(order: SponsorOrder, task_name: str) -> str | None:
    if not settings.zpay_gateway_url or not settings.zpay_pid or not settings.zpay_key:
        return None

    params = {
        "pid": settings.zpay_pid,
        "type": "alipay",
        "out_trade_no": order.merchant_order_no,
        "notify_url": settings.zpay_notify_url,
        "return_url": settings.zpay_return_url,
        "name": task_name[:120],
        "money": format(Decimal(order.amount), ".2f"),
    }
    params["sign"] = sign_params(params)
    params["sign_type"] = "MD5"
    return f"{settings.zpay_gateway_url}?{urlencode(params)}"


def sign_params(params: dict[str, str]) -> str:
    filtered = {k: v for k, v in params.items() if k not in {"sign", "sign_type"} and v is not None and v != ""}
    source = "&".join(f"{k}={filtered[k]}" for k in sorted(filtered)) + settings.zpay_key
    return hashlib.md5(source.encode("utf-8")).hexdigest()


def verify_callback(params: dict[str, str]) -> bool:
    if not params.get("sign") or not settings.zpay_key:
        return False
    return sign_params(params) == params.get("sign")


def callback_is_paid(params: dict[str, str]) -> bool:
    value = (params.get("trade_status") or params.get("status") or "").upper()
    return value in {"TRADE_SUCCESS", "TRADE_FINISHED", "SUCCESS", "PAID"}
