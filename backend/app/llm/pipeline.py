"""NL → SQL pipeline with bounded self-correction and result review.

The model emits a candidate SQL. We:
  1. Parse + assert SELECT-only (sql_guard).
  2. Execute on the read-only MariaDB connection.
  3. (Optional, on by default) Send the result preview back to the model and
     ask whether it actually answers the question. The model either replies
     `OK` (we accept and return) or emits a refined SQL in a fenced block.

If guard / execution / refinement fails, we append the assistant's failed
turn and a user turn containing the error or judgment, then ask again. We
loop until the model signs off or we hit `max_attempts` (default 5,
override via MLX_MAX_RETRIES).

Empty result sets are treated as a valid answer when the model approves
them, but the model is allowed to refine if it spots a fixable filter
mistake. Oscillation guard: if the model emits a SQL we've already tried,
we stop and accept the last successful result.

The chat() call structure: one call before the loop produces the initial
candidate, then each loop iteration runs guard + execute + (optionally)
review. The review either approves (return) or emits a refinement which
is consumed directly by the next iteration. So chat() is called once
per round — never redundantly at the top of the loop.
"""

import os
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db import ro_engine
from app.llm.client import (
    chat,
    explanation_messages,
    extract_sql,
    format_result_preview,
    has_fenced_sql,
    initial_messages,
    review_user_message,
    strip_code_fences,
)
from app.llm.sql_guard import UnsafeSQLError, ensure_select_only


@dataclass
class Attempt:
    sql: str
    error: str | None = None
    succeeded: bool = False
    # 'execution' = SQL was guarded + run; 'review' = LLM was shown the result
    # and either approved (succeeded=True with judgment text) or proposed a
    # refinement (succeeded=False, judgment carries the model's reasoning).
    kind: str = "execution"
    judgment: str | None = None


@dataclass
class AskResult:
    question: str
    sql: str
    columns: list[str]
    rows: list[dict]
    attempts: list[Attempt] = field(default_factory=list)
    raw_llm_response: str = ""
    explanation: str | None = None


def _max_attempts() -> int:
    try:
        return max(1, int(os.getenv("MLX_MAX_RETRIES", "5")))
    except ValueError:
        return 5


def _verify_results_enabled() -> bool:
    return os.getenv("MLX_VERIFY_RESULTS", "true").lower() not in {"false", "0", "no"}


def _explain_results_enabled() -> bool:
    return os.getenv("MLX_EXPLAIN_RESULTS", "true").lower() not in {"false", "0", "no"}


def _preview_rows() -> int:
    try:
        return max(1, int(os.getenv("MLX_VERIFY_PREVIEW_ROWS", "10")))
    except ValueError:
        return 10


def _explain_result(question: str, sql: str,
                    cols: list[str], rows: list[dict]) -> str | None:
    """Ask the LLM for a 2-4 sentence plain-English summary of the result.

    Self-contained: builds a fresh chat conversation with its own system
    prompt and a single user turn carrying the question, SQL, and result
    preview. Returns None if explanations are disabled or the model emits
    nothing usable.
    """
    if not _explain_results_enabled():
        return None
    preview = format_result_preview(cols, rows, max_rows=_preview_rows())
    raw = chat(explanation_messages(question, sql, preview))
    cleaned = strip_code_fences(raw)
    return cleaned or None


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
    """Run the NL → SQL pipeline with self-correction + result review.

    Always returns; the caller inspects `result.attempts[-1].succeeded` to
    know if we gave up.
    """

    messages = initial_messages(question)
    attempts: list[Attempt] = []
    max_attempts = _max_attempts()
    verify = _verify_results_enabled()
    preview_rows = _preview_rows()

    # Track SQLs we've already executed successfully — if the model refines
    # to one of them we stop the review loop and keep the existing result.
    seen_sqls: set[str] = set()
    last_success: tuple[str, list[str], list[dict]] | None = None

    # First chat call produces the initial candidate. Subsequent iterations
    # either consume an error-retry response or a review-refinement directly,
    # without calling chat() at the top.
    last_raw = chat(messages)

    for _ in range(max_attempts):
        candidate = extract_sql(last_raw)

        try:
            safe_sql = ensure_select_only(candidate)
        except UnsafeSQLError as e:
            error = f"Refused unsafe SQL: {e}"
            attempts.append(Attempt(sql=candidate, error=error, kind="execution"))
            messages.append({"role": "assistant", "content": last_raw})
            messages.append({"role": "user", "content": _retry_user_message(error)})
            last_raw = chat(messages)
            continue

        try:
            cols, rows = _execute(safe_sql)
        except SQLAlchemyError as e:
            error = f"{e.__class__.__name__}: {e}"
            attempts.append(Attempt(sql=safe_sql, error=error, kind="execution"))
            messages.append({"role": "assistant", "content": last_raw})
            messages.append({"role": "user", "content": _retry_user_message(error)})
            last_raw = chat(messages)
            continue

        # Oscillation guard: if the model has refined to a SQL we've already
        # executed, stop and accept the previous result.
        if safe_sql in seen_sqls and last_success is not None:
            prev_sql, prev_cols, prev_rows = last_success
            attempts.append(Attempt(
                sql=safe_sql, succeeded=True, kind="review",
                judgment="(oscillation guard) model re-emitted a previous query; accepting prior result",
            ))
            return AskResult(
                question=question,
                sql=prev_sql, columns=prev_cols, rows=prev_rows,
                attempts=attempts, raw_llm_response=last_raw,
                explanation=_explain_result(question, prev_sql, prev_cols, prev_rows),
            )
        seen_sqls.add(safe_sql)
        last_success = (safe_sql, cols, rows)

        attempts.append(Attempt(sql=safe_sql, succeeded=True, kind="execution"))

        if not verify:
            return AskResult(
                question=question, sql=safe_sql, columns=cols, rows=rows,
                attempts=attempts, raw_llm_response=last_raw,
                explanation=_explain_result(question, safe_sql, cols, rows),
            )

        # Verification on: ask the model to judge the result.
        messages.append({"role": "assistant", "content": last_raw})
        preview = format_result_preview(cols, rows, max_rows=preview_rows)
        messages.append({"role": "user",
                         "content": review_user_message(question, safe_sql, preview)})

        review_raw = chat(messages)
        if not has_fenced_sql(review_raw):
            attempts.append(Attempt(
                sql=safe_sql, succeeded=True, kind="review",
                judgment=review_raw.strip()[:500],
            ))
            return AskResult(
                question=question, sql=safe_sql, columns=cols, rows=rows,
                attempts=attempts, raw_llm_response=review_raw,
                explanation=_explain_result(question, safe_sql, cols, rows),
            )

        # Refinement: log the judgment and feed the refined SQL into the next
        # loop iteration directly (no extra chat() call at the top).
        attempts.append(Attempt(
            sql=safe_sql, succeeded=False, kind="review",
            judgment=review_raw.strip()[:500],
        ))
        messages.append({"role": "assistant", "content": review_raw})
        last_raw = review_raw

    # Hit max_attempts. Return the last successful result if we have one.
    if last_success is not None:
        prev_sql, prev_cols, prev_rows = last_success
        return AskResult(
            question=question, sql=prev_sql, columns=prev_cols, rows=prev_rows,
            attempts=attempts, raw_llm_response=last_raw,
            explanation=_explain_result(question, prev_sql, prev_cols, prev_rows),
        )
    return AskResult(
        question=question,
        sql=attempts[-1].sql if attempts else "",
        columns=[],
        rows=[],
        attempts=attempts,
        raw_llm_response=last_raw,
    )
