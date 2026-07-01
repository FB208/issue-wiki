from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.models import PaymentStatus, SponsorOrder
from app.services.payment import callback_is_paid, verify_callback

router = APIRouter(prefix="/payments", tags=["payments"])


@router.api_route("/zpay/callback", methods=["GET", "POST"])
async def zpay_callback(request: Request, db: Session = Depends(get_db)) -> str:
    if request.method == "POST":
        form = await request.form()
        params = {key: str(value) for key, value in form.items()}
    else:
        params = {key: str(value) for key, value in request.query_params.items()}

    if not verify_callback(params):
        return "fail"

    order_no = params.get("out_trade_no")
    if not order_no:
        return "fail"
    order = db.query(SponsorOrder).filter(SponsorOrder.merchant_order_no == order_no).first()
    if not order:
        return "fail"

    money = params.get("money") or params.get("total_amount")
    if money is None or Decimal(money).quantize(Decimal("0.01")) != Decimal(order.amount).quantize(Decimal("0.01")):
        return "fail"

    order.callback_at = datetime.now(timezone.utc)
    order.zpay_trade_no = params.get("trade_no") or order.zpay_trade_no
    if callback_is_paid(params) and order.status != PaymentStatus.paid.value:
        order.status = PaymentStatus.paid.value
        order.paid_at = datetime.now(timezone.utc)
    db.commit()
    return "success"
