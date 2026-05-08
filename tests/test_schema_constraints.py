"""Schema constraint integrity tests.

For every constraint declared on the ORM (CHECK, UNIQUE, NOT NULL, FK), we
construct a violating INSERT/UPDATE/DELETE and assert the engine rejects it.
This proves the integrity work in the proposal is wired through to executing
SQL — a regression here would be silent otherwise.

NOTE: SQLite enforces FKs only when ``PRAGMA foreign_keys=ON`` (set by
conftest.py) and treats CHECK expressions slightly differently from MariaDB.
For each constraint listed in Project_Proposal.pdf §2.1, we verify it fires.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError


def _exec(engine, sql: str, **params) -> None:
    """Execute INSERT/UPDATE/DELETE in a transaction. Raises on violation."""
    with engine.begin() as conn:
        conn.execute(text(sql), params)


# ---------------------------------------------------------------------------
# UNIQUE
# ---------------------------------------------------------------------------


class TestUniqueConstraints:
    def test_device_name_unique_brand_model(self, populated_engine):
        with pytest.raises(IntegrityError):
            _exec(
                populated_engine,
                "INSERT INTO Device_Name (brand, model) VALUES ('Apple', 'iPhone 15')",
            )

    def test_device_name_unique_allows_distinct_model(self, populated_engine):
        # Same brand, different model → must succeed.
        _exec(
            populated_engine,
            "INSERT INTO Device_Name (brand, model) VALUES ('Apple', 'iPhone 16')",
        )
        with populated_engine.connect() as conn:
            count = conn.execute(text(
                "SELECT COUNT(*) FROM Device_Name WHERE brand = 'Apple'"
            )).scalar()
        assert count >= 2

    def test_network_technology_unique(self, populated_engine):
        with pytest.raises(IntegrityError):
            _exec(
                populated_engine,
                "INSERT INTO Network_Technology (technology) VALUES ('GSM / HSPA / LTE / 5G')",
            )

    def test_os_unique_pair(self, populated_engine):
        with pytest.raises(IntegrityError):
            _exec(
                populated_engine,
                "INSERT INTO OS (os_name, os_version) VALUES ('iOS', '17')",
            )

    def test_platform_unique_profile(self, populated_engine):
        with pytest.raises(IntegrityError):
            _exec(
                populated_engine,
                "INSERT INTO Platform (chipset_manufacturer, cpu_core_count, "
                "internal_storage_gb, ram_gb) "
                "VALUES ('Apple', 6, 128, 6)",
            )

    def test_sim_unique_pair(self, populated_engine):
        with pytest.raises(IntegrityError):
            _exec(
                populated_engine,
                "INSERT INTO Sim (sim_count, sim_type) VALUES ('dual', 'nano')",
            )

    def test_device_unique_device_key(self, populated_engine):
        with pytest.raises(IntegrityError):
            _exec(
                populated_engine,
                """INSERT INTO Device (
                    device_key, device_name_id, network_technology_id, year,
                    launch_status, battery_capacity_mah, camera_id, display_id,
                    weight, length, width, height, volume, os_id, platform_id,
                    sim_id, price_eur
                ) VALUES (
                    'k1',  -- collides with seeded device id=1
                    1, 1, 2024, 'Available', 4000, 1, 1,
                    180.0, 150.0, 70.0, 8.0, 84000.0, 1, 1, 1, 599.0
                )""",
            )


# ---------------------------------------------------------------------------
# CHECK
# ---------------------------------------------------------------------------


class TestCheckConstraints:
    def test_price_eur_min_zero(self, populated_engine):
        with pytest.raises(IntegrityError):
            _exec(
                populated_engine,
                "UPDATE Device SET price_eur = -1.0 WHERE id = 1",
            )

    def test_year_range(self, populated_engine):
        with pytest.raises(IntegrityError):
            _exec(populated_engine, "UPDATE Device SET year = 1900 WHERE id = 1")
        with pytest.raises(IntegrityError):
            _exec(populated_engine, "UPDATE Device SET year = 2050 WHERE id = 1")

    def test_battery_capacity_positive(self, populated_engine):
        with pytest.raises(IntegrityError):
            _exec(
                populated_engine,
                "UPDATE Device SET battery_capacity_mah = 0 WHERE id = 1",
            )

    def test_launch_status_enum(self, populated_engine):
        with pytest.raises(IntegrityError):
            _exec(
                populated_engine,
                "UPDATE Device SET launch_status = 'BogusStatus' WHERE id = 1",
            )

    def test_dimensions_must_be_positive(self, populated_engine):
        for col in ("weight", "length", "width", "height", "volume"):
            with pytest.raises(IntegrityError):
                _exec(populated_engine, f"UPDATE Device SET {col} = 0 WHERE id = 1")

    def test_ram_gb_positive(self, populated_engine):
        with pytest.raises(IntegrityError):
            _exec(populated_engine, "UPDATE Platform SET ram_gb = 0 WHERE id = 1")

    def test_internal_storage_positive(self, populated_engine):
        with pytest.raises(IntegrityError):
            _exec(
                populated_engine,
                "UPDATE Platform SET internal_storage_gb = 0 WHERE id = 1",
            )

    def test_camera_main_count_non_negative(self, populated_engine):
        with pytest.raises(IntegrityError):
            _exec(
                populated_engine,
                "UPDATE Camera SET main_cameras_num = -1 WHERE id = 1",
            )

    def test_camera_main_resolution_positive(self, populated_engine):
        with pytest.raises(IntegrityError):
            _exec(
                populated_engine,
                "UPDATE Camera SET highest_maincam_res = 0 WHERE id = 1",
            )

    def test_display_size_positive(self, populated_engine):
        with pytest.raises(IntegrityError):
            _exec(
                populated_engine,
                "UPDATE Display SET display_size_inch = 0 WHERE id = 1",
            )

    def test_screen_to_body_ratio_non_negative(self, populated_engine):
        # Note: implementation only enforces >= 0 (no upper bound — wraparound
        # displays exceed 100%); see CLAUDE.md.
        with pytest.raises(IntegrityError):
            _exec(
                populated_engine,
                "UPDATE Display SET screen_to_body_ratio = -1 WHERE id = 1",
            )

    def test_sim_count_enum(self, populated_engine):
        with pytest.raises(IntegrityError):
            _exec(populated_engine, "UPDATE Sim SET sim_count = 'septuple' WHERE id = 1")


# ---------------------------------------------------------------------------
# NOT NULL
# ---------------------------------------------------------------------------


class TestNotNullConstraints:
    def test_device_name_brand_required(self, populated_engine):
        with pytest.raises((IntegrityError, OperationalError)):
            _exec(populated_engine, "UPDATE Device_Name SET brand = NULL WHERE id = 1")

    def test_device_name_model_required(self, populated_engine):
        with pytest.raises((IntegrityError, OperationalError)):
            _exec(populated_engine, "UPDATE Device_Name SET model = NULL WHERE id = 1")

    def test_device_year_required(self, populated_engine):
        with pytest.raises((IntegrityError, OperationalError)):
            _exec(populated_engine, "UPDATE Device SET year = NULL WHERE id = 1")

    def test_device_device_key_required(self, populated_engine):
        with pytest.raises((IntegrityError, OperationalError)):
            _exec(populated_engine, "UPDATE Device SET device_key = NULL WHERE id = 1")

    def test_platform_chipset_required(self, populated_engine):
        with pytest.raises((IntegrityError, OperationalError)):
            _exec(
                populated_engine,
                "UPDATE Platform SET chipset_manufacturer = NULL WHERE id = 1",
            )

    def test_platform_ram_required(self, populated_engine):
        with pytest.raises((IntegrityError, OperationalError)):
            _exec(populated_engine, "UPDATE Platform SET ram_gb = NULL WHERE id = 1")


# ---------------------------------------------------------------------------
# Foreign keys
# ---------------------------------------------------------------------------


class TestForeignKeys:
    def test_insert_device_with_unknown_brand_id_rejected(self, populated_engine):
        with pytest.raises(IntegrityError):
            _exec(
                populated_engine,
                """INSERT INTO Device (
                    device_key, device_name_id, network_technology_id, year,
                    launch_status, battery_capacity_mah, camera_id, display_id,
                    weight, length, width, height, volume, os_id, platform_id,
                    sim_id, price_eur
                ) VALUES (
                    'fk_violation_test',
                    99999,  -- nonexistent device_name_id
                    1, 2024, 'Available', 4000, 1, 1,
                    180.0, 150.0, 70.0, 8.0, 84000.0, 1, 1, 1, 599.0
                )""",
            )

    def test_delete_referenced_brand_rejected_by_restrict(self, populated_engine):
        # Device_Name id=1 is referenced by Device.device_name_id; ON DELETE
        # RESTRICT must reject the DELETE.
        with pytest.raises(IntegrityError):
            _exec(populated_engine, "DELETE FROM Device_Name WHERE id = 1")

    def test_update_to_unknown_fk_rejected(self, populated_engine):
        with pytest.raises(IntegrityError):
            _exec(
                populated_engine,
                "UPDATE Device SET device_name_id = 99999 WHERE id = 1",
            )
