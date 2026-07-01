from functools import lru_cache
from decimal import Decimal
from urllib.parse import urlparse

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Issue Wiki"
    env: str = "development"
    api_prefix: str = "/api"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    github_project_url: str = "https://github.com/example/project"
    github_sync_enabled: bool = False
    github_token: str = ""
    github_webhook_secret: str = ""
    github_api_base_url: str = "https://api.github.com"

    database_url: str = "mysql+pymysql://issue_wiki:issue_wiki@127.0.0.1:3306/issue_wiki?charset=utf8mb4"
    redis_url: str = "redis://127.0.0.1:6379/0"

    jwt_secret: str = Field(default="change-me-in-env")
    jwt_algorithm: str = "HS256"
    jwt_expire_days: int = 3650

    admin_email: str = "admin@example.com"
    admin_password: str = "admin123456"
    admin_nickname: str = "生产力Mark"

    payment_channel: str = "afdian"

    afdian_sponsor_url: str = ""
    afdian_webhook_secret: str = ""
    afdian_user_id: str = ""
    afdian_api_token: str = ""
    afdian_api_base_url: str = "https://afdian.net/api/open"

    xorpay_aid: str = ""
    xorpay_app_secret: str = ""
    xorpay_notify_url: str = ""
    xorpay_min_order_amount: Decimal = Decimal("1.00")
    xorpay_api_base_url: str = "https://xorpay.com"
    xorpay_order_expire_seconds: int = 7200

    gmail_smtp_host: str = "smtp.gmail.com"
    gmail_smtp_port: int = 587
    gmail_username: str = ""
    gmail_password: str = ""
    gmail_from: str = ""

    aliyun_access_key_id: str = ""
    aliyun_access_key_secret: str = ""

    rustfs_endpoint_url: str = ""
    rustfs_access_key_id: str = ""
    rustfs_secret_access_key: str = ""
    rustfs_bucket: str = ""
    rustfs_public_base_url: str = ""
    rustfs_secure: bool = True

    upload_max_size: int = 10 * 1024 * 1024
    upload_allowed_extensions: str = ".jpg,.jpeg,.png,.gif,.webp,.pdf,.doc,.docx,.xls,.xlsx,.md"
    upload_allowed_mime_prefixes: str = "image/"
    upload_allowed_mime_types: str = "application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/markdown,text/plain"

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def allowed_extension_set(self) -> set[str]:
        return {item.strip().lower() for item in self.upload_allowed_extensions.split(",") if item.strip()}

    @property
    def allowed_mime_type_set(self) -> set[str]:
        return {item.strip().lower() for item in self.upload_allowed_mime_types.split(",") if item.strip()}

    @property
    def allowed_mime_prefix_list(self) -> list[str]:
        return [item.strip().lower() for item in self.upload_allowed_mime_prefixes.split(",") if item.strip()]

    @property
    def github_repo(self) -> str:
        parsed = urlparse(self.github_project_url)
        path = parsed.path.strip("/")
        if path.endswith(".git"):
            path = path[:-4]
        parts = [item for item in path.split("/") if item]
        if len(parts) < 2:
            return ""
        return f"{parts[0]}/{parts[1]}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
