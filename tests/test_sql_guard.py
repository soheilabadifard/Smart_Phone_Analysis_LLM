"""Security tests for the LLM SQL guard.

The guard is the second of two defenses on the Ask path (the first is the
read-only MariaDB user). These tests assert that the parser correctly
classifies SELECT-family statements as safe and rejects everything else.
"""

from __future__ import annotations

import pytest

from app.llm.sql_guard import UnsafeSQLError, ensure_select_only


# ---------------------------------------------------------------------------
# Allowed: SELECT, WITH, UNION
# ---------------------------------------------------------------------------


class TestAllowedStatements:
    def test_simple_select(self):
        sql = "SELECT id, brand FROM Device_Name"
        out = ensure_select_only(sql)
        assert "SELECT" in out.upper()

    def test_select_with_where(self):
        sql = "SELECT * FROM Device WHERE year >= 2023"
        ensure_select_only(sql)  # should not raise

    def test_select_with_join(self):
        sql = """
            SELECT dn.brand, d.year
            FROM Device d JOIN Device_Name dn ON dn.id = d.device_name_id
            WHERE d.price_eur < 500
        """
        ensure_select_only(sql)

    def test_with_cte(self):
        sql = """
            WITH per_year AS (
                SELECT year, COUNT(*) AS n FROM Device GROUP BY year
            )
            SELECT * FROM per_year ORDER BY year DESC
        """
        ensure_select_only(sql)

    def test_union(self):
        sql = """
            SELECT brand FROM Device_Name WHERE id < 5
            UNION
            SELECT brand FROM Device_Name WHERE id > 100
        """
        ensure_select_only(sql)

    def test_subquery_in_where(self):
        sql = """
            SELECT * FROM Device d
            WHERE d.price_eur > (SELECT AVG(price_eur) FROM Device)
        """
        ensure_select_only(sql)

    def test_window_function(self):
        sql = """
            SELECT brand, ROW_NUMBER() OVER (PARTITION BY year ORDER BY price_eur) AS rn
            FROM Device d JOIN Device_Name dn ON dn.id = d.device_name_id
        """
        ensure_select_only(sql)


# ---------------------------------------------------------------------------
# Rejected: write-side DML
# ---------------------------------------------------------------------------


class TestRejectsDML:
    @pytest.mark.parametrize(
        "sql",
        [
            "INSERT INTO Device_Name (brand, model) VALUES ('x', 'y')",
            "UPDATE Device SET price_eur = 0",
            "DELETE FROM Device WHERE id = 1",
            "REPLACE INTO Device_Name (id, brand, model) VALUES (1, 'x', 'y')",
        ],
    )
    def test_dml_rejected(self, sql):
        with pytest.raises(UnsafeSQLError):
            ensure_select_only(sql)


# ---------------------------------------------------------------------------
# Rejected: DDL
# ---------------------------------------------------------------------------


class TestRejectsDDL:
    @pytest.mark.parametrize(
        "sql",
        [
            "DROP TABLE Device_Name",
            "CREATE TABLE evil (id INT)",
            "ALTER TABLE Device ADD COLUMN evil INT",
            "TRUNCATE TABLE Device",
        ],
    )
    def test_ddl_rejected(self, sql):
        with pytest.raises(UnsafeSQLError):
            ensure_select_only(sql)


# ---------------------------------------------------------------------------
# Rejected: multiple statements (stacked queries)
# ---------------------------------------------------------------------------


class TestRejectsMultiStatement:
    def test_select_then_insert(self):
        sql = "SELECT 1; INSERT INTO Device_Name (brand, model) VALUES ('x', 'y')"
        with pytest.raises(UnsafeSQLError):
            ensure_select_only(sql)

    def test_select_then_drop(self):
        sql = "SELECT * FROM Device; DROP TABLE Device"
        with pytest.raises(UnsafeSQLError):
            ensure_select_only(sql)

    def test_two_selects_rejected(self):
        # Even two harmless SELECTs are rejected — single-statement only.
        sql = "SELECT 1; SELECT 2"
        with pytest.raises(UnsafeSQLError):
            ensure_select_only(sql)


# ---------------------------------------------------------------------------
# Rejected: empty / nonsense
# ---------------------------------------------------------------------------


class TestRejectsEmptyAndJunk:
    def test_empty_string_rejected(self):
        with pytest.raises(UnsafeSQLError):
            ensure_select_only("")

    def test_whitespace_only_rejected(self):
        with pytest.raises(UnsafeSQLError):
            ensure_select_only("   \n  \t  ")

    def test_non_sql_text_rejected(self):
        # sqlglot parses "SHOW TABLES" as a Show command — not SELECT-family
        with pytest.raises(UnsafeSQLError):
            ensure_select_only("SHOW TABLES")

    def test_explain_rejected(self):
        # EXPLAIN is read-only but still not a Select node — guard is strict
        with pytest.raises(UnsafeSQLError):
            ensure_select_only("EXPLAIN SELECT * FROM Device")
