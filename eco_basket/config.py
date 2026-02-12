import os
from typing import Any


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def ensure_mysql_database_exists() -> None:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url.lower().startswith("mysql"):
        return

    try:
        from sqlalchemy.engine.url import make_url
    except Exception as exc:  # pragma: no cover - defensive import guard
        print(f"[bootstrap] Unable to parse DATABASE_URL: {exc}")
        return

    try:
        import pymysql
    except Exception as exc:  # pragma: no cover - dependency guard
        print(f"[bootstrap] PyMySQL unavailable, skipping DB bootstrap: {exc}")
        return

    conn = None
    try:
        parsed = make_url(database_url)
        db_name = parsed.database
        if not db_name:
            return

        host = parsed.host or os.getenv("DB_HOST", "localhost")
        port = parsed.port or _int_or_default(os.getenv("DB_PORT"), 3306)
        user = parsed.username or os.getenv("DB_USER", "root")
        password = parsed.password or os.getenv("DB_PASSWORD", "")

        conn = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            charset="utf8mb4",
            autocommit=True,
        )
        with conn.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
    except Exception as exc:
        print(f"[bootstrap] MySQL database bootstrap skipped: {exc}")
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
