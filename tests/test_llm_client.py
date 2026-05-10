"""Tests for the LLM client wrapper and pipeline retry logic.

The actual LLM call (`chat`) is monkeypatched in every test — we never
hit a real model. These tests assert message structure and the pipeline's
retry/recovery behavior.
"""

from __future__ import annotations

import pytest

from app.llm import client as llm_client
from app.llm import pipeline as llm_pipeline
from app.llm.client import extract_sql, initial_messages
from app.llm.few_shot import EXAMPLES


# ---------------------------------------------------------------------------
# extract_sql
# ---------------------------------------------------------------------------


class TestExtractSQL:
    def test_fenced_with_sql_tag(self):
        text = "Here you go:\n```sql\nSELECT 1\n```\nLet me know!"
        assert extract_sql(text) == "SELECT 1"

    def test_fenced_without_lang_tag(self):
        text = "```\nSELECT * FROM Device LIMIT 5\n```"
        assert extract_sql(text) == "SELECT * FROM Device LIMIT 5"

    def test_unfenced_returns_full_text(self):
        text = "SELECT 1"
        assert extract_sql(text) == "SELECT 1"

    def test_strips_trailing_semicolon(self):
        text = "```sql\nSELECT 1;\n```"
        assert extract_sql(text) == "SELECT 1"

    def test_picks_first_fenced_block(self):
        text = "```sql\nSELECT 1\n```\nand\n```sql\nSELECT 2\n```"
        # Regex is non-greedy → first block wins
        assert extract_sql(text) == "SELECT 1"

    def test_case_insensitive_sql_tag(self):
        text = "```SQL\nSELECT 1\n```"
        assert extract_sql(text) == "SELECT 1"


# ---------------------------------------------------------------------------
# initial_messages
# ---------------------------------------------------------------------------


class TestInitialMessages:
    def test_contains_system_prompt_first(self):
        msgs = initial_messages("test question")
        assert msgs[0]["role"] == "system"
        assert "MariaDB" in msgs[0]["content"]

    def test_few_shot_examples_alternate(self):
        msgs = initial_messages("test")
        # System + (user/assistant pairs from EXAMPLES) + final user
        expected_count = 1 + 2 * len(EXAMPLES) + 1
        assert len(msgs) == expected_count
        # The middle pairs should alternate user / assistant
        for i, (q, a) in enumerate(EXAMPLES):
            user_msg = msgs[1 + i * 2]
            asst_msg = msgs[1 + i * 2 + 1]
            assert user_msg == {"role": "user", "content": q}
            assert asst_msg == {"role": "assistant", "content": a}

    def test_user_question_is_last_message(self):
        msgs = initial_messages("how many phones?")
        assert msgs[-1] == {"role": "user", "content": "how many phones?"}

    def test_system_prompt_mentions_security_rules(self):
        # Critical rule the system prompt must communicate
        sys_content = initial_messages("x")[0]["content"]
        assert "INSERT" in sys_content
        assert "SELECT" in sys_content
        assert "DROP" in sys_content


# ---------------------------------------------------------------------------
# pipeline.answer_question — retry logic with mocked LLM and DB
# ---------------------------------------------------------------------------


class TestPipelineRetry:
    @pytest.fixture(autouse=True)
    def _patch_db(self, populated_engine, monkeypatch):
        """Force the populated_engine fixture to construct (which patches
        ro_engine), and disable result-review + explanation by default for
        the error-retry tests below — they're testing the guard / DB-error
        path, not review or explanation."""
        monkeypatch.setenv("MLX_VERIFY_RESULTS", "false")
        monkeypatch.setenv("MLX_EXPLAIN_RESULTS", "false")
        return populated_engine

    def test_first_try_success(self, monkeypatch):
        monkeypatch.setattr(
            llm_pipeline,
            "chat",
            lambda messages: "```sql\nSELECT brand FROM Device_Name\n```",
        )
        result = llm_pipeline.answer_question("list brands")
        assert len(result.attempts) == 1
        assert result.attempts[0].succeeded
        assert any(r["brand"] == "Apple" for r in result.rows)

    def test_self_correction_after_unsafe_sql(self, monkeypatch):
        responses = iter([
            "```sql\nDROP TABLE Device\n```",                       # rejected by guard
            "```sql\nSELECT brand FROM Device_Name LIMIT 1\n```",   # ok
        ])
        monkeypatch.setattr(llm_pipeline, "chat", lambda messages: next(responses))

        result = llm_pipeline.answer_question("show one brand")
        assert len(result.attempts) == 2
        assert result.attempts[0].error is not None
        assert "Refused unsafe SQL" in result.attempts[0].error
        assert result.attempts[1].succeeded
        assert len(result.rows) == 1

    def test_self_correction_after_db_error(self, monkeypatch):
        responses = iter([
            "```sql\nSELECT no_such_column FROM Device_Name\n```",  # SQL error
            "```sql\nSELECT brand FROM Device_Name LIMIT 1\n```",   # ok
        ])
        monkeypatch.setattr(llm_pipeline, "chat", lambda messages: next(responses))

        result = llm_pipeline.answer_question("show one brand")
        assert len(result.attempts) == 2
        assert result.attempts[0].error is not None
        assert result.attempts[1].succeeded

    def test_gives_up_after_max_attempts(self, monkeypatch):
        # Force max=3 to make the test fast
        monkeypatch.setenv("MLX_MAX_RETRIES", "3")
        # Always emits unsafe SQL — guard always rejects
        monkeypatch.setattr(
            llm_pipeline,
            "chat",
            lambda messages: "```sql\nDROP TABLE Device\n```",
        )

        result = llm_pipeline.answer_question("evil intent")
        assert len(result.attempts) == 3
        assert all(not a.succeeded for a in result.attempts)
        assert result.rows == []

    def test_max_attempts_clamps_to_minimum_1(self, monkeypatch):
        monkeypatch.setenv("MLX_MAX_RETRIES", "0")
        monkeypatch.setattr(
            llm_pipeline,
            "chat",
            lambda messages: "```sql\nSELECT 1 AS one\n```",
        )

        result = llm_pipeline.answer_question("one")
        # Even with MLX_MAX_RETRIES=0, the loop runs at least once.
        assert len(result.attempts) >= 1

    def test_retry_appends_to_message_history(self, monkeypatch):
        """The LLM should see the failed-attempt context on the second call."""
        captured = []

        def capturing_chat(messages):
            # Snapshot via list() — pipeline mutates `messages` after this
            # call returns, and we want to assert what *this* call saw.
            captured.append(list(messages))
            if len(captured) == 1:
                return "```sql\nDROP TABLE Device\n```"
            return "```sql\nSELECT brand FROM Device_Name LIMIT 1\n```"

        monkeypatch.setattr(llm_pipeline, "chat", capturing_chat)
        llm_pipeline.answer_question("retry me")

        # First call: just system + few-shot + user question
        assert len(captured) == 2
        # Second call must contain the failed-assistant + retry-user turns
        assert len(captured[1]) > len(captured[0])
        last_msg = captured[1][-1]
        assert last_msg["role"] == "user"
        assert "fail" in last_msg["content"].lower() or "error" in last_msg["content"].lower()


class TestPipelineReview:
    """Result-review (verification) loop — separate from the error-retry path."""

    @pytest.fixture(autouse=True)
    def _patch_db(self, populated_engine, monkeypatch):
        # Verification ON; explanation OFF — focus on the review semantics.
        monkeypatch.delenv("MLX_VERIFY_RESULTS", raising=False)
        monkeypatch.setenv("MLX_EXPLAIN_RESULTS", "false")
        return populated_engine

    def test_review_approves_first_result(self, monkeypatch):
        responses = iter([
            "```sql\nSELECT brand FROM Device_Name LIMIT 1\n```",
            "OK",
        ])
        monkeypatch.setattr(llm_pipeline, "chat", lambda messages: next(responses))

        result = llm_pipeline.answer_question("show a brand")
        assert len(result.attempts) == 2
        assert result.attempts[0].kind == "execution"
        assert result.attempts[0].succeeded
        assert result.attempts[1].kind == "review"
        assert result.attempts[1].succeeded
        assert result.attempts[1].judgment == "OK"

    def test_review_refines_then_approves(self, monkeypatch):
        responses = iter([
            "```sql\nSELECT model FROM Device_Name LIMIT 1\n```",
            "```sql\nSELECT brand FROM Device_Name LIMIT 2\n```",  # refinement
            "OK",
        ])
        monkeypatch.setattr(llm_pipeline, "chat", lambda messages: next(responses))

        result = llm_pipeline.answer_question("show brands")
        # exec1 succeeded, review-refine, exec2 succeeded, review-approve = 4
        assert len(result.attempts) == 4
        assert result.sql == "SELECT brand FROM Device_Name LIMIT 2"
        assert result.attempts[-1].judgment == "OK"

    def test_oscillation_guard(self, monkeypatch):
        responses = iter([
            "```sql\nSELECT brand FROM Device_Name LIMIT 1\n```",
            "```sql\nSELECT model FROM Device_Name LIMIT 1\n```",
            "```sql\nSELECT brand FROM Device_Name LIMIT 1\n```",  # same as #1
        ])
        monkeypatch.setattr(llm_pipeline, "chat", lambda messages: next(responses))

        result = llm_pipeline.answer_question("anything")
        # Loop should detect the duplicate SQL and bail with last successful result.
        assert any(a.judgment and "oscillation" in a.judgment for a in result.attempts)

    def test_verify_off_skips_review(self, monkeypatch):
        monkeypatch.setenv("MLX_VERIFY_RESULTS", "false")
        monkeypatch.setattr(
            llm_pipeline, "chat",
            lambda messages: "```sql\nSELECT brand FROM Device_Name LIMIT 1\n```",
        )
        result = llm_pipeline.answer_question("brands")
        assert len(result.attempts) == 1
        assert result.attempts[0].succeeded


class TestPipelineExplanation:
    """Final LLM turn that explains the result for the user."""

    @pytest.fixture(autouse=True)
    def _patch_db(self, populated_engine, monkeypatch):
        # Skip the review loop so this suite focuses on the explanation turn.
        monkeypatch.setenv("MLX_VERIFY_RESULTS", "false")
        monkeypatch.delenv("MLX_EXPLAIN_RESULTS", raising=False)
        return populated_engine

    def test_explanation_added_after_success(self, monkeypatch):
        responses = iter([
            "```sql\nSELECT brand FROM Device_Name LIMIT 2\n```",
            "Two brands are listed: Apple and Samsung.",
        ])
        monkeypatch.setattr(llm_pipeline, "chat", lambda messages: next(responses))

        result = llm_pipeline.answer_question("show brands")
        assert result.explanation == "Two brands are listed: Apple and Samsung."

    def test_explain_off_returns_none(self, monkeypatch):
        monkeypatch.setenv("MLX_EXPLAIN_RESULTS", "false")
        monkeypatch.setattr(
            llm_pipeline, "chat",
            lambda messages: "```sql\nSELECT brand FROM Device_Name LIMIT 1\n```",
        )
        result = llm_pipeline.answer_question("brands")
        assert result.explanation is None

    def test_explanation_strips_code_blocks(self, monkeypatch):
        """If the model accidentally emits SQL in the explanation, strip it."""
        responses = iter([
            "```sql\nSELECT 1\n```",
            "The result is 1. ```sql\nSELECT 1\n``` Just one row.",
        ])
        monkeypatch.setattr(llm_pipeline, "chat", lambda messages: next(responses))

        result = llm_pipeline.answer_question("just one")
        assert "```" not in (result.explanation or "")
        assert "The result is 1" in result.explanation
        assert "Just one row" in result.explanation
