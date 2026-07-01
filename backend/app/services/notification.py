import json
import random
import smtplib
from email.message import EmailMessage

from aliyunsdkcore.acs_exception.exceptions import ClientException, ServerException
from aliyunsdkcore.client import AcsClient
from aliyunsdkdypnsapi.request.v20170525.SendSmsVerifyCodeRequest import SendSmsVerifyCodeRequest
from fastapi import HTTPException, status
import redis

from app.core.config import settings


ALIYUN_REGION_ID = "cn-hangzhou"
ALIYUN_SMS_SIGN_NAME = "速通互联验证码"
ALIYUN_SMS_TEMPLATE_CODE = "100001"
ALIYUN_SMS_VALID_TIME = 300


def generate_code() -> str:
    return f"{random.randint(100000, 999999)}"


def infer_channel(target: str) -> str:
    return "email" if "@" in target else "phone"


def send_verification_code(target: str, purpose: str, code: str) -> None:
    channel = infer_channel(target)
    if channel == "email":
        send_email_code(target, purpose, code)
        return
    send_sms_code(target, purpose, code)


def send_email_code(email: str, purpose: str, code: str) -> None:
    if not settings.gmail_username or not settings.gmail_password:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="邮箱服务未配置")

    message = EmailMessage()
    message["Subject"] = "Issue Wiki 验证码"
    message["From"] = settings.gmail_from or settings.gmail_username
    message["To"] = email
    message.set_content(f"你的验证码是：{code}\n用途：{purpose}\n请勿泄露给他人。")

    with smtplib.SMTP(settings.gmail_smtp_host, settings.gmail_smtp_port, timeout=20) as smtp:
        smtp.starttls()
        smtp.login(settings.gmail_username, settings.gmail_password)
        smtp.send_message(message)


def send_sms_code(phone: str, purpose: str, code: str) -> None:
    if not all([settings.aliyun_access_key_id, settings.aliyun_access_key_secret]):
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="短信服务未配置")

    client = AcsClient(settings.aliyun_access_key_id, settings.aliyun_access_key_secret, ALIYUN_REGION_ID)
    request = SendSmsVerifyCodeRequest()
    request.set_PhoneNumber(phone)
    request.set_CountryCode("86")
    request.set_SignName(ALIYUN_SMS_SIGN_NAME)
    request.set_TemplateCode(ALIYUN_SMS_TEMPLATE_CODE)
    request.set_TemplateParam(json.dumps({"code": code, "min": str(ALIYUN_SMS_VALID_TIME // 60)}, ensure_ascii=False))
    request.set_ValidTime(ALIYUN_SMS_VALID_TIME)
    request.set_DuplicatePolicy(1)
    request.set_Interval(60)

    try:
        response = client.do_action_with_exception(request)
        result = json.loads(response.decode("utf-8"))
    except (ClientException, ServerException, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="短信验证码发送失败") from exc

    if result.get("Code") != "OK" or result.get("Success") is not True:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="短信验证码发送失败")


def store_code(client: redis.Redis, target: str, purpose: str, code: str) -> None:
    client.setex(code_key(target, purpose), 10 * 60, code)


def verify_code(client: redis.Redis, target: str, purpose: str, code: str) -> bool:
    key = code_key(target, purpose)
    stored = client.get(key)
    if stored and stored == code:
        client.delete(key)
        return True
    return False


def enforce_send_limit(client: redis.Redis, target: str, purpose: str) -> None:
    key = f"verify-limit:{purpose}:{target}"
    count = client.incr(key)
    if count == 1:
        client.expire(key, 24 * 60 * 60)
    if count > 2:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="每日验证码发送次数已达上限")


def code_key(target: str, purpose: str) -> str:
    return f"verify-code:{purpose}:{target}"
