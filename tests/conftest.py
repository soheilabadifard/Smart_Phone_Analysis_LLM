"""Shared pytest fixtures.

Three layers of fixtures:
  * `sample_*` — small in-memory DataFrames for cleaner / loader tests
  * `sqlite_engine` — in-memory SQLite engine with the project schema
  * `populated_engine` — sqlite_engine with a handful of seeded devices
  * `client` — FastAPI TestClient pointed at populated_engine, with
    `app.llm.client.chat` monkeypatched so tests never hit the LLM
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Engine

# Make the repo root + backend importable from tests
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

# Required env vars for newDatabase / app.db imports — fake values are fine
# because tests override the engine factories.
os.environ.setdefault("DB_NAME", "gsm_test")
os.environ.setdefault("DB_USER", "test_user")
os.environ.setdefault("DB_PASSWORD", "test_pass")
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "3306")
os.environ.setdefault("DB_RO_USER", "test_ro_user")
os.environ.setdefault("DB_RO_PASSWORD", "test_ro_pass")


@event.listens_for(Engine, "connect")
def _enable_sqlite_fk(dbapi_connection, connection_record):
    """Force SQLite to enforce FKs (off by default)."""
    if dbapi_connection.__class__.__module__.startswith("sqlite3"):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


# ---------------------------------------------------------------------------
# Schema fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sqlite_engine():
    """In-memory SQLite engine with the project's ORM schema applied.

    Uses StaticPool + check_same_thread=False so a single connection is shared
    across FastAPI's threadpool. Without this, every worker thread gets a new
    `:memory:` (i.e. empty) database and the route tests see "no such table".
    """
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    from etl.newDatabase import Base

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def populated_engine(sqlite_engine, monkeypatch):
    """sqlite_engine with a small seeded dataset (5 devices, 3 brands).

    Also rewires every module that did ``from app.db import ro_engine`` at
    import time so they pick up the test SQLite engine instead of opening a
    real MariaDB connection. Without these patches the route handlers raise
    "Can't connect to MySQL server" because they hold their own bound
    reference to the original ``ro_engine`` callable.
    """
    seed_rows = {
        "Device_Name": [
            {"id": 1, "brand": "Apple", "model": "iPhone 15"},
            {"id": 2, "brand": "Samsung", "model": "Galaxy S24"},
            {"id": 3, "brand": "Xiaomi", "model": "Redmi Note 13"},
        ],
        "Network_Technology": [
            {"id": 1, "technology": "GSM / HSPA / LTE / 5G"},
            {"id": 2, "technology": "GSM / HSPA / LTE"},
        ],
        "Sim": [
            {"id": 1, "sim_count": "dual", "sim_type": "nano"},
            {"id": 2, "sim_count": "single", "sim_type": "esim"},
        ],
        "Camera": [
            {"id": 1, "main_cameras_num": 3, "selfie_cameras_num": 1,
             "highest_maincam_res": 48.0, "highest_selfiecam_res": 12.0},
            {"id": 2, "main_cameras_num": 2, "selfie_cameras_num": 1,
             "highest_maincam_res": 50.0, "highest_selfiecam_res": 16.0},
        ],
        "Display": [
            {"id": 1, "display_size_inch": 6.1, "display_size_cm": 15.5,
             "screen_to_body_ratio": 86.4, "resolution_pixels": 2556 * 1179,
             "resolution_ratio": "19.5:9", "ppi_density": 460.0},
            {"id": 2, "display_size_inch": 6.7, "display_size_cm": 17.0,
             "screen_to_body_ratio": 89.0, "resolution_pixels": 3120 * 1440,
             "resolution_ratio": "19.5:9", "ppi_density": 510.0},
        ],
        "OS": [
            {"id": 1, "os_name": "iOS", "os_version": "17"},
            {"id": 2, "os_name": "Android", "os_version": "14"},
        ],
        "Platform": [
            {"id": 1, "chipset_manufacturer": "Apple", "cpu_core_count": 6,
             "internal_storage_gb": 128, "ram_gb": 6},
            {"id": 2, "chipset_manufacturer": "Qualcomm", "cpu_core_count": 8,
             "internal_storage_gb": 256, "ram_gb": 12},
            {"id": 3, "chipset_manufacturer": "Mediatek", "cpu_core_count": 8,
             "internal_storage_gb": 128, "ram_gb": 8},
        ],
        "Device": [
            {"id": 1, "device_key": "k1", "device_name_id": 1,
             "network_technology_id": 1, "year": 2023, "launch_status": "Available",
             "battery_capacity_mah": 3349, "camera_id": 1, "display_id": 1,
             "weight": 171.0, "length": 147.6, "width": 71.6, "height": 7.8,
             "volume": 82400.0, "os_id": 1, "platform_id": 1, "price_eur": 799.0,
             "sim_id": 2, "form_factor": "phone"},
            {"id": 2, "device_key": "k2", "device_name_id": 2,
             "network_technology_id": 1, "year": 2024, "launch_status": "Available",
             "battery_capacity_mah": 4000, "camera_id": 2, "display_id": 2,
             "weight": 196.0, "length": 162.3, "width": 79.0, "height": 8.6,
             "volume": 110200.0, "os_id": 2, "platform_id": 2, "price_eur": 899.0,
             "sim_id": 1, "form_factor": "phone"},
            {"id": 3, "device_key": "k3", "device_name_id": 3,
             "network_technology_id": 1, "year": 2024, "launch_status": "Available",
             "battery_capacity_mah": 5000, "camera_id": 2, "display_id": 1,
             "weight": 188.0, "length": 161.0, "width": 75.0, "height": 8.0,
             "volume": 96600.0, "os_id": 2, "platform_id": 3, "price_eur": 249.0,
             "sim_id": 1, "form_factor": "phone"},
            {"id": 4, "device_key": "k4", "device_name_id": 2,
             "network_technology_id": 2, "year": 2022, "launch_status": "Discontinued",
             "battery_capacity_mah": 3700, "camera_id": 1, "display_id": 1,
             "weight": 168.0, "length": 146.0, "width": 70.6, "height": 7.6,
             "volume": 78300.0, "os_id": 2, "platform_id": 2, "price_eur": None,
             "sim_id": 1, "form_factor": "phone"},
            {"id": 5, "device_key": "k5", "device_name_id": 1,
             "network_technology_id": 1, "year": 2024, "launch_status": "Available",
             "battery_capacity_mah": 3274, "camera_id": 1, "display_id": 1,
             "weight": 174.0, "length": 147.6, "width": 71.6, "height": 7.8,
             "volume": 82400.0, "os_id": 1, "platform_id": 1, "price_eur": 949.0,
             "sim_id": 2, "form_factor": "phone"},
            # id=6: a watch — used to verify form_factor filter excludes non-phones.
            {"id": 6, "device_key": "k6_watch", "device_name_id": 1,
             "network_technology_id": 1, "year": 2024, "launch_status": "Available",
             "battery_capacity_mah": 300, "camera_id": 1, "display_id": 1,
             "weight": 38.0, "length": 44.0, "width": 38.0, "height": 10.7,
             "volume": 17880.0, "os_id": 1, "platform_id": 1, "price_eur": 449.0,
             "sim_id": 2, "form_factor": "watch"},
        ],
    }

    with sqlite_engine.begin() as conn:
        for table_name, rows in seed_rows.items():
            for row in rows:
                cols = ", ".join(row.keys())
                placeholders = ", ".join(f":{k}" for k in row)
                conn.execute(text(f"INSERT INTO {table_name} ({cols}) VALUES ({placeholders})"), row)

    # Rewire every module that imported ro_engine / rw_engine by name.
    import importlib
    fake_engine = lambda: sqlite_engine  # noqa: E731

    import app.db
    monkeypatch.setattr(app.db, "ro_engine", fake_engine)
    monkeypatch.setattr(app.db, "rw_engine", fake_engine)
    for mod_path in ("app.llm.pipeline", "app.routes.recommend", "app.routes.analytics"):
        mod = importlib.import_module(mod_path)
        if hasattr(mod, "ro_engine"):
            monkeypatch.setattr(mod, "ro_engine", fake_engine)
        if hasattr(mod, "rw_engine"):
            monkeypatch.setattr(mod, "rw_engine", fake_engine)

    return sqlite_engine


# ---------------------------------------------------------------------------
# FastAPI client
# ---------------------------------------------------------------------------


@pytest.fixture
def client(populated_engine, monkeypatch):
    """FastAPI TestClient with DB pointed at SQLite and LLM stubbed."""
    from fastapi.testclient import TestClient

    # Patch the engine factories before importing the app
    import app.db as db_module
    monkeypatch.setattr(db_module, "ro_engine", lambda: populated_engine)
    monkeypatch.setattr(db_module, "rw_engine", lambda: populated_engine)

    # Default LLM stub — individual tests can override
    import app.llm.client as llm_client
    monkeypatch.setattr(
        llm_client,
        "chat",
        lambda messages: "```sql\nSELECT 1 AS ok;\n```",
    )

    from app.main import app

    return TestClient(app)


# ---------------------------------------------------------------------------
# Cleaner test data
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_flattened_df() -> pd.DataFrame:
    """Tiny DataFrame mirroring the columns flattened_data.csv exposes.

    Used by Data_cleaning tests — exercises one row per code path without
    requiring the full GSMArena-scraped CSV.
    """
    return pd.DataFrame({
        "Body_Dimensions": [
            "147.6 x 71.6 x 7.8 mm (5.81 x 2.82 x 0.31 in)",
            "162.3 x 79.0 x 8.6 mm",
            "Foldable",
            None,
        ],
        "Body_Weight": ["171 g (6.03 oz)", "196 g", None, "0.5 kg"],
        "Body_SIM": [
            "Nano-SIM and eSIM or Dual eSIM",
            "Single SIM (Nano-SIM)",
            "Dual SIM (Nano-SIM, dual stand-by)",
            "No",
        ],
        "Network_2G bands": ["GSM 850 / 900", "GSM 850 / 900", None, None],
        "Network_3G bands": ["HSDPA 850 / 900", "HSDPA 850", None, None],
        "Network_4G bands": ["LTE 1, 2, 3", "LTE 1, 2, 3", "LTE 1", None],
        "Network_5G bands": ["1, 3, 5 SA/NSA", None, "n1, n3, n78", None],
        "Battery_Type": [
            "Li-Ion 3349 mAh, non-removable",
            "Li-Po 4000 mAh, non-removable",
            None,
            "Li-Po 5000 mAh, fast charging 33W",
        ],
        "Features_Sensors": [
            "Face ID, accelerometer, gyro, proximity, compass, barometer",
            "Fingerprint (under display, ultrasonic), accelerometer, gyro",
            None,
            "Fingerprint (side-mounted), accelerometer, proximity, compass",
        ],
        "Display_Size": [
            "6.1 inches, 90.2 cm2 (~86.4% screen-to-body ratio)",
            "6.7 inches, 110.0 cm2 (~89.0%)",
            None,
            "6.67 inches, 107.4 cm2 (~85.0% screen-to-body ratio)",
        ],
        "Display_Resolution": [
            "1179 x 2556 pixels, 19.5:9 ratio (~460 ppi density)",
            "1440 x 3120 pixels (~510 ppi density)",
            None,
            "1080 x 2400 pixels, 20:9 ratio (~395 ppi density)",
        ],
        "Platform_OS": [
            "iOS 17, upgradable to iOS 17.4",
            "Android 14, One UI 6.1",
            "Android 13",
            "MIUI 14, Android 13",
        ],
        "Platform_Chipset": [
            "Apple A16 Bionic (4 nm)",
            "Qualcomm SM8650-AC Snapdragon 8 Gen 3",
            "Mediatek Dimensity 7050 (6 nm)",
            "Qualcomm Snapdragon 685 (6 nm)",
        ],
        "Platform_CPU": [
            "Hexa-core (2x3.46 GHz Everest + 4x2.02 GHz Sawtooth)",
            "Octa-core (1x3.39 GHz Cortex-X4 & 5x3.1 GHz Cortex-A720)",
            "Octa-core (2x2.6 GHz Cortex-A78 & 6x2.0 GHz Cortex-A55)",
            "Single-core",
        ],
        "Memory_Card slot": ["No", "No", "microSDXC", "microSDXC (dedicated slot)"],
        "Memory_Internal": [
            "128GB 6GB RAM, 256GB 6GB RAM, 512GB 6GB RAM",
            "256GB 12GB RAM, 512GB 12GB RAM, 1TB 12GB RAM",
            "128GB 6GB RAM, 256GB 8GB RAM",
            "128GB 6GB RAM (Africa), 64GB 4GB RAM (India)",
        ],
        "Main Camera_Single": [None, None, None, "13 MP, f/2.2"],
        "Main Camera_Dual": [None, "12 MP + 50 MP, OIS", None, None],
        "Main Camera_Triple": ["48 MP wide + 12 MP UW + 12 MP TELE", None, "108 MP + 8 MP + 2 MP", None],
        "Main Camera_Quad": [None, None, None, None],
        "Main Camera_Dual or Triple": [None, None, None, None],
        "Main Camera_Penta": [None, None, None, None],
        "Main Camera_Five": [None, None, None, None],
        "Main Camera_Video": ["4K@60fps, HDR", "8K@30fps, 4K@60fps", "1080p@30fps", "1080p@30fps"],
        "Main Camera_Features": ["Quad-LED dual-tone flash, HDR (photo/panorama)", "LED flash", "LED flash", "LED flash"],
        "Selfie camera_Single": ["12 MP, f/1.9", "12 MP, f/2.2", "16 MP, f/2.4", "5 MP, f/2.2"],
        "Selfie camera_Dual": [None, None, None, None],
        "Selfie camera_Triple": [None, None, None, None],
        "Selfie camera_Video": ["4K@60fps", "4K@30fps", "1080p@30fps", "1080p@30fps"],
        "Selfie camera_Features": [None, None, None, None],
        "Misc_Price": [
            "About 800 EUR",
            "$ 999.99 / £ 849.00",
            "About 250 EUR",
            "₹ 12,499",
        ],
        "Launch_Announced": ["2023, September 12", "2024, January 17", "2024, January", "2023, August"],
        "Launch_Status": ["Available. Released 2023, September 22", "Available. Released 2024", "Discontinued", "Coming soon. Exp. release 2024"],
    })
