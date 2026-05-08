"""Integration tests for /api/ask.

Mocks app.llm.client.chat (and thus app.llm.pipeline.chat) per-test to drive
the LLM through specific outcomes: success, retry-then-success, and
exhausted-attempts failure.
"""

from __future__ import annotations

import pytest


class TestAskSuccess:
    def test_first_try_success(self, client, monkeypatch):
        # Monkeypatch the pipeline's chat (which is imported from client)
        from app.llm import pipeline as pl

        monkeypatch.setattr(
            pl, "chat", lambda messages: "```sql\nSELECT brand FROM Device_Name LIMIT 2\n```"
        )
        r = client.post("/api/ask", json={"question": "show me brands"})
        assert r.status_code == 200
        body = r.json()
        assert body["question"] == "show me brands"
        assert "Device_Name" in body["sql"]
        assert len(body["rows"]) == 2
        assert body["columns"] == ["brand"]
        assert len(body["attempts"]) == 1
        assert body["attempts"][0]["succeeded"] is True


class TestAskRetry:
    def test_retry_after_unsafe_emission(self, client, monkeypatch):
        from app.llm import pipeline as pl

        responses = iter([
            "```sql\nDROP TABLE Device\n```",  # rejected by guard
            "```sql\nSELECT model FROM Device_Name LIMIT 1\n```",  # ok
        ])
        monkeypatch.setattr(pl, "chat", lambda messages: next(responses))

        r = client.post("/api/ask", json={"question": "any question"})
        assert r.status_code == 200
        body = r.json()
        assert len(body["attempts"]) == 2
        assert body["attempts"][0]["succeeded"] is False
        assert "Refused unsafe SQL" in body["attempts"][0]["error"]
        assert body["attempts"][1]["succeeded"] is True

    def test_retry_after_db_error(self, client, monkeypatch):
        from app.llm import pipeline as pl

        responses = iter([
            "```sql\nSELECT bogus_col FROM Device_Name\n```",  # SQL error
            "```sql\nSELECT brand FROM Device_Name LIMIT 1\n```",
        ])
        monkeypatch.setattr(pl, "chat", lambda messages: next(responses))

        r = client.post("/api/ask", json={"question": "x"})
        assert r.status_code == 200
        body = r.json()
        assert len(body["attempts"]) == 2
        assert body["attempts"][1]["succeeded"] is True


class TestAskFailure:
    def test_exhausts_attempts_returns_400(self, client, monkeypatch):
        from app.llm import pipeline as pl

        monkeypatch.setenv("MLX_MAX_RETRIES", "2")
        # Always emits something the guard rejects
        monkeypatch.setattr(
            pl, "chat", lambda messages: "```sql\nDROP TABLE Device\n```"
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
