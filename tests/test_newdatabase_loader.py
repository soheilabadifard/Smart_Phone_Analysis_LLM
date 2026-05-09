"""Loader integration tests — the FK-resolution machinery in newDatabase.py.

These were the biggest untested gap. The cleaner regex tests prove
processed_data.csv columns are right; these prove that turning that DataFrame
into FK-respecting Device rows actually works.

Coverage targets:
  * `attach_lookup_id` — natural-key join produces correct FK ids
  * `build_lookup_signature` — sha256 dedupe key is stable + collision-free
  * `normalize_lookup_frame` — case/whitespace/numeric normalization
  * `append_new_rows` — idempotent insert (skips existing keys)
  * `build_device_records` — full FK resolution against a populated DB
  * `addDevice` — drops rows with unresolved required FKs
  * `addAll` — orchestrated end-to-end load from a synthetic CSV
"""

from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import text

from etl.newDatabase import (
    AddToTable,
    attach_lookup_id,
    build_lookup_signature,
    derive_form_factor,
    normalize_lookup_frame,
)


# ---------------------------------------------------------------------------
# Pure-function level
# ---------------------------------------------------------------------------


class TestNormalizeLookupFrame:
    def test_normalises_strings(self):
        df = pd.DataFrame({"brand": ["Apple", "  apple ", "APPLE"]})
        out = normalize_lookup_frame(df, ["brand"])
        assert out["brand"].tolist() == ["apple", "apple", "apple"]

    def test_normalises_numerics(self):
        df = pd.DataFrame({"ram_gb": [8.0, 8, "8"]})
        out = normalize_lookup_frame(df, ["ram_gb"])
        assert out["ram_gb"].tolist() == ["8", "8", "8"]


class TestAttachLookupId:
    def test_left_join_attaches_id(self):
        data = pd.DataFrame({"brand": ["Apple", "Samsung"], "model": ["iPhone 15", "Galaxy S24"]})
        mapping = pd.DataFrame({
            "device_name_id": [10, 20],
            "brand": ["Apple", "Samsung"],
            "model": ["iPhone 15", "Galaxy S24"],
        })
        out = attach_lookup_id(data, mapping, ["brand", "model"], "device_name_id")
        assert out["device_name_id"].tolist() == [10, 20]

    def test_unmatched_row_yields_nan_id(self):
        data = pd.DataFrame({"brand": ["Apple", "Unknown"], "model": ["iPhone 15", "Mystery"]})
        mapping = pd.DataFrame({
            "device_name_id": [10],
            "brand": ["Apple"],
            "model": ["iPhone 15"],
        })
        out = attach_lookup_id(data, mapping, ["brand", "model"], "device_name_id")
        assert out["device_name_id"].iloc[0] == 10
        assert pd.isna(out["device_name_id"].iloc[1])

    def test_normalisation_handles_case_diff(self):
        # The data has APPLE; the mapping has apple. Normalisation should match.
        data = pd.DataFrame({"brand": ["APPLE"], "model": ["iPhone 15"]})
        mapping = pd.DataFrame({
            "device_name_id": [10],
            "brand": ["apple"],
            "model": ["iphone 15"],
        })
        out = attach_lookup_id(data, mapping, ["brand", "model"], "device_name_id")
        assert out["device_name_id"].iloc[0] == 10


class TestDeriveFormFactor:
    @pytest.mark.parametrize(
        "model,expected",
        [
            ("iPhone 15", "phone"),
            ("Galaxy S24 Ultra", "phone"),
            ("Apple Watch Edition 42mm (1st gen)", "watch"),
            ("Galaxy Watch Active 2", "watch"),
            ("Samsung Gear S3", "watch"),
            ("iPad Pro 12.9 (2024)", "tablet"),
            ("Galaxy Tab S9", "tablet"),
            ("Huawei MatePad Pro", "tablet"),
            ("Mi Band 7", "band"),
            ("Smart Band X", "band"),
            ("Fitbit Charge 5", "watch"),  # 'fitbit' is in WATCH_TOKENS by design
        ],
    )
    def test_known_models(self, model, expected):
        assert derive_form_factor(model) == expected

    def test_nan_returns_other(self):
        import pandas as pd
        assert derive_form_factor(pd.NA) == "other"


class TestBuildLookupSignature:
    def test_collision_free_for_distinct_rows(self):
        df = pd.DataFrame({
            "a": ["apple", "apple", "samsung"],
            "b": ["iphone 15", "iphone 14", "galaxy s24"],
        })
        sigs = build_lookup_signature(df, ["a", "b"])
        assert len(set(sigs)) == 3

    def test_stable_under_normalisation(self):
        df = pd.DataFrame({
            "a": ["Apple", "apple", "APPLE"],
            "b": ["iPhone 15", "  iphone 15", "IPHONE 15"],
        })
        sigs = build_lookup_signature(df, ["a", "b"])
        assert len(set(sigs)) == 1


# ---------------------------------------------------------------------------
# Loader against the in-memory DB
# ---------------------------------------------------------------------------


def _make_loader(engine):
    """Construct an AddToTable that uses the test engine, no .env required."""
    loader = AddToTable.__new__(AddToTable)
    loader.engine = engine
    loader.connection = engine
    loader._source_dataframe = None
    return loader


@pytest.fixture
def synthetic_processed_df():
    """Minimal dataframe that mirrors processed_data.csv post-cleaning.

    Five rows: three valid devices across 2 brands + 1 row with NaN platform
    (should be dropped by addDevice) + 1 dup of the first row (should be
    deduped by build_device_records).

    Note: when load_source_dataframe is bypassed (set ``_source_dataframe``
    directly), the form_factor column must be present here — derivation only
    runs as part of load_source_dataframe.
    """
    df = pd.DataFrame([
        # row 0: complete Apple iPhone 15 record
        {
            "brand": "Apple", "model": "iPhone 15",
            "network_technology": "GSM / HSPA / LTE / 5G",
            "sim_count": "single", "sim_type": "esim", "body_sim": "Nano-SIM",
            "main_cameras_num": 3, "selfie_cameras_num": 1,
            "highest_maincam_res": 48.0, "highest_selfiecam_res": 12.0,
            "display_size_inch": 6.1, "display_size_cm": 15.5,
            "screen_to_body_ratio": 86.4, "resolution_pixels": 3013524,
            "resolution_ratio": "19.5:9", "ppi_density": 460.0,
            "os_name": "iOS", "os_version": "17",
            "chipset_manufacturer": "Apple", "cpu_core_count": 6,
            "internal_storage_gb": 128, "ram_gb": 6,
            "year": 2023, "launch_status": "Available",
            "battery_capacity_mah": 3349,
            "weight": 171.0, "length": 147.6, "width": 71.6, "height": 7.8,
            "volume": 82400.0, "price_eur": 799.0,
            "sensor_payload": "['Face ID', 'gyro']",
        },
        # row 1: Samsung Galaxy
        {
            "brand": "Samsung", "model": "Galaxy S24",
            "network_technology": "GSM / HSPA / LTE / 5G",
            "sim_count": "dual", "sim_type": "nano", "body_sim": "Dual SIM",
            "main_cameras_num": 2, "selfie_cameras_num": 1,
            "highest_maincam_res": 50.0, "highest_selfiecam_res": 16.0,
            "display_size_inch": 6.7, "display_size_cm": 17.0,
            "screen_to_body_ratio": 89.0, "resolution_pixels": 4492800,
            "resolution_ratio": "19.5:9", "ppi_density": 510.0,
            "os_name": "Android", "os_version": "14",
            "chipset_manufacturer": "Qualcomm", "cpu_core_count": 8,
            "internal_storage_gb": 256, "ram_gb": 12,
            "year": 2024, "launch_status": "Available",
            "battery_capacity_mah": 4000,
            "weight": 196.0, "length": 162.3, "width": 79.0, "height": 8.6,
            "volume": 110200.0, "price_eur": 899.0,
            "sensor_payload": "['Fingerprint', 'gyro']",
        },
        # row 2: another Apple, different model
        {
            "brand": "Apple", "model": "iPhone 15 Pro",
            "network_technology": "GSM / HSPA / LTE / 5G",
            "sim_count": "single", "sim_type": "esim", "body_sim": "Nano-SIM",
            "main_cameras_num": 3, "selfie_cameras_num": 1,
            "highest_maincam_res": 48.0, "highest_selfiecam_res": 12.0,
            "display_size_inch": 6.1, "display_size_cm": 15.5,
            "screen_to_body_ratio": 86.4, "resolution_pixels": 3013524,
            "resolution_ratio": "19.5:9", "ppi_density": 460.0,
            "os_name": "iOS", "os_version": "17",
            "chipset_manufacturer": "Apple", "cpu_core_count": 6,
            "internal_storage_gb": 256, "ram_gb": 8,
            "year": 2023, "launch_status": "Available",
            "battery_capacity_mah": 3274,
            "weight": 187.0, "length": 146.6, "width": 70.6, "height": 8.25,
            "volume": 85400.0, "price_eur": 1199.0,
            "sensor_payload": "['Face ID']",
        },
        # row 3: NaN platform fields — survives with NULL platform_id under
        # the nullable-FK schema (2026-05-09).
        {
            "brand": "Mystery", "model": "Phone X",
            "network_technology": "GSM / HSPA / LTE",
            "sim_count": "single", "sim_type": "nano", "body_sim": "SIM",
            "main_cameras_num": 1, "selfie_cameras_num": 1,
            "highest_maincam_res": 8.0, "highest_selfiecam_res": 5.0,
            "display_size_inch": 5.0, "display_size_cm": 12.7,
            "screen_to_body_ratio": 70.0, "resolution_pixels": 1280 * 720,
            "resolution_ratio": "16:9", "ppi_density": 320.0,
            # platform fields all NaN → device_id keeps platform_id = NULL
            "os_name": "Android", "os_version": "13",
            "chipset_manufacturer": pd.NA, "cpu_core_count": pd.NA,
            "internal_storage_gb": pd.NA, "ram_gb": pd.NA,
            "year": 2020, "launch_status": "Discontinued",
            "battery_capacity_mah": 2000,
            "weight": 150.0, "length": 140.0, "width": 70.0, "height": 8.0,
            "volume": 78400.0, "price_eur": 100.0,
            "sensor_payload": "[]",
        },
        # row 4: exact dup of row 0 (different sensor_payload to test dedupe-ignores-it)
        {
            "brand": "Apple", "model": "iPhone 15",
            "network_technology": "GSM / HSPA / LTE / 5G",
            "sim_count": "single", "sim_type": "esim", "body_sim": "Nano-SIM",
            "main_cameras_num": 3, "selfie_cameras_num": 1,
            "highest_maincam_res": 48.0, "highest_selfiecam_res": 12.0,
            "display_size_inch": 6.1, "display_size_cm": 15.5,
            "screen_to_body_ratio": 86.4, "resolution_pixels": 3013524,
            "resolution_ratio": "19.5:9", "ppi_density": 460.0,
            "os_name": "iOS", "os_version": "17",
            "chipset_manufacturer": "Apple", "cpu_core_count": 6,
            "internal_storage_gb": 128, "ram_gb": 6,
            "year": 2023, "launch_status": "Available",
            "battery_capacity_mah": 3349,
            "weight": 171.0, "length": 147.6, "width": 71.6, "height": 7.8,
            "volume": 82400.0, "price_eur": 799.0,
            "sensor_payload": "['DIFFERENT', 'SENSORS']",
        },
    ])
    # All synthetic rows are phones; load_source_dataframe is bypassed by these
    # tests, so we add form_factor manually.
    df["form_factor"] = df["model"].map(derive_form_factor)
    return df


class TestAppendNewRows:
    def test_inserts_into_empty_table(self, sqlite_engine):
        loader = _make_loader(sqlite_engine)
        df = pd.DataFrame({"brand": ["Apple", "Samsung"], "model": ["iPhone 15", "Galaxy S24"]})
        loader.append_new_rows("Device_Name", df, ["brand", "model"])
        with sqlite_engine.connect() as conn:
            rows = conn.execute(text("SELECT brand, model FROM Device_Name ORDER BY brand")).all()
        assert rows == [("Apple", "iPhone 15"), ("Samsung", "Galaxy S24")]

    def test_idempotent_skips_existing(self, sqlite_engine):
        loader = _make_loader(sqlite_engine)
        df = pd.DataFrame({"brand": ["Apple"], "model": ["iPhone 15"]})
        loader.append_new_rows("Device_Name", df, ["brand", "model"])
        loader.append_new_rows("Device_Name", df, ["brand", "model"])  # same row again
        with sqlite_engine.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM Device_Name")).scalar()
        assert count == 1

    def test_dedupes_within_batch(self, sqlite_engine):
        loader = _make_loader(sqlite_engine)
        df = pd.DataFrame({
            "brand": ["Apple", "Apple", "Apple"],
            "model": ["iPhone 15", "iphone 15", "IPHONE 15"],  # case variants
        })
        loader.append_new_rows("Device_Name", df, ["brand", "model"])
        with sqlite_engine.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM Device_Name")).scalar()
        assert count == 1

    def test_skips_all_nan_keys(self, sqlite_engine):
        loader = _make_loader(sqlite_engine)
        df = pd.DataFrame({"brand": [pd.NA, pd.NA], "model": [pd.NA, pd.NA]})
        loader.append_new_rows("Device_Name", df, ["brand", "model"])
        with sqlite_engine.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM Device_Name")).scalar()
        assert count == 0


class TestEndToEndAddAll:
    """Drive the full loader against the synthetic dataframe and assert the
    populated DB looks right. Exercises addDeviceName → addNetworkTechnology →
    addSim → addCamera → addDisplay → addOs → addPlatform → addDevice in
    sequence, with FK resolution via attach_lookup_id."""

    def test_addAll_populates_all_tables(self, sqlite_engine, synthetic_processed_df):
        loader = _make_loader(sqlite_engine)
        loader._source_dataframe = synthetic_processed_df

        with sqlite_engine.begin() as conn:
            loader.connection = conn
            try:
                loader.addDeviceName()
                loader.addNetworkTechnology()
                loader.addSim()
                loader.addcamera()
                loader.addDisplay()
                loader.addOs()
                loader.addPlatform()
                loader.addDevice()
            finally:
                loader.connection = sqlite_engine

        with sqlite_engine.connect() as conn:
            counts = {
                t: conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
                for t in (
                    "Device_Name", "Network_Technology", "Sim", "Camera",
                    "Display", "OS", "Platform", "Device",
                )
            }

        # 4 distinct (brand, model): Apple/iPhone 15, Samsung/Galaxy S24,
        # Apple/iPhone 15 Pro, Mystery/Phone X
        assert counts["Device_Name"] == 4
        # Network Technology has 2 distinct strings
        assert counts["Network_Technology"] == 2
        # Sim: (single,esim) + (dual,nano) + (single,nano) = 3
        assert counts["Sim"] == 3
        # Devices: 5 raw rows → row 4 deduped by device_key → row 3 kept
        # with NULL platform_id (nullable-FK schema) → 4 devices.
        assert counts["Device"] == 4

    def test_addDevice_keeps_rows_with_null_fks(self, sqlite_engine, synthetic_processed_df, capsys):
        loader = _make_loader(sqlite_engine)
        loader._source_dataframe = synthetic_processed_df

        with sqlite_engine.begin() as conn:
            loader.connection = conn
            loader.addDeviceName()
            loader.addNetworkTechnology()
            loader.addSim()
            loader.addcamera()
            loader.addDisplay()
            loader.addOs()
            loader.addPlatform()  # row 3's platform is NaN → not inserted
            loader.addDevice()    # row 3 → unresolved platform_id → kept with NULL
            loader.connection = sqlite_engine

        # The "Mystery" device IS inserted now, with platform_id = NULL.
        with sqlite_engine.connect() as conn:
            mystery_row = conn.execute(text("""
                SELECT d.platform_id
                FROM Device d
                JOIN Device_Name dn ON dn.id = d.device_name_id
                WHERE dn.brand = 'Mystery'
            """)).first()
        assert mystery_row is not None, "Mystery device should now be loaded"
        assert mystery_row.platform_id is None, "platform_id should be NULL"

        # The diagnostic should have logged the per-column NaN count
        captured = capsys.readouterr()
        assert "platform_id" in captured.out and "NULL dim FK" in captured.out

    def test_addAll_idempotent_under_replay(self, sqlite_engine, synthetic_processed_df):
        """Running the full pipeline twice must produce the same row counts."""
        loader = _make_loader(sqlite_engine)
        loader._source_dataframe = synthetic_processed_df

        for _ in range(2):
            with sqlite_engine.begin() as conn:
                loader.connection = conn
                loader.addDeviceName()
                loader.addNetworkTechnology()
                loader.addSim()
                loader.addcamera()
                loader.addDisplay()
                loader.addOs()
                loader.addPlatform()
                loader.addDevice()
                loader.connection = sqlite_engine

        with sqlite_engine.connect() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM Device_Name")).scalar() == 4
            assert conn.execute(text("SELECT COUNT(*) FROM Device")).scalar() == 4


class TestDeviceKeyDedupe:
    """Verify the device_key SHA-256 hash dedupes rows that are identical
    across all 16 device-level columns (the Device UNIQUE constraint)."""

    def test_identical_rows_collapse_to_one_device(self, sqlite_engine, synthetic_processed_df):
        loader = _make_loader(sqlite_engine)
        loader._source_dataframe = synthetic_processed_df

        with sqlite_engine.begin() as conn:
            loader.connection = conn
            loader.addDeviceName()
            loader.addNetworkTechnology()
            loader.addSim()
            loader.addcamera()
            loader.addDisplay()
            loader.addOs()
            loader.addPlatform()
            loader.addDevice()
            loader.connection = sqlite_engine

        # Rows 0 and 4 differ only in sensor_payload (which isn't part of the
        # Device fact). They must produce one Device row, not two.
        with sqlite_engine.connect() as conn:
            iphone15_count = conn.execute(text("""
                SELECT COUNT(*) FROM Device d
                JOIN Device_Name dn ON dn.id = d.device_name_id
                WHERE dn.brand = 'Apple' AND dn.model = 'iPhone 15'
            """)).scalar()
        assert iphone15_count == 1
