"""Integration tests for /api/ask.

Mocks app.llm.client.chat (and thus app.llm.pipeline.chat) per-test to drive
the LLM through specific outcomes: success, retry-then-success, and
exhausted-attempts failure.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _disable_explanation(monkeypatch):
    """Default: turn off the explanation turn for these tests so they don't
    have to budget an extra chat() call. The explanation feature itself is
    covered in test_llm_client.py::TestPipelineExplanation."""
    monkeypatch.setenv("MLX_EXPLAIN_RESULTS", "false")


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
        monkeypatch.setattr(pl, "chat", lambda messages: next(responses))

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
            pl, "chat", lambda messages: "```sql\nSELECT brand FROM Device_Name LIMIT 2\n```"
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

        monkeypatch.setenv("MLX_VERIFY_RESULTS", "false")
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


class TestAskReviewLoop:
    """Verification on, review may refine multiple times before approving."""

    def test_review_refines_then_approves(self, client, monkeypatch):
        from app.llm import pipeline as pl

        responses = iter([
            "```sql\nSELECT model FROM Device_Name LIMIT 1\n```",   # initial SQL
            "```sql\nSELECT brand FROM Device_Name LIMIT 2\n```",   # review refines
            "OK",                                                    # second review approves
        ])
        monkeypatch.setattr(pl, "chat", lambda messages: next(responses))

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
        """If the LLM refines back to a SQL we already executed, accept the prior result."""
        from app.llm import pipeline as pl

        responses = iter([
            "```sql\nSELECT brand FROM Device_Name LIMIT 1\n```",  # initial
            "```sql\nSELECT model FROM Device_Name LIMIT 1\n```",  # review refines
            "```sql\nSELECT brand FROM Device_Name LIMIT 1\n```",  # refines back to first
        ])
        monkeypatch.setattr(pl, "chat", lambda messages: next(responses))

        r = client.post("/api/ask", json={"question": "anything"})
        assert r.status_code == 200
        body = r.json()
        # The pipeline should detect the loop and stop with the last succeeded SQL.
        assert body["sql"] in ("SELECT brand FROM Device_Name LIMIT 1",
                               "SELECT model FROM Device_Name LIMIT 1")
        # An oscillation-guard attempt was added.
        guards = [a for a in body["attempts"] if a.get("judgment") and "oscillation" in a["judgment"]]
        assert len(guards) >= 1


class TestAskFailure:
    def test_exhausts_attempts_returns_400(self, client, monkeypatch):
        from app.llm import pipeline as pl

        monkeypatch.setenv("MLX_VERIFY_RESULTS", "false")
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
