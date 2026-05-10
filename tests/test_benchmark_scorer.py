"""Tests for evaluation/scorer.py — pure result-set comparison logic.

The runner in evaluation/run_benchmark.py is local-only (it hits a real MLX
+ MariaDB), but the scorer is library code and worth covering in CI.
"""

from __future__ import annotations

import pytest

from evaluation.scorer import (
    BenchmarkScorecard,
    QuestionScore,
    results_equivalent,
)


class TestResultsEquivalent:
    def test_identical_results_match(self):
        cols = ["brand", "n"]
        rows = [{"brand": "Apple", "n": 5}, {"brand": "Samsung", "n": 12}]
        assert results_equivalent(cols, rows, cols, rows) is True

    def test_set_mode_ignores_row_order(self):
        cols = ["brand", "n"]
        rows_a = [{"brand": "Apple", "n": 5}, {"brand": "Samsung", "n": 12}]
        rows_b = [{"brand": "Samsung", "n": 12}, {"brand": "Apple", "n": 5}]
        assert results_equivalent(cols, rows_a, cols, rows_b, comparison="set") is True

    def test_ordered_mode_respects_row_order(self):
        cols = ["brand", "n"]
        rows_a = [{"brand": "Apple", "n": 5}, {"brand": "Samsung", "n": 12}]
        rows_b = [{"brand": "Samsung", "n": 12}, {"brand": "Apple", "n": 5}]
        assert results_equivalent(cols, rows_a, cols, rows_b, comparison="ordered") is False

    def test_different_row_count_fails(self):
        cols = ["brand"]
        a = [{"brand": "Apple"}]
        b = [{"brand": "Apple"}, {"brand": "Samsung"}]
        assert results_equivalent(cols, a, cols, b) is False

    def test_different_column_set_fails(self):
        a_cols, a_rows = ["brand"], [{"brand": "Apple"}]
        b_cols, b_rows = ["model"], [{"model": "Apple"}]
        assert results_equivalent(a_cols, a_rows, b_cols, b_rows) is False

    def test_column_order_doesnt_matter_in_set_mode(self):
        a_cols = ["brand", "n"]
        b_cols = ["n", "brand"]
        rows = [{"brand": "Apple", "n": 5}]
        assert results_equivalent(a_cols, rows, b_cols, rows, comparison="set") is True

    def test_float_noise_within_tolerance(self):
        cols = ["x"]
        a = [{"x": 1.234567}]
        b = [{"x": 1.234571}]  # same to 4 dp
        assert results_equivalent(cols, a, cols, b) is True

    def test_float_difference_outside_tolerance(self):
        cols = ["x"]
        a = [{"x": 1.234}]
        b = [{"x": 1.235}]
        assert results_equivalent(cols, a, cols, b) is False

    def test_none_values_compare_equal(self):
        cols = ["brand", "price"]
        a = [{"brand": "X", "price": None}]
        b = [{"brand": "X", "price": None}]
        assert results_equivalent(cols, a, cols, b) is True

    def test_none_vs_zero_differ(self):
        cols = ["price"]
        a = [{"price": None}]
        b = [{"price": 0}]
        assert results_equivalent(cols, a, cols, b) is False

    def test_int_and_float_with_same_value_equal(self):
        cols = ["n"]
        a = [{"n": 5}]
        b = [{"n": 5.0}]
        assert results_equivalent(cols, a, cols, b) is True

    def test_string_values_compared_exactly(self):
        cols = ["s"]
        a = [{"s": "Apple"}]
        b = [{"s": "apple"}]
        assert results_equivalent(cols, a, cols, b) is False


class TestBenchmarkScorecard:
    def test_empty_scorecard_summary(self):
        sc = BenchmarkScorecard()
        out = sc.summary()
        assert "0 questions" in out

    def test_counts_aggregate(self):
        sc = BenchmarkScorecard(scores=[
            QuestionScore("Q1", "q1", "correct", True, True, True),
            QuestionScore("Q2", "q2", "wrong-result", True, True, False),
            QuestionScore("Q3", "q3", "guard-rejected", False, False, False),
        ])
        assert sc.n == 3
        assert sc.n_guard_passed == 2
        assert sc.n_executed == 2
        assert sc.n_correct == 1
