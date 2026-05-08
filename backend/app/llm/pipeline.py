"""NL → SQL pipeline with bounded self-correction.

The model emits a candidate SQL. We:
  1. Parse + assert SELECT-only (sql_guard).
  2. Execute on the read-only MariaDB connection.

If either step fails, we append the assistant's failed turn and a user turn
containing the error, then ask for a corrected query. We loop until it
succeeds or we hit `max_attempts` (default 5, override via MLX_MAX_RETRIES).

Empty result sets count as success — there is no automated signal for "this
is the result the user wanted", so the only failure modes that drive a retry
are guard rejections and DB execution errors.
"""

import os
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db import ro_engine
from app.llm.client import chat, extract_sql, initial_messages
from app.llm.sql_guard import UnsafeSQLError, ensure_select_only


@dataclass
class Attempt:
    sql: str
    error: str | None = None
    succeeded: bool = False


@dataclass
class AskResult:
    question: str
    sql: str
    columns: list[str]
    rows: list[dict]
    attempts: list[Attempt] = field(default_factory=list)
    raw_llm_response: str = ""


def _max_attempts() -> int:
    try:
        return max(1, int(os.getenv("MLX_MAX_RETRIES", "5")))
    except ValueError:
        return 5


def _retry_user_message(error: str) -> str:
    return (
        f"That query failed with this error:\n\n{error}\n\n"
        "Carefully read the error. Identify the specific column, join, or "
        "syntax that caused it. Re-emit a single corrected ```sql fenced "
        "SELECT statement. Do not repeat the same mistake."
    )


def _execute(sql: str) -> tuple[list[str], list[dict]]:
    with ro_engine().connect() as conn:
        result = conn.execute(text(sql))
        cols = list(result.keys())
        rows = [dict(r) for r in result.mappings().all()]
    return cols, rows


def answer_question(question: str) -> AskResult:
    """Run the NL → SQL pipeline with self-correction. Always returns; the
    caller inspects `result.attempts[-1].succeeded` to know if it gave up."""

    messages = initial_messages(question)
    attempts: list[Attempt] = []
    last_raw = ""
    max_attempts = _max_attempts()

    for _ in range(max_attempts):
        last_raw = chat(messages)
        candidate = extract_sql(last_raw)

        try:
            safe_sql = ensure_select_only(candidate)
        except UnsafeSQLError as e:
            error = f"Refused unsafe SQL: {e}"
            attempts.append(Attempt(sql=candidate, error=error))
            messages.append({"role": "assistant", "content": last_raw})
            messages.append({"role": "user", "content": _retry_user_message(error)})
            continue

        try:
            cols, rows = _execute(safe_sql)
        except SQLAlchemyError as e:
            error = f"{e.__class__.__name__}: {e}"
            attempts.append(Attempt(sql=safe_sql, error=error))
            messages.append({"role": "assistant", "content": last_raw})
            messages.append({"role": "user", "content": _retry_user_message(error)})
            continue

        attempts.append(Attempt(sql=safe_sql, succeeded=True))
        return AskResult(
            question=question,
            sql=safe_sql,
            columns=cols,
            rows=rows,
            attempts=attempts,
            raw_llm_response=last_raw,
        )

    return AskResult(
        question=question,
        sql=attempts[-1].sql if attempts else "",
        columns=[],
        rows=[],
        attempts=attempts,
        raw_llm_response=last_raw,
    )
