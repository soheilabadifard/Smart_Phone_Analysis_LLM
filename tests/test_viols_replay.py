"""Replay Deliverables/viols.sql against the populated test DB.

The deliverable lists 5 statements that intentionally violate the schema's
integrity constraints. We parse the file, execute each, and assert each one
raises an IntegrityError. If a future schema change accidentally relaxes a
constraint, this test catches it before the screenshot evidence in
Deliverables/Viol-ScreenShots/ goes stale.

Two of the five violations assume the deliverable's `alcatel`-branded seed
data that our test seed doesn't have. The `viols_engine` fixture adds the
prerequisite rows so each statement violates its intended constraint.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

VIOLS_PATH = Path(__file__).resolve().parent.parent / "Deliverables" / "viols.sql"


def _strip_comments(sql: str) -> str:
    """Remove `-- ...` line comments without touching string literals."""
    return "\n".join(line.split("--", 1)[0] for line in sql.splitlines())


def _split_statements(sql: str) -> list[str]:
    """Split top-level SQL statements by `;`. Sufficient for viols.sql, which
    has no string literals containing semicolons."""
    cleaned = _strip_comments(sql)
    return [s.strip() for s in cleaned.split(";") if s.strip()]


@pytest.fixture(scope="module")
def viols_statements() -> list[str]:
    if not VIOLS_PATH.exists():
        pytest.skip(f"{VIOLS_PATH} missing — Deliverables not present")
    statements = _split_statements(VIOLS_PATH.read_text())
    if len(statements) != 5:
        pytest.fail(
            f"Expected 5 violation statements in viols.sql, got {len(statements)}"
        )
    return statements


@pytest.fixture
def viols_engine(populated_engine):
    """populated_engine plus the prerequisite rows the deliverable assumes.

    Statement (a) inserts ('alcatel', '1B (2022)') — must already be present.
    Statement (b) updates Device_Name id=1's model to '1L Pro (2021)' and
    expects a UNIQUE collision; in our seed id=1 is ('Apple', 'iPhone 15'),
    so we also seed ('Apple', '1L Pro (2021)') for the collision.
    """
    with populated_engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO Device_Name (brand, model) VALUES ('alcatel', '1B (2022)')"
        ))
        conn.execute(text(
            "INSERT INTO Device_Name (brand, model) VALUES ('Apple', '1L Pro (2021)')"
        ))
    return populated_engine


# ---------------------------------------------------------------------------
# File-shape sanity
# ---------------------------------------------------------------------------


class TestViolsFile:
    def test_has_five_statements(self, viols_statements):
        assert len(viols_statements) == 5

    def test_statements_cover_expected_operations(self, viols_statements):
        joined = " ".join(viols_statements).upper()
        assert joined.count("INSERT") >= 2  # (a), (c)
        assert joined.count("UPDATE") >= 2  # (b), (e)
        assert joined.count("DELETE") >= 1  # (d)


# ---------------------------------------------------------------------------
# Per-statement: each must raise an IntegrityError when executed
# ---------------------------------------------------------------------------


class TestViolsReplay:
    def test_a_insert_unique_brand_model(self, viols_engine, viols_statements):
        """(a) Re-INSERT (alcatel, 1B (2022)) → uq_device_name_brand_model fires."""
        stmt = viols_statements[0]
        with viols_engine.begin() as conn:
            with pytest.raises(IntegrityError):
                conn.execute(text(stmt))

    def test_b_update_unique_brand_model(self, viols_engine, viols_statements):
        """(b) UPDATE id=1's model to '1L Pro (2021)' → collides with seeded
        (Apple, 1L Pro (2021)) → uq_device_name_brand_model fires."""
        stmt = viols_statements[1]
        with viols_engine.begin() as conn:
            with pytest.raises(IntegrityError):
                conn.execute(text(stmt))

    def test_c_insert_fk_violation(self, viols_engine, viols_statements):
        """(c) INSERT Device with device_name_id=999999 → FK violation."""
        stmt = viols_statements[2]
        with viols_engine.begin() as conn:
            with pytest.raises(IntegrityError):
                conn.execute(text(stmt))

    def test_d_delete_on_restrict(self, viols_engine, viols_statements):
        """(d) DELETE Device_Name id=1 → ON DELETE RESTRICT fires
        because seeded Device id=1 and id=5 reference it."""
        stmt = viols_statements[3]
        with viols_engine.begin() as conn:
            with pytest.raises(IntegrityError):
                conn.execute(text(stmt))

    def test_e_update_fk_violation(self, viols_engine, viols_statements):
        """(e) UPDATE Device id=1 SET device_name_id=999999 → FK violation."""
        stmt = viols_statements[4]
        with viols_engine.begin() as conn:
            with pytest.raises(IntegrityError):
                conn.execute(text(stmt))


class TestViolsReplayAll:
    """Single-shot run-them-all check, useful for catching new violations
    that get added without per-statement coverage."""

    def test_every_statement_raises_integrity_error(self, viols_engine, viols_statements):
        for index, stmt in enumerate(viols_statements, start=1):
            with viols_engine.begin() as conn:
                try:
                    conn.execute(text(stmt))
                except (IntegrityError, OperationalError):
                    continue
                pytest.fail(
                    f"viols.sql statement #{index} did NOT raise an integrity "
                    f"error — schema constraint may have been relaxed:\n{stmt}"
                )
