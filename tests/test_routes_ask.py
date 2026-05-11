"""Integration tests for /api/ask.

Mocks app.llm.client.chat_stream (the token-streaming primitive the pipeline
now calls) per-test to drive the LLM through specific outcomes: success,
retry-then-success, and exhausted-attempts failure. Each canned response is
yielded as a single token chunk — token-level streaming is exercised in
test_llm_client.py.
"""

from __future__ import annotations

import json

import pytest


def _chat_stream_from_iter(responses):
    """Build a `chat_stream`-shaped generator function that yields each
    pre-canned response as a single token. Each call consumes one entry
    from `responses`, mirroring how the iterator-of-strings mocks used to
    drive the non-streaming `chat()` primitive.

    Accepts either a list or an already-instantiated iterator (existing
    tests build `responses = iter([...])` so we don't double-wrap).
    """
    it = responses if hasattr(responses, "__next__") else iter(responses)

    def _impl(messages):
        yield next(it)

    return _impl


@pytest.fixture(autouse=True)
def _disable_explanation(monkeypatch):
    """Default: turn off the explanation turn for these tests so they don't
    have to budget an extra chat() call. The explanation feature itself is
    covered in test_llm_client.py::TestPipelineExplanation."""
    monkeypatch.setenv("MLX_EXPLAIN_RESULTS", "false")


@pytest.fixture(autouse=True)
def _reset_sessions():
    """Wipe in-memory session state between tests so they can't leak history."""
    from app.routes import session_store
    session_store.reset_all()
    yield
    session_store.reset_all()


class TestAskSuccess:
    """Verification on (default): execute → review → approve = 2 chat calls,
    surfaced as 2 attempts ('execution' kind that succeeded, then 'review'
    kind that succeeded with judgment='OK')."""

    def test_first_try_success_with_review_approval(self, client, monkeypatch):
        from app.llm import pipeline as pl

        responses = iter([
            "```sql\nSELECT brand FROM Device_Name LIMIT 2\n```",
            "OK",  # review approves
        ])
        monkeypatch.setattr(pl, "chat_stream", _chat_stream_from_iter(responses))

        r = client.post("/api/ask", json={"question": "show me brands"})
        assert r.status_code == 200
        body = r.json()
        assert body["question"] == "show me brands"
        assert "Device_Name" in body["sql"]
        assert len(body["rows"]) == 2
        assert body["columns"] == ["brand"]
        # 2 attempts: execution + review-approval
        assert len(body["attempts"]) == 2
        assert body["attempts"][0]["kind"] == "execution"
        assert body["attempts"][0]["succeeded"] is True
        assert body["attempts"][1]["kind"] == "review"
        assert body["attempts"][1]["succeeded"] is True
        assert body["attempts"][1]["judgment"] == "OK"

    def test_first_try_success_verify_off(self, client, monkeypatch):
        """With MLX_VERIFY_RESULTS=false the pipeline returns after one execution."""
        from app.llm import pipeline as pl

        monkeypatch.setenv("MLX_VERIFY_RESULTS", "false")
        monkeypatch.setattr(
            pl, "chat_stream",
            lambda messages: iter(["```sql\nSELECT brand FROM Device_Name LIMIT 2\n```"]),
        )
        r = client.post("/api/ask", json={"question": "show me brands"})
        assert r.status_code == 200
        body = r.json()
        assert len(body["attempts"]) == 1
        assert body["attempts"][0]["succeeded"] is True


class TestAskRetry:
    def test_retry_after_unsafe_emission(self, client, monkeypatch):
        from app.llm import pipeline as pl

        monkeypatch.setenv("MLX_VERIFY_RESULTS", "false")  # focus on guard retry
        responses = iter([
            "```sql\nDROP TABLE Device\n```",  # rejected by guard
            "```sql\nSELECT model FROM Device_Name LIMIT 1\n```",  # ok
        ])
        monkeypatch.setattr(pl, "chat_stream", _chat_stream_from_iter(responses))

        r = client.post("/api/ask", json={"question": "any question"})
        assert r.status_code == 200
        body = r.json()
        assert len(body["attempts"]) == 2
        assert body["attempts"][0]["succeeded"] is False
        assert "Refused unsafe SQL" in body["attempts"][0]["error"]
        assert body["attempts"][1]["succeeded"] is True

    def test_retry_after_db_error(self, client, monkeypatch):
        from app.llm import pipeline as pl

        monkeypatch.setenv("MLX_VERIFY_RESULTS", "false")
        responses = iter([
            "```sql\nSELECT bogus_col FROM Device_Name\n```",  # SQL error
            "```sql\nSELECT brand FROM Device_Name LIMIT 1\n```",
        ])
        monkeypatch.setattr(pl, "chat_stream", _chat_stream_from_iter(responses))

        r = client.post("/api/ask", json={"question": "x"})
        assert r.status_code == 200
        body = r.json()
        assert len(body["attempts"]) == 2
        assert body["attempts"][1]["succeeded"] is True


class TestAskReviewLoop:
    """Verification on, review may refine multiple times before approving."""

    def test_review_refines_then_approves(self, client, monkeypatch):
        from app.llm import pipeline as pl

        responses = iter([
            "```sql\nSELECT model FROM Device_Name LIMIT 1\n```",   # initial SQL
            "```sql\nSELECT brand FROM Device_Name LIMIT 2\n```",   # review refines
            "OK",                                                    # second review approves
        ])
        monkeypatch.setattr(pl, "chat_stream", _chat_stream_from_iter(responses))

        r = client.post("/api/ask", json={"question": "show brands"})
        assert r.status_code == 200
        body = r.json()
        # 4 attempts: exec1, review-refine, exec2, review-approve
        assert len(body["attempts"]) == 4
        kinds = [a["kind"] for a in body["attempts"]]
        # First execution succeeds, then review refines, then second exec, then approval
        assert kinds[0] == "execution"
        assert kinds[1] == "review"  # the refinement
        assert "brand" in body["sql"]  # final accepted SQL is the refined one

    def test_oscillation_guard_breaks_loop(self, client, monkeypatch):
        """If the LLM refines back to a SQL we already executed, accept the
        FIRST successful result (the one previously stored in last_success).
        """
        from app.llm import pipeline as pl

        responses = iter([
            "```sql\nSELECT brand FROM Device_Name LIMIT 1\n```",  # initial — first success
            "```sql\nSELECT model FROM Device_Name LIMIT 1\n```",  # review refines (also runs)
            "```sql\nSELECT brand FROM Device_Name LIMIT 1\n```",  # refines back to first → oscillation
        ])
        monkeypatch.setattr(pl, "chat_stream", _chat_stream_from_iter(responses))

        r = client.post("/api/ask", json={"question": "anything"})
        assert r.status_code == 200
        body = r.json()
        # Contract: the oscillation guard accepts the *previously stored*
        # last_success at the moment the duplicate fires. After exec1 then
        # exec2, last_success == exec2's SQL (`model`), and the duplicate
        # third candidate matches exec1 (`brand`). The guard returns the
        # second (most-recently-stored) successful SQL.
        assert body["sql"] == "SELECT model FROM Device_Name LIMIT 1"
        # The oscillation-guard attempt is the LAST one logged.
        last = body["attempts"][-1]
        assert last["judgment"] is not None
        assert "oscillation" in last["judgment"]
        assert last["kind"] == "review"
        assert last["succeeded"] is True


class TestAskFailure:
    def test_exhausts_attempts_returns_400(self, client, monkeypatch):
        from app.llm import pipeline as pl

        monkeypatch.setenv("MLX_VERIFY_RESULTS", "false")
        monkeypatch.setenv("MLX_MAX_RETRIES", "2")
        # Always emits something the guard rejects
        monkeypatch.setattr(
            pl, "chat_stream",
            lambda messages: iter(["```sql\nDROP TABLE Device\n```"]),
        )

        r = client.post("/api/ask", json={"question": "anything"})
        assert r.status_code == 400
        body = r.json()
        assert "attempts" in body["detail"]
        assert len(body["detail"]["attempts"]) == 2
        assert all(not a["succeeded"] for a in body["detail"]["attempts"])


class TestAskHealth:
    def test_health_endpoint(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json() == {"ok": True}


class TestAskSessionMemory:
    """Conversation memory: history is recorded after a successful ask and
    surfaced on the next call within the same session."""

    def test_first_call_mints_session_id(self, client, monkeypatch):
        from app.llm import pipeline as pl
        monkeypatch.setenv("MLX_VERIFY_RESULTS", "false")
        monkeypatch.setattr(
            pl, "chat_stream",
            lambda messages: iter(["```sql\nSELECT brand FROM Device_Name LIMIT 1\n```"]),
        )
        r = client.post("/api/ask", json={"question": "show one brand"})
        assert r.status_code == 200
        body = r.json()
        assert "session_id" in body and body["session_id"]

    def test_history_prepended_on_second_call(self, client, monkeypatch):
        """Capture every chat() call's messages list; on the second call the
        prepended history must include a turn referencing the first question."""
        from app.llm import pipeline as pl
        monkeypatch.setenv("MLX_VERIFY_RESULTS", "false")

        captured = []

        def capturing_chat_stream(messages):
            captured.append(list(messages))
            yield "```sql\nSELECT brand FROM Device_Name LIMIT 1\n```"

        monkeypatch.setattr(pl, "chat_stream", capturing_chat_stream)

        r1 = client.post("/api/ask", json={"question": "show brands"})
        sid = r1.json()["session_id"]

        r2 = client.post("/api/ask", json={"question": "now show models", "session_id": sid})
        assert r2.status_code == 200

        # First call: no prior turns. Second call: prior turn injected.
        first_call_msgs = captured[0]
        second_call_msgs = captured[1]
        assert len(second_call_msgs) > len(first_call_msgs)
        # The injected user turn must reference the earlier question.
        injected = "\n".join(m["content"] for m in second_call_msgs if m["role"] == "user")
        assert "show brands" in injected

    def test_explicit_session_id_used_as_provided(self, client, monkeypatch):
        from app.llm import pipeline as pl
        monkeypatch.setenv("MLX_VERIFY_RESULTS", "false")
        monkeypatch.setattr(
            pl, "chat_stream",
            lambda messages: iter(["```sql\nSELECT brand FROM Device_Name LIMIT 1\n```"]),
        )
        r = client.post("/api/ask", json={"question": "x", "session_id": "my-fixed-id"})
        assert r.json()["session_id"] == "my-fixed-id"

    def test_failed_call_still_returns_session_id_in_detail(self, client, monkeypatch):
        from app.llm import pipeline as pl
        monkeypatch.setenv("MLX_VERIFY_RESULTS", "false")
        monkeypatch.setenv("MLX_MAX_RETRIES", "1")
        monkeypatch.setattr(
            pl, "chat_stream",
            lambda messages: iter(["```sql\nDROP TABLE Device\n```"]),
        )
        r = client.post("/api/ask", json={"question": "x", "session_id": "abc123"})
        assert r.status_code == 400
        assert r.json()["detail"]["session_id"] == "abc123"

    def test_reset_session_endpoint(self, client, monkeypatch):
        from app.llm import pipeline as pl
        monkeypatch.setenv("MLX_VERIFY_RESULTS", "false")
        monkeypatch.setattr(
            pl, "chat_stream",
            lambda messages: iter(["```sql\nSELECT brand FROM Device_Name LIMIT 1\n```"]),
        )
        sid = "to-reset"
        client.post("/api/ask", json={"question": "x", "session_id": sid})
        # Reset and verify history is empty by capturing the next call's messages.
        r = client.delete(f"/api/ask/session/{sid}")
        assert r.status_code == 200

        captured = []

        def capturing_chat_stream(messages):
            captured.append(list(messages))
            yield "```sql\nSELECT brand FROM Device_Name LIMIT 1\n```"

        monkeypatch.setattr(pl, "chat_stream", capturing_chat_stream)
        client.post("/api/ask", json={"question": "y", "session_id": sid})
        # No injected "earlier question" content — only the new "y" question.
        injected = "\n".join(m["content"] for m in captured[0] if m["role"] == "user")
        assert "earlier question" not in injected


class TestAskStream:
    """Streaming endpoint: NDJSON events flow in order."""

    def _events(self, response_text: str) -> list[dict]:
        return [json.loads(line) for line in response_text.splitlines() if line]

    def test_stream_emits_attempt_executed_result_session(self, client, monkeypatch):
        from app.llm import pipeline as pl
        monkeypatch.setenv("MLX_VERIFY_RESULTS", "false")
        monkeypatch.setattr(
            pl, "chat_stream",
            lambda messages: iter(["```sql\nSELECT brand FROM Device_Name LIMIT 1\n```"]),
        )

        r = client.post("/api/ask/stream", json={"question": "show brands"})
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/x-ndjson")

        events = self._events(r.text)
        kinds = [e["type"] for e in events]
        # attempt → executed → result → session, in that order
        assert "attempt" in kinds
        assert "executed" in kinds
        assert "result" in kinds
        assert kinds[-1] == "session"
        # The executed event carries rows before the final result.
        executed = next(e for e in events if e["type"] == "executed")
        assert executed["columns"] == ["brand"]
        assert len(executed["rows"]) == 1

    def test_stream_records_history_for_session(self, client, monkeypatch):
        from app.llm import pipeline as pl
        monkeypatch.setenv("MLX_VERIFY_RESULTS", "false")

        captured = []

        def capturing_chat_stream(messages):
            captured.append(list(messages))
            yield "```sql\nSELECT brand FROM Device_Name LIMIT 1\n```"

        monkeypatch.setattr(pl, "chat_stream", capturing_chat_stream)

        # First streaming call mints a session
        r1 = client.post("/api/ask/stream", json={"question": "first q"})
        sess_event = next(json.loads(line) for line in r1.text.splitlines()[::-1] if line)
        assert sess_event["type"] == "session"
        sid = sess_event["session_id"]

        # Second call (non-streaming) sees the history from the streamed turn
        client.post("/api/ask", json={"question": "second q", "session_id": sid})
        injected = "\n".join(m["content"] for m in captured[1] if m["role"] == "user")
        assert "first q" in injected

    def test_stream_breaks_after_closing_fence(self, client, monkeypatch):
        """Repro for the year-over-year RAM hang: the model emits a complete
        fenced SQL block then keeps generating commentary. The pipeline must
        break out of chat_stream as soon as the closing fence lands —
        otherwise the user waits for ~max_tokens of dead output before the
        pipeline ever runs the SQL.
        """
        from app.llm import pipeline as pl
        monkeypatch.setenv("MLX_VERIFY_RESULTS", "false")
        monkeypatch.setenv("MLX_EXPLAIN_RESULTS", "false")

        tokens_consumed = []

        def trailing_commentary_chat_stream(messages):
            # A realistic 8-token SQL block followed by 100 garbage tokens
            # the early-break should NEVER consume.
            sql_chunks = [
                "```sql\n", "SELECT ", "year ", "FROM Device ", "LIMIT 1", "\n", "```",
            ]
            for t in sql_chunks:
                tokens_consumed.append(t)
                yield t
            for i in range(100):
                tokens_consumed.append(f"garbage_{i}")
                yield f"garbage_{i}"

        monkeypatch.setattr(pl, "chat_stream", trailing_commentary_chat_stream)

        r = client.post("/api/ask/stream", json={"question": "anything"})
        assert r.status_code == 200

        # Only the 7 SQL chunks should have been pulled — no garbage.
        assert tokens_consumed == [
            "```sql\n", "SELECT ", "year ", "FROM Device ", "LIMIT 1", "\n", "```",
        ]
        # And the pipeline successfully reached the result event.
        events = self._events(r.text)
        types = [e["type"] for e in events]
        assert "executed" in types
        assert "result" in types

    def test_stream_emits_phase_and_sql_token_events(self, client, monkeypatch):
        """Token-level streaming: each chat_stream() call yields multiple
        tokens; the streaming route surfaces each as a sql_token event,
        bracketed by a phase event."""
        from app.llm import pipeline as pl
        monkeypatch.setenv("MLX_VERIFY_RESULTS", "false")
        monkeypatch.setenv("MLX_EXPLAIN_RESULTS", "false")

        # Five tokens that, joined, form a valid SQL block.
        sql_tokens = ["```sql\n", "SELECT brand ", "FROM Device_Name ", "LIMIT 1", "\n```"]

        def chat_stream_mock(messages):
            for tok in sql_tokens:
                yield tok

        monkeypatch.setattr(pl, "chat_stream", chat_stream_mock)

        r = client.post("/api/ask/stream", json={"question": "stream me"})
        assert r.status_code == 200
        events = self._events(r.text)
        types = [e["type"] for e in events]

        # Order: phase → 5× sql_token → attempt → executed → result → session
        assert types[0] == "phase"
        assert events[0]["phase"] == "generating_sql"
        token_events = [e for e in events if e["type"] == "sql_token"]
        assert len(token_events) == len(sql_tokens)
        assert "".join(e["content"] for e in token_events) == "".join(sql_tokens)
        # Every sql_token carries its phase so the UI can route it.
        for e in token_events:
            assert e["phase"] == "generating_sql"
        # The result still carries the canonicalised SQL.
        result = next(e for e in events if e["type"] == "result")
        assert "Device_Name" in result["sql"]

    def test_stream_emits_error_on_exhaustion(self, client, monkeypatch):
        from app.llm import pipeline as pl
        monkeypatch.setenv("MLX_VERIFY_RESULTS", "false")
        monkeypatch.setenv("MLX_MAX_RETRIES", "2")
        monkeypatch.setattr(
            pl, "chat_stream",
            lambda messages: iter(["```sql\nDROP TABLE Device\n```"]),
        )

        r = client.post("/api/ask/stream", json={"question": "no good"})
        assert r.status_code == 200
        events = self._events(r.text)
        # Two attempts (both rejected) + one error + session sentinel
        assert sum(1 for e in events if e["type"] == "attempt") == 2
        err = next(e for e in events if e["type"] == "error")
        assert "after 2 attempts" in err["message"]
        assert err["last_error"] is not None
