"""NL → SQL endpoint with self-correction.

Two routes share the same pipeline:
  - POST /api/ask         — non-streaming, returns the final AskResponse.
  - POST /api/ask/stream  — newline-delimited JSON event stream so the UI
                            can render attempts and the executed result
                            before the review/explanation turns finish.

Both accept an optional `session_id` to opt into conversation memory.
Sessions store prior (question, accepted SQL, result preview) tuples in
memory, prepended to the LLM context on subsequent calls in the same
session. Memory is process-local — a server restart resets it.
"""

from __future__ import annotations

import datetime
import decimal
import json
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.llm.client import format_result_preview
from app.llm.pipeline import answer_question, answer_question_events
from app.routes import session_store


def _json_default(obj):
    """Fallback for json.dumps on values that the streaming route emits but
    aren't natively serialisable. pipeline._execute already coerces these on
    row construction; this is defence-in-depth for anything that slips
    through (or future schema changes that introduce new column types).
    A silent TypeError here closes the stream and the UI hangs — see the
    Decimal-from-ROUND(AVG(...)) regression that prompted this guard.
    """
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    if isinstance(obj, (datetime.datetime, datetime.date, datetime.time)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

router = APIRouter()


class AskRequest(BaseModel):
    question: str
    session_id: str | None = None


class AttemptOut(BaseModel):
    sql: str
    error: str | None = None
    succeeded: bool = False
    kind: str = "execution"          # 'execution' | 'review'
    judgment: str | None = None      # LLM's review-turn text


class AskResponse(BaseModel):
    question: str
    sql: str
    columns: list[str]
    rows: list[dict]
    attempts: list[AttemptOut]
    raw_llm_response: str
    explanation: str | None = None
    truncated: bool = False
    session_id: str


def _to_out(a) -> AttemptOut:
    return AttemptOut(
        sql=a.sql, error=a.error, succeeded=a.succeeded,
        kind=getattr(a, "kind", "execution"),
        judgment=getattr(a, "judgment", None),
    )


def _record_turn(sid: str, question: str, sql: str,
                 cols: list[str], rows: list[dict]) -> None:
    """Write a successful (question, sql, preview) tuple into the session log."""
    session_store.append_turn(
        sid,
        question=question,
        sql=sql,
        result_preview=format_result_preview(cols, rows, max_rows=5),
    )


@router.post("", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    sid = session_store.resolve_session_id(req.session_id)
    history = session_store.history_messages(sid)
    result = answer_question(req.question, history=history)

    if not result.attempts or not result.attempts[-1].succeeded:
        last_err = result.attempts[-1].error if result.attempts else "no attempts"
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"LLM failed to produce a runnable query after {len(result.attempts)} attempts.",
                "last_error": last_err,
                "attempts": [_to_out(a).model_dump() for a in result.attempts],
                "session_id": sid,
            },
        )

    _record_turn(sid, req.question, result.sql, result.columns, result.rows)

    return AskResponse(
        question=result.question,
        sql=result.sql,
        columns=result.columns,
        rows=result.rows,
        attempts=[_to_out(a) for a in result.attempts],
        raw_llm_response=result.raw_llm_response,
        explanation=result.explanation,
        truncated=result.truncated,
        session_id=sid,
    )


def _stream_events(question: str, sid: str):
    """Iterate the pipeline generator, emit one JSON object per line.

    Records the successful turn into the session store on the terminal
    `result` event. Always emits a final `session_id` event so the client
    knows which id to pass on the next call.
    """
    history = session_store.history_messages(sid)
    last_result: dict[str, Any] | None = None
    for ev in answer_question_events(question, history=history):
        if ev.get("type") == "result":
            last_result = ev
            _record_turn(
                sid, question,
                ev.get("sql", ""), ev.get("columns", []), ev.get("rows", []),
            )
        yield json.dumps(ev, default=_json_default) + "\n"
    yield json.dumps({"type": "session", "session_id": sid}, default=_json_default) + "\n"


@router.post("/stream")
def ask_stream(req: AskRequest):
    sid = session_store.resolve_session_id(req.session_id)
    return StreamingResponse(
        _stream_events(req.question, sid),
        media_type="application/x-ndjson",
    )


@router.delete("/session/{session_id}")
def reset_session(session_id: str) -> dict:
    """Clear a session's conversation memory."""
    session_store.clear_session(session_id)
    return {"ok": True, "session_id": session_id}
