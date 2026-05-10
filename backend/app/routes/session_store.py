"""In-memory session store for Ask-path conversation memory.

Each session keeps a small ring of recent (question, accepted SQL, short
result preview) tuples. Subsequent calls in the same session prepend those
turns to the LLM context as a faux assistant/user history so the model can
reference earlier work ("now show that for Samsung").

In-memory means: lost on server restart, not shared across workers. That is
acceptable for the local web platform; a hosted deployment would swap this
out for Redis or similar. Bounded by `SESSION_MAX_TURNS` (default 5) so
the prompt size stays predictable.
"""

from __future__ import annotations

import os
import threading
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Deque


def _max_turns() -> int:
    try:
        return max(1, int(os.getenv("SESSION_MAX_TURNS", "5")))
    except ValueError:
        return 5


@dataclass
class Turn:
    question: str
    sql: str
    result_preview: str


# session_id → ring of recent turns
_SESSIONS: dict[str, Deque[Turn]] = {}
_LOCK = threading.Lock()


def resolve_session_id(provided: str | None) -> str:
    """Return `provided` if non-empty, else mint a new uuid4 hex string."""
    if provided:
        return provided
    return uuid.uuid4().hex


def append_turn(session_id: str, *, question: str, sql: str, result_preview: str) -> None:
    """Record a successful turn into the session ring."""
    with _LOCK:
        ring = _SESSIONS.setdefault(session_id, deque(maxlen=_max_turns()))
        ring.append(Turn(question=question, sql=sql, result_preview=result_preview))


def history_messages(session_id: str) -> list[dict]:
    """Render the session into chat messages to insert into the LLM context.

    Each prior turn becomes a user→assistant pair: the user message restates
    the question, the assistant message restates the SQL it ran with a one-
    line "(this returned X rows; preview: …)" tail. Returns [] when the
    session is empty or unknown.
    """
    with _LOCK:
        ring = _SESSIONS.get(session_id)
        if not ring:
            return []
        turns = list(ring)

    msgs: list[dict] = []
    for t in turns:
        msgs.append({"role": "user", "content": f"(earlier question) {t.question}"})
        msgs.append({
            "role": "assistant",
            "content": (
                f"(my earlier answer)\n```sql\n{t.sql}\n```\n"
                f"That query produced this preview:\n{t.result_preview}"
            ),
        })
    return msgs


def clear_session(session_id: str) -> None:
    with _LOCK:
        _SESSIONS.pop(session_id, None)


def reset_all() -> None:
    """Test helper — wipe every session."""
    with _LOCK:
        _SESSIONS.clear()
