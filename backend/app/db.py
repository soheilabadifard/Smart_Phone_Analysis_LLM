"""Engine factories: one read-write (admin) and one read-only (LLM Ask path)."""

import os
import sys
from functools import lru_cache

from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from database_eng import create_table

load_dotenv()


def _env(name: str, default: str | None = None) -> str:
    val = os.getenv(name, default)
    if val is None:
        raise RuntimeError(f"Missing required env var {name}")
    return val


@lru_cache(maxsize=1)
def rw_engine():
    return create_table(
        username=_env("DB_USER"),
        password=_env("DB_PASSWORD"),
        db_name=_env("DB_NAME"),
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "3306")),
    )


@lru_cache(maxsize=1)
def ro_engine():
    return create_table(
        username=_env("DB_RO_USER", "gsm_readonly"),
        password=_env("DB_RO_PASSWORD"),
        db_name=_env("DB_NAME"),
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "3306")),
    )
