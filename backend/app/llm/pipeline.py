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
    truncated: bool = False


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


def _row_cap() -> int:
    try:
        return max(1, int(os.getenv("ASK_MAX_ROWS", "500")))
    except ValueError:
        return 500


def _statement_timeout_seconds() -> int:
    """Statement timeout for Ask-path queries. 0 disables enforcement."""
    try:
        return max(0, int(os.getenv("ASK_STATEMENT_TIMEOUT_SECONDS", "30")))
    except ValueError:
        return 30


def _execute(sql: str) -> tuple[list[str], list[dict], bool]:
    """Execute `sql` and return (columns, rows, truncated).

    Caps the result at `ASK_MAX_ROWS` rows (default 500) so a malformed query
    that returns the entire fact table cannot OOM the JSON serializer. When
    the cap is hit, `truncated=True` and only the first N rows are returned.

    Applies a per-statement timeout via MariaDB's `MAX_STATEMENT_TIME` (in
    seconds). SQLite (used in tests) doesn't support the SET, so we skip the
    statement when the dialect isn't mysql/mariadb.
    """
    cap = _row_cap()
    timeout = _statement_timeout_seconds()
    eng = ro_engine()
    with eng.connect() as conn:
        if timeout > 0 and eng.dialect.name in {"mysql", "mariadb"}:
            try:
                conn.execute(text(f"SET SESSION MAX_STATEMENT_TIME = {timeout}"))
            except SQLAlchemyError:
                # Older MariaDB / non-MariaDB MySQL may reject; not fatal.
                pass
        result = conn.execute(text(sql))
        cols = list(result.keys())
        # Read up to cap+1 rows so we can detect truncation without
        # materialising the entire result set.
        mapping_iter = result.mappings()
        rows: list[dict] = []
        truncated = False
        for i, r in enumerate(mapping_iter):
            if i >= cap:
                truncated = True
                break
            rows.append(dict(r))
    return cols, rows, truncated


def _attempt_event(att: Attempt, idx: int) -> dict:
    return {
        "type": "attempt",
        "index": idx,
        "attempt": {
            "sql": att.sql,
            "error": att.error,
            "succeeded": att.succeeded,
            "kind": att.kind,
            "judgment": att.judgment,
        },
    }


def _result_event(result: AskResult, kind: str = "result") -> dict:
    return {
        "type": kind,
        "question": result.question,
        "sql": result.sql,
        "columns": result.columns,
        "rows": result.rows,
        "attempts": [
            {
                "sql": a.sql, "error": a.error, "succeeded": a.succeeded,
                "kind": a.kind, "judgment": a.judgment,
            }
            for a in result.attempts
        ],
        "raw_llm_response": result.raw_llm_response,
        "explanation": result.explanation,
        "truncated": result.truncated,
    }


def answer_question_events(question: str, *, history: list[dict] | None = None):
    """Generator-form pipeline: yields event dicts as work progresses.

    Event shapes:
      {"type": "attempt", "index": int, "attempt": {...}}
        — emitted as soon as an Attempt is appended to `attempts`.
      {"type": "executed", "sql": str, "columns": [...], "rows": [...],
       "truncated": bool}
        — emitted on every successful execution, before the review/explanation
        turns. UI can render the SQL and rows incrementally.
      {"type": "result", ...AskResult fields...}
        — final accepted answer.
      {"type": "error", "message": str, "last_error": str|None,
       "attempts": [...]}
        — pipeline gave up with no successful execution.

    The non-streaming `answer_question` consumes this generator and returns
    either the AskResult from the terminal `result` event, or raises
    `PipelineFailure` with the `error` event payload.

    `history` (optional) is a list of prior chat messages to prepend to the
    LLM context — used by the conversation-memory feature so the model can
    reference earlier turns. Each entry is a {"role", "content"} dict.
    """
    messages = initial_messages(question)
    if history:
        # Insert history *between* the few-shot examples and the final user
        # turn so the model sees: system, few-shot pairs, history, question.
        # initial_messages puts the user question at messages[-1]; insert
        # before that.
        for h in history:
            messages.insert(-1, h)

    attempts: list[Attempt] = []
    max_attempts = _max_attempts()
    verify = _verify_results_enabled()
    preview_rows = _preview_rows()

    seen_sqls: set[str] = set()
    last_success: tuple[str, list[str], list[dict], bool] | None = None

    last_raw = chat(messages)

    def _push(att: Attempt):
        attempts.append(att)
        return _attempt_event(att, len(attempts) - 1)

    for _ in range(max_attempts):
        candidate = extract_sql(last_raw)

        try:
            safe_sql = ensure_select_only(candidate)
        except UnsafeSQLError as e:
            error = f"Refused unsafe SQL: {e}"
            yield _push(Attempt(sql=candidate, error=error, kind="execution"))
            messages.append({"role": "assistant", "content": last_raw})
            messages.append({"role": "user", "content": _retry_user_message(error)})
            last_raw = chat(messages)
            continue

        try:
            cols, rows, truncated = _execute(safe_sql)
        except SQLAlchemyError as e:
            error = f"{e.__class__.__name__}: {e}"
            yield _push(Attempt(sql=safe_sql, error=error, kind="execution"))
            messages.append({"role": "assistant", "content": last_raw})
            messages.append({"role": "user", "content": _retry_user_message(error)})
            last_raw = chat(messages)
            continue

        if safe_sql in seen_sqls and last_success is not None:
            prev_sql, prev_cols, prev_rows, prev_truncated = last_success
            yield _push(Attempt(
                sql=safe_sql, succeeded=True, kind="review",
                judgment="(oscillation guard) model re-emitted a previous query; accepting prior result",
            ))
            res = AskResult(
                question=question,
                sql=prev_sql, columns=prev_cols, rows=prev_rows,
                attempts=attempts, raw_llm_response=last_raw,
                explanation=_explain_result(question, prev_sql, prev_cols, prev_rows),
                truncated=prev_truncated,
            )
            yield _result_event(res)
            return

        seen_sqls.add(safe_sql)
        last_success = (safe_sql, cols, rows, truncated)

        yield _push(Attempt(sql=safe_sql, succeeded=True, kind="execution"))
        # Emit the executed result eagerly so the UI can render rows before
        # the review and explanation turns finish.
        yield {
            "type": "executed",
            "sql": safe_sql, "columns": cols, "rows": rows, "truncated": truncated,
        }

        if not verify:
            res = AskResult(
                question=question, sql=safe_sql, columns=cols, rows=rows,
                attempts=attempts, raw_llm_response=last_raw,
                explanation=_explain_result(question, safe_sql, cols, rows),
                truncated=truncated,
            )
            yield _result_event(res)
            return

        messages.append({"role": "assistant", "content": last_raw})
        preview = format_result_preview(cols, rows, max_rows=preview_rows)
        messages.append({"role": "user",
                         "content": review_user_message(question, safe_sql, preview)})

        review_raw = chat(messages)
        if not has_fenced_sql(review_raw):
            yield _push(Attempt(
                sql=safe_sql, succeeded=True, kind="review",
                judgment=review_raw.strip()[:500],
            ))
            res = AskResult(
                question=question, sql=safe_sql, columns=cols, rows=rows,
                attempts=attempts, raw_llm_response=review_raw,
                explanation=_explain_result(question, safe_sql, cols, rows),
                truncated=truncated,
            )
            yield _result_event(res)
            return

        yield _push(Attempt(
            sql=safe_sql, succeeded=False, kind="review",
            judgment=review_raw.strip()[:500],
        ))
        messages.append({"role": "assistant", "content": review_raw})
        last_raw = review_raw

    # Exhausted attempts. Return last successful result if any.
    if last_success is not None:
        prev_sql, prev_cols, prev_rows, prev_truncated = last_success
        res = AskResult(
            question=question, sql=prev_sql, columns=prev_cols, rows=prev_rows,
            attempts=attempts, raw_llm_response=last_raw,
            explanation=_explain_result(question, prev_sql, prev_cols, prev_rows),
            truncated=prev_truncated,
        )
        yield _result_event(res)
        return

    # No successful execution ever — error event.
    yield {
        "type": "error",
        "message": f"LLM failed to produce a runnable query after {len(attempts)} attempts.",
        "last_error": attempts[-1].error if attempts else None,
        "attempts": [
            {"sql": a.sql, "error": a.error, "succeeded": a.succeeded,
             "kind": a.kind, "judgment": a.judgment}
            for a in attempts
        ],
    }


class PipelineFailure(Exception):
    """Raised by `answer_question` when no successful execution occurred."""

    def __init__(self, payload: dict):
        super().__init__(payload.get("message", "pipeline failed"))
        self.payload = payload


def answer_question(question: str, *, history: list[dict] | None = None) -> AskResult:
    """Non-streaming wrapper. Always returns an AskResult.

    For backwards compatibility with existing tests / the non-streaming route,
    this consumes `answer_question_events`. When the pipeline gives up
    (terminal `error` event), we still return an AskResult so the existing
    route's "inspect attempts[-1].succeeded" idiom keeps working — but the
    streaming route raises `PipelineFailure` for richer error data.
    """
    final_result: AskResult | None = None
    error_payload: dict | None = None
    attempts_collected: list[Attempt] = []
    last_raw_seen = ""

    for ev in answer_question_events(question, history=history):
        t = ev.get("type")
        if t == "attempt":
            a = ev["attempt"]
            attempts_collected.append(Attempt(
                sql=a["sql"], error=a["error"], succeeded=a["succeeded"],
                kind=a["kind"], judgment=a["judgment"],
            ))
        elif t == "result":
            # Reconstruct AskResult from the event payload.
            final_result = AskResult(
                question=ev["question"], sql=ev["sql"],
                columns=ev["columns"], rows=ev["rows"],
                attempts=attempts_collected,
                raw_llm_response=ev["raw_llm_response"],
                explanation=ev["explanation"],
                truncated=ev["truncated"],
            )
            last_raw_seen = ev["raw_llm_response"]
        elif t == "error":
            error_payload = ev

    if final_result is not None:
        return final_result

    return AskResult(
        question=question,
        sql=attempts_collected[-1].sql if attempts_collected else "",
        columns=[],
        rows=[],
        attempts=attempts_collected,
        raw_llm_response=last_raw_seen,
    )
