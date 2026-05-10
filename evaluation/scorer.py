"""Result-set comparison + per-question scoring for the NL→SQL benchmark.

Pure functions only — no DB, no LLM. Tested in tests/test_benchmark_scorer.py
so the comparison logic is covered by CI even though the runner is not.

A scored result has three booleans + a category:
  - guard_passed:    SQL passed sqlglot's SELECT-only check
  - executed:        SQL ran against the DB without raising
  - result_correct:  result rows match the reference query's rows
  - category:        'correct' | 'wrong-result' | 'execution-error' |
                     'guard-rejected' | 'no-sql'
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class QuestionScore:
    qid: str
    question: str
    category: str  # see module docstring
    guard_passed: bool = False
    executed: bool = False
    result_correct: bool = False
    llm_sql: str = ""
    error: str | None = None
    n_attempts: int = 0
    elapsed_sec: float | None = None


@dataclass
class BenchmarkScorecard:
    scores: list[QuestionScore] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.scores)

    @property
    def n_guard_passed(self) -> int:
        return sum(1 for s in self.scores if s.guard_passed)

    @property
    def n_executed(self) -> int:
        return sum(1 for s in self.scores if s.executed)

    @property
    def n_correct(self) -> int:
        return sum(1 for s in self.scores if s.result_correct)

    def summary(self) -> str:
        n = max(1, self.n)
        return (
            f"NL→SQL benchmark: {self.n} questions\n"
            f"  guard-passed:   {self.n_guard_passed:>3} / {self.n}  "
            f"({100 * self.n_guard_passed / n:.0f}%)\n"
            f"  executed:       {self.n_executed:>3} / {self.n}  "
            f"({100 * self.n_executed / n:.0f}%)\n"
            f"  result-correct: {self.n_correct:>3} / {self.n}  "
            f"({100 * self.n_correct / n:.0f}%)"
        )


# --- comparison primitives -------------------------------------------------


def _normalise_value(v: Any) -> Any:
    """Reduce small numeric noise + None handling for comparison.

    Floats are rounded to 4 decimals; Decimal/numeric types are coerced via
    float; everything else is left alone (str, int, bool, None).
    """
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return round(float(v), 4)
    # SQLAlchemy may hand us Decimal — coerce by str then float when possible.
    try:
        return round(float(v), 4)
    except (TypeError, ValueError):
        return v


def _normalise_row(row: dict, columns: list[str] | None = None) -> tuple:
    """Convert a row dict to a tuple of normalised values.

    If `columns` is given, the tuple is in that column order; otherwise we
    use sorted keys so two rows with the same data but different key orderings
    still compare equal.
    """
    keys = columns if columns is not None else sorted(row.keys())
    return tuple(_normalise_value(row.get(k)) for k in keys)


def results_equivalent(
    a_cols: list[str],
    a_rows: list[dict],
    b_cols: list[str],
    b_rows: list[dict],
    *,
    comparison: str = "set",
) -> bool:
    """Compare two query results.

    Column order doesn't matter when `comparison='set'` (each row is sorted
    by key). Row order doesn't matter for 'set'; row order is part of the
    comparison for 'ordered'. The number of rows must match in both modes.
    Column *names* must match as a set in both modes — otherwise we'd be
    comparing apples to oranges.
    """
    if set(a_cols) != set(b_cols):
        return False
    if len(a_rows) != len(b_rows):
        return False

    a_norm = [_normalise_row(r) for r in a_rows]
    b_norm = [_normalise_row(r) for r in b_rows]

    if comparison == "ordered":
        return a_norm == b_norm

    # set comparison: sort both sides
    return sorted(a_norm) == sorted(b_norm)
