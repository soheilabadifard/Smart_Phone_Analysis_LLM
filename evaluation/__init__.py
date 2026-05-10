"""NL→SQL benchmark for the Ask path.

Module layout:
  - questions.py — hand-curated (question, reference_sql) pairs
  - scorer.py    — pure comparison logic (CI-testable)
  - run_benchmark.py — local-only CLI runner that hits a real MLX

The runner is NOT part of the pytest CI pass. Run it manually after starting
mlx_lm.server:

    python -m evaluation.run_benchmark --json benchmark_results.json

The scorer is tested in tests/test_benchmark_scorer.py against a few
hand-built result sets, so the comparison logic itself is covered by CI.
"""
