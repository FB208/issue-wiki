from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.config import settings


def initialize_database() -> None:
    ensure_mysql_database()
    upgrade_schema()


def ensure_mysql_database() -> None:
    url = make_url(settings.database_url)
    if not url.get_backend_name().startswith("mysql") or not url.database:
        return

    server_url = url.set(database=None)
    engine = create_engine(server_url, pool_pre_ping=True, future=True)
    database = url.database.replace("`", "``")
    try:
        with engine.begin() as connection:
            connection.execute(text(f"CREATE DATABASE IF NOT EXISTS `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))
    finally:
        engine.dispose()


def upgrade_schema() -> None:
    backend_dir = Path(__file__).resolve().parents[2]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    command.upgrade(config, "head")
