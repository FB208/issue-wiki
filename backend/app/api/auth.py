from fastapi import APIRouter, Depends, HTTPException, status
from redis import Redis
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token, get_password_hash, verify_password
from app.dependencies import get_current_user, get_db, get_redis
from app.models import User, UserRole
from app.schemas import LoginRequest, RegisterRequest, ResetPasswordRequest, SendCodeRequest, TokenOut, UserOut
from app.services.notification import enforce_send_limit, generate_code, send_verification_code, store_code, verify_code

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/send-code")
def send_code(payload: SendCodeRequest, client: Redis = Depends(get_redis)) -> dict[str, str]:
    target = normalize_account(payload.target)
    enforce_send_limit(client, target, payload.purpose)
    code = generate_code()
    send_verification_code(target, payload.purpose, code)
    store_code(client, target, payload.purpose, code)
    return {"message": "验证码已发送"}


@router.post("/register", response_model=TokenOut)
def register(payload: RegisterRequest, db: Session = Depends(get_db), client: Redis = Depends(get_redis)) -> TokenOut:
    if bool(payload.email) == bool(payload.phone):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="邮箱或手机号必须二选一")

    target = normalize_account(str(payload.email) if payload.email else payload.phone or "")
    if not verify_code(client, target, "register", payload.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码错误或已过期")

    conditions = []
    if payload.email:
        conditions.append(User.email == str(payload.email).lower())
    if payload.phone:
        conditions.append(User.phone == payload.phone)
    exists = db.query(User).filter(or_(*conditions)).first()
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="账号已存在")

    user = User(
        email=str(payload.email).lower() if payload.email else None,
        phone=payload.phone,
        nickname=payload.nickname,
        password_hash=get_password_hash(payload.password),
        avatar_url=payload.avatar_url,
        role=UserRole.user.value,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token(str(user.id), {"role": user.role})
    return TokenOut(access_token=token, user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenOut)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenOut:
    account = normalize_account(payload.account)
    user = db.query(User).filter(or_(User.email == account, User.phone == account)).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")
    if user.is_banned:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已被封禁")
    token = create_access_token(str(user.id), {"role": user.role})
    return TokenOut(access_token=token, user=UserOut.model_validate(user))


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db), client: Redis = Depends(get_redis)) -> dict[str, str]:
    account = normalize_account(payload.account)
    user = db.query(User).filter(or_(User.email == account, User.phone == account)).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账号不存在")
    if not verify_code(client, account, "reset", payload.code):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码错误或已过期")
    user.password_hash = get_password_hash(payload.new_password)
    db.commit()
    return {"message": "密码已重置"}


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


def ensure_admin_user(db: Session) -> None:
    admin = db.query(User).filter(User.email == settings.admin_email).first()
    if admin:
        changed = False
        if admin.role != UserRole.admin.value:
            admin.role = UserRole.admin.value
            changed = True
        if settings.admin_password and not verify_password(settings.admin_password, admin.password_hash):
            admin.password_hash = get_password_hash(settings.admin_password)
            changed = True
        if changed:
            db.commit()
        return

    admin = User(
        email=settings.admin_email,
        phone=None,
        nickname=settings.admin_nickname,
        password_hash=get_password_hash(settings.admin_password),
        role=UserRole.admin.value,
    )
    db.add(admin)
    db.commit()


def normalize_account(value: str) -> str:
    value = value.strip()
    return value.lower() if "@" in value else value
