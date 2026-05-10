"""Run the NL→SQL benchmark against a live MLX server.

Local-only — not run in CI. Requires:
  1. mlx_lm.server running on MLX_BASE_URL (default http://localhost:8080/v1)
  2. The populated MariaDB reachable via .env (DB_HOST/DB_PORT/...)

Usage:
    python -m evaluation.run_benchmark
    python -m evaluation.run_benchmark --json results.json
    python -m evaluation.run_benchmark --filter Q1,Q5,Q9 --quiet

Per-question result is printed in real time. Final scorecard reports
guard-passed / executed / result-correct rates and writes a JSON file when
--json is given.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Make backend/ + repo root importable when invoked as `python -m evaluation.*`
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

from app.db import ro_engine  # noqa: E402
from app.llm.pipeline import answer_question  # noqa: E402
from evaluation.questions import QUESTIONS, BenchmarkQuestion  # noqa: E402
from evaluation.scorer import (  # noqa: E402
    BenchmarkScorecard,
    QuestionScore,
    results_equivalent,
)


def _execute_reference(sql: str) -> tuple[list[str], list[dict]]:
    with ro_engine().connect() as conn:
        r = conn.execute(text(sql))
        return list(r.keys()), [dict(row) for row in r.mappings().all()]


def _categorise(qs: QuestionScore) -> str:
    if not qs.llm_sql:
        return "no-sql"
    if not qs.guard_passed:
        return "guard-rejected"
    if not qs.executed:
        return "execution-error"
    if not qs.result_correct:
        return "wrong-result"
    return "correct"


def _score_one(q: BenchmarkQuestion, *, quiet: bool = False) -> QuestionScore:
    qs = QuestionScore(qid=q.id, question=q.question, category="no-sql")

    # 1) reference SQL — must succeed; otherwise the benchmark question is bad
    try:
        ref_cols, ref_rows = _execute_reference(q.reference_sql)
    except SQLAlchemyError as e:
        qs.error = f"reference SQL failed: {e}"
        qs.category = "reference-error"
        return qs

    # 2) LLM pipeline
    t0 = time.time()
    try:
        result = answer_question(q.question)
    except Exception as e:  # noqa: BLE001 — runner robustness
        qs.error = f"pipeline raised: {e}"
        qs.elapsed_sec = time.time() - t0
        qs.category = "no-sql"
        return qs
    qs.elapsed_sec = time.time() - t0
    qs.n_attempts = len(result.attempts)
    qs.llm_sql = result.sql or ""

    if not result.attempts:
        qs.category = "no-sql"
        return qs

    last = result.attempts[-1]
    # Guard passed if at least one attempt didn't error with "Refused unsafe SQL"
    qs.guard_passed = any(
        not (a.error and "Refused unsafe SQL" in (a.error or ""))
        for a in result.attempts
    )

    # Executed if the final accepted attempt succeeded (i.e. not failed-out)
    qs.executed = last.succeeded and bool(result.columns)

    if qs.executed:
        qs.result_correct = results_equivalent(
            result.columns, result.rows, ref_cols, ref_rows,
            comparison=q.comparison,
        )

    qs.category = _categorise(qs)
    if not quiet:
        marker = {"correct": "✓", "wrong-result": "≈", "execution-error": "✗",
                  "guard-rejected": "✗", "no-sql": "✗",
                  "reference-error": "!"}.get(qs.category, "?")
        print(f"  {marker} {q.id}: {qs.category}  "
              f"(attempts={qs.n_attempts}, elapsed={qs.elapsed_sec:.1f}s)")
    return qs


def run_benchmark(filter_ids: list[str] | None = None, *, quiet: bool = False) -> BenchmarkScorecard:
    qs_filter = set(filter_ids or [])
    selected = [q for q in QUESTIONS if not qs_filter or q.id in qs_filter]
    sc = BenchmarkScorecard()
    if not quiet:
        print(f"Running {len(selected)} question(s)…")
    for q in selected:
        sc.scores.append(_score_one(q, quiet=quiet))
    return sc


def _to_jsonable(sc: BenchmarkScorecard) -> dict:
    return {
        "summary": {
            "n": sc.n,
            "guard_passed": sc.n_guard_passed,
            "executed": sc.n_executed,
            "result_correct": sc.n_correct,
        },
        "scores": [
            {
                "qid": s.qid,
                "question": s.question,
                "category": s.category,
                "guard_passed": s.guard_passed,
                "executed": s.executed,
                "result_correct": s.result_correct,
                "n_attempts": s.n_attempts,
                "elapsed_sec": s.elapsed_sec,
                "llm_sql": s.llm_sql,
                "error": s.error,
            }
            for s in sc.scores
        ],
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--filter", help="Comma-separated question ids to run (e.g. Q1,Q5)")
    p.add_argument("--json", help="Write the full scorecard to this JSON file")
    p.add_argument("--quiet", action="store_true", help="Suppress per-question lines")
    args = p.parse_args()

    ids = [x.strip() for x in args.filter.split(",")] if args.filter else None
    sc = run_benchmark(ids, quiet=args.quiet)
    print()
    print(sc.summary())

    if args.json:
        Path(args.json).write_text(json.dumps(_to_jsonable(sc), indent=2))
        print(f"\nWrote scorecard to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
