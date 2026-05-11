"""Tests for the LLM client wrapper and pipeline retry logic.

The actual LLM call (`chat`) is monkeypatched in every test — we never
hit a real model. These tests assert message structure and the pipeline's
retry/recovery behavior.
"""

from __future__ import annotations

import pytest

from app.llm import client as llm_client
from app.llm import pipeline as llm_pipeline
from app.llm.client import extract_sql, has_fenced_sql, initial_messages
from app.llm.few_shot import EXAMPLES


def _stream(responses):
    """chat_stream-shaped mock: each invocation consumes the next entry
    from `responses` and yields it as a single token. Accepts the new
    `stop` + `max_tokens` kwargs the pipeline now passes (and ignores them).
    """
    it = responses if hasattr(responses, "__next__") else iter(responses)

    def _impl(messages, stop=None, max_tokens=None):
        yield next(it)

    return _impl


def _stream_single(text):
    """One-shot chat_stream mock that always yields the same text."""
    def _impl(messages, stop=None, max_tokens=None):
        yield text
    return _impl


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


class TestHasFencedSQL:
    """Used by the review loop: True ⇒ refinement, False ⇒ approval."""

    def test_sql_tagged_block_is_refinement(self):
        assert has_fenced_sql("```sql\nSELECT 1\n```") is True

    def test_uppercase_sql_tag_is_refinement(self):
        assert has_fenced_sql("```SQL\nSELECT 1\n```") is True

    def test_bare_fence_is_not_a_refinement(self):
        # Bare ``` blocks (e.g. the model emitting prose in a code block)
        # must be treated as approval, not as a SQL refinement.
        assert has_fenced_sql("OK\n```\nthis isn't sql\n```") is False

    def test_plain_ok_is_approval(self):
        assert has_fenced_sql("OK") is False

    def test_prose_only_is_approval(self):
        assert has_fenced_sql("That looks correct.") is False


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
        # Critical rules the system prompt must communicate. REPLACE is in the
        # guard's _DISALLOWED list too — keep them in sync.
        sys_content = initial_messages("x")[0]["content"]
        for kw in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER",
                   "TRUNCATE", "CREATE", "MERGE", "REPLACE", "SELECT"):
            assert kw in sys_content, f"system prompt missing keyword {kw!r}"


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
            "chat_stream",
            _stream_single("```sql\nSELECT brand FROM Device_Name\n```"),
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
        monkeypatch.setattr(llm_pipeline, "chat_stream", _stream(responses))

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
        monkeypatch.setattr(llm_pipeline, "chat_stream", _stream(responses))

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
            "chat_stream",
            _stream_single("```sql\nDROP TABLE Device\n```"),
        )

        result = llm_pipeline.answer_question("evil intent")
        assert len(result.attempts) == 3
        assert all(not a.succeeded for a in result.attempts)
        assert result.rows == []

    def test_max_attempts_clamps_to_minimum_1(self, monkeypatch):
        monkeypatch.setenv("MLX_MAX_RETRIES", "0")
        monkeypatch.setattr(
            llm_pipeline,
            "chat_stream",
            _stream_single("```sql\nSELECT 1 AS one\n```"),
        )

        result = llm_pipeline.answer_question("one")
        # Even with MLX_MAX_RETRIES=0, the loop runs at least once.
        assert len(result.attempts) >= 1

    def test_retry_appends_to_message_history(self, monkeypatch):
        """The LLM should see the failed-attempt context on the second call."""
        captured = []

        def capturing_chat_stream(messages, stop=None, max_tokens=None):
            # Snapshot via list() — pipeline mutates `messages` after this
            # call returns, and we want to assert what *this* call saw.
            captured.append(list(messages))
            if len(captured) == 1:
                yield "```sql\nDROP TABLE Device\n```"
                return
            yield "```sql\nSELECT brand FROM Device_Name LIMIT 1\n```"

        monkeypatch.setattr(llm_pipeline, "chat_stream", capturing_chat_stream)
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
        monkeypatch.setattr(llm_pipeline, "chat_stream", _stream(responses))

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
        monkeypatch.setattr(llm_pipeline, "chat_stream", _stream(responses))

        result = llm_pipeline.answer_question("show brands")
        # exec1 succeeded, review-refine, exec2 succeeded, review-approve = 4
        assert len(result.attempts) == 4
        assert result.sql == "SELECT brand FROM Device_Name LIMIT 2"
        assert result.attempts[-1].judgment == "OK"

    def test_oscillation_guard(self, monkeypatch):
        """When the model refines to a previously-executed SQL, return the
        most-recent stored last_success (which is exec #2's SQL, not exec #1).
        """
        responses = iter([
            "```sql\nSELECT brand FROM Device_Name LIMIT 1\n```",  # exec1
            "```sql\nSELECT model FROM Device_Name LIMIT 1\n```",  # review refines → exec2
            "```sql\nSELECT brand FROM Device_Name LIMIT 1\n```",  # refines back → oscillation
        ])
        monkeypatch.setattr(llm_pipeline, "chat_stream", _stream(responses))

        result = llm_pipeline.answer_question("anything")
        # Last attempt is the oscillation-guard review entry.
        assert result.attempts[-1].kind == "review"
        assert result.attempts[-1].succeeded
        assert "oscillation" in (result.attempts[-1].judgment or "")
        # Returns the second-stored last_success (the refinement that *did* run),
        # not the first.
        assert result.sql == "SELECT model FROM Device_Name LIMIT 1"

    def test_verify_off_skips_review(self, monkeypatch):
        monkeypatch.setenv("MLX_VERIFY_RESULTS", "false")
        monkeypatch.setattr(
            llm_pipeline, "chat_stream",
            _stream_single("```sql\nSELECT brand FROM Device_Name LIMIT 1\n```"),
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
        monkeypatch.setattr(llm_pipeline, "chat_stream", _stream(responses))

        result = llm_pipeline.answer_question("show brands")
        assert result.explanation == "Two brands are listed: Apple and Samsung."

    def test_explain_off_returns_none(self, monkeypatch):
        monkeypatch.setenv("MLX_EXPLAIN_RESULTS", "false")
        monkeypatch.setattr(
            llm_pipeline, "chat_stream",
            _stream_single("```sql\nSELECT brand FROM Device_Name LIMIT 1\n```"),
        )
        result = llm_pipeline.answer_question("brands")
        assert result.explanation is None

    def test_explanation_strips_code_blocks(self, monkeypatch):
        """If the model accidentally emits SQL in the explanation, strip it."""
        responses = iter([
            "```sql\nSELECT 1\n```",
            "The result is 1. ```sql\nSELECT 1\n``` Just one row.",
        ])
        monkeypatch.setattr(llm_pipeline, "chat_stream", _stream(responses))

        result = llm_pipeline.answer_question("just one")
        assert "```" not in (result.explanation or "")
        assert "The result is 1" in result.explanation
        assert "Just one row" in result.explanation
