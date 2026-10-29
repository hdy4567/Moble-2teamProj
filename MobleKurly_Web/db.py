"""Shared MySQL connections, based on the imported MobleKurlyFlask project."""

import os
from pathlib import Path
from threading import Lock

from dotenv import load_dotenv
from mysql.connector import Error, pooling


load_dotenv(Path(__file__).with_name(".env"))

DATABASE_NAME = "moblekurly"

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "192.168.0.90"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "moblekurly"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", DATABASE_NAME),
    "charset": "utf8mb4",
    "collation": "utf8mb4_unicode_ci",
    "connection_timeout": 5,
}

_pool = None
_pool_lock = Lock()


def get_db():
    """Lazily create one thread-safe pool; close() returns a connection to it."""
    global _pool
    if DB_CONFIG["database"] != DATABASE_NAME:
        raise Error("DB_NAME은 moblekurly만 사용할 수 있습니다.")
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = pooling.MySQLConnectionPool(
                    pool_name="moblekurly_pool",
                    pool_size=5,
                    pool_reset_session=True,
                    **DB_CONFIG,
                )
    return _pool.get_connection()
