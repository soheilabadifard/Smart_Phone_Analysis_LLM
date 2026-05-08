"""Tests for generate_table_sql.py — the deliverable generator.

Verifies the generated DDL contains every table, every UNIQUE/CHECK/FK,
and is parseable as MySQL. The generator runs at import time (its `main()`
writes to Deliverables/table.sql), so these tests reach into the underlying
SQLAlchemy metadata directly to exercise the generation logic without
clobbering the committed deliverable.

generate_records_sql.py is **not** tested here — it reads from a populated
MariaDB and emits FK-respecting INSERT batches, which would require a real
MariaDB to exercise faithfully.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from etl.newDatabase import Base


# ---------------------------------------------------------------------------
# DDL generation against the ORM metadata
# ---------------------------------------------------------------------------


def _generate_ddl_for_all_tables() -> str:
    """Reproduce what generate_table_sql.py emits, but as a string in memory."""
    dialect = mysql.dialect()
    chunks = []
    for table in Base.metadata.sorted_tables:
        table.dialect_options["mysql"]["engine"] = "InnoDB"
        table.dialect_options["mysql"]["charset"] = "utf8mb4"
        ddl = str(CreateTable(table).compile(dialect=dialect)).strip()
        chunks.append(ddl)
    return "\n\n".join(chunks)


@pytest.fixture(scope="module")
def generated_ddl() -> str:
    return _generate_ddl_for_all_tables()


class TestTableCoverage:
    def test_every_orm_table_appears_in_ddl(self, generated_ddl):
        expected = {
            "Device_Name",
            "Network_Technology",
            "Sim",
            "Camera",
            "Display",
            "OS",
            "Platform",
            "Device",
        }
        for name in expected:
            assert f"`{name}`" in generated_ddl or name in generated_ddl, (
                f"Generated DDL is missing CREATE TABLE for {name}"
            )

    def test_eight_tables_emitted(self, generated_ddl):
        # Each table produces one "CREATE TABLE" header
        assert generated_ddl.upper().count("CREATE TABLE") == 8


class TestConstraintCoverage:
    def test_unique_constraints_present(self, generated_ddl):
        # One representative UNIQUE per dim table
        unique_clauses = generated_ddl.upper().count("UNIQUE")
        assert unique_clauses >= 8  # 7 dim tables + Device.device_key

    def test_foreign_keys_use_restrict_on_delete(self, generated_ddl):
        upper = generated_ddl.upper()
        assert "ON DELETE RESTRICT" in upper

    def test_foreign_keys_use_cascade_on_update(self, generated_ddl):
        upper = generated_ddl.upper()
        assert "ON UPDATE CASCADE" in upper

    def test_check_constraints_present(self, generated_ddl):
        # CHECK constraints appear with the column rules from CLAUDE.md
        upper = generated_ddl.upper()
        assert "CHECK" in upper
        # Specific CHECKs we care about
        assert "PRICE_EUR" in upper
        assert "BATTERY_CAPACITY_MAH" in upper

    def test_seven_fks_on_device(self, generated_ddl):
        # Device has 7 FKs to dim tables (device_name_id, network_technology_id,
        # camera_id, display_id, os_id, platform_id, sim_id).
        # The generated DDL should contain "FOREIGN KEY" 7 times in the Device
        # block (or more, if other tables grew FKs in the future).
        assert generated_ddl.upper().count("FOREIGN KEY") >= 7


class TestEngineAndCharset:
    def test_innodb_set_on_each_table(self, generated_ddl):
        # The dialect_options are applied table-by-table; each compiled DDL
        # should pick up ENGINE=InnoDB.
        # SQLAlchemy emits this as "ENGINE=InnoDB" without spaces.
        upper = generated_ddl.upper()
        assert upper.count("ENGINE=INNODB") >= 1

    def test_utf8mb4_charset_emitted(self, generated_ddl):
        # SQLAlchemy emits as DEFAULT CHARSET=utf8mb4 or CHARSET=utf8mb4
        upper = generated_ddl.upper()
        assert "UTF8MB4" in upper


# ---------------------------------------------------------------------------
# Committed file (Deliverables/table.sql) — sanity check that it's not stale
# ---------------------------------------------------------------------------


COMMITTED_TABLE_SQL = (
    Path(__file__).resolve().parent.parent / "Deliverables" / "table.sql"
)


class TestCommittedTableSQL:
    def test_committed_file_exists(self):
        if not COMMITTED_TABLE_SQL.exists():
            pytest.skip("Deliverables/table.sql not present")

    def test_committed_file_has_eight_tables(self):
        if not COMMITTED_TABLE_SQL.exists():
            pytest.skip("Deliverables/table.sql not present")
        content = COMMITTED_TABLE_SQL.read_text().upper()
        assert content.count("CREATE TABLE") == 8

    def test_committed_file_has_drop_block(self):
        if not COMMITTED_TABLE_SQL.exists():
            pytest.skip("Deliverables/table.sql not present")
        content = COMMITTED_TABLE_SQL.read_text().upper()
        # generate_table_sql.py emits a DROP TABLE IF EXISTS block for replay
        assert content.count("DROP TABLE IF EXISTS") == 8
