"""Audit Data_cleaning.py cleaner coverage column-by-column.

For each (raw_col -> cleaned_col) pair, prints the unique raw values whose
cleaning produced NaN or a sentinel value (e.g. 'unknown'). These are the
fall-throughs — patterns the cleaner did not recognize.

Run:  python audit_cleaning.py
Or import and call individual helpers from a notebook:

    from audit_cleaning import build_audit_df, fallthrough, distribution
    df_before, df_after = build_audit_df()
    _safe(fallthrough, df_before, df_after, 'Body_SIM', 'SIM_count')

Cleaners are called one by one on a fresh DataPreProcess so row order/count
is preserved (the post-`expand_memory_configurations` and post-year-filter
DataFrames don't align with the raw input by index).
"""

import os
import sys
from pathlib import Path

# Ensure repo root is on sys.path so the absolute import below resolves
# whether this is run directly or imported as `etl.audit_cleaning`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from etl.Data_cleaning import DataPreProcess

DATA_DIR = Path(__file__).resolve().parent / "data"


SENTINELS = {'', 'nan', 'unknown', 'none'}


def is_sentinel(series: pd.Series) -> pd.Series:
    if series.dtype.kind in 'iuf':
        return series.isna()
    cleaned = series.astype(str).str.strip().str.lower()
    return series.isna() | cleaned.isin(SENTINELS)


def fallthrough(df_before, df_after, raw_cols, cleaned_col, top=20):
    """Show raw values whose cleaned output is missing/sentinel."""
    if isinstance(raw_cols, str):
        raw_cols = [raw_cols]
    raw_repr = df_before[raw_cols].fillna('').astype(str).agg(' | '.join, axis=1)
    cleaned = df_after[cleaned_col]
    raw_present = df_before[raw_cols].notna().any(axis=1)
    bad = is_sentinel(cleaned) & raw_present
    label = raw_cols[0] if len(raw_cols) == 1 else f"{len(raw_cols)} cols"
    print(f"\n== {label} -> {cleaned_col} ==")
    print(f"  rows: {len(df_before)}  raw-present: {int(raw_present.sum())}  fall-through: {int(bad.sum())}")
    if bad.any():
        print(f"  top {top} raw values that fell through:")
        for raw_val, count in raw_repr[bad].value_counts().head(top).items():
            print(f"    [{count:>4}]  {raw_val}")
    else:
        print("  (no fall-through)")


def distribution(df, col, top=20):
    print(f"\n== {col} value counts ==")
    print(df[col].value_counts(dropna=False).head(top).to_string())


def build_audit_df(input_csv=str(DATA_DIR / 'flattened_data.csv')):
    """Run every cleaner that preserves row count, return (raw, cleaned, failures) triple.

    Each cleaner is wrapped so one broken cleaner doesn't poison the audit.
    `failures` maps cleaner name -> exception message.
    """
    proc = DataPreProcess(input_csv)
    df_before = proc.df.copy()

    cleaners = [
        proc.process_main_camera_columns,
        proc.process_selfie_camera_columns,
        proc.process_camera_resolutions,
        proc.weight_process,
        proc.demintions_process,
        proc.network_tech_process,
        proc.battery_capacity_process,
        proc.sensors_process,
        proc.SIM_process,
        proc.extract_display_characteristics,
        proc.extract_resolution_details,
        proc.extract_base_os,
        proc.extract_os_version,
        proc.extract_chipset_manufacturer,
        proc.extract_cpu_core_count,
    ]

    failures = {}
    for fn in cleaners:
        try:
            fn()
        except Exception as exc:
            failures[fn.__name__] = f"{type(exc).__name__}: {exc}"

    return df_before, proc.df, failures


MAIN_CAM_SOURCES = [
    'Main Camera_Single', 'Main Camera_Dual', 'Main Camera_Triple',
    'Main Camera_Quad', 'Main Camera_Dual or Triple',
    'Main Camera_Penta', 'Main Camera_Five',
]
SELFIE_CAM_SOURCES = ['Selfie camera_Single', 'Selfie camera_Dual', 'Selfie camera_Triple']


def _safe(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except Exception as exc:
        target = args[-1] if args else '?'
        print(f"  (skipped {target} — {type(exc).__name__}: {exc})")


def audit_all():
    df_before, df_after, failures = build_audit_df()

    if failures:
        print("\n!! cleaner failures (these columns will be missing from df_after):")
        for name, msg in failures.items():
            print(f"  - {name}: {msg}")

    _safe(fallthrough, df_before, df_after, MAIN_CAM_SOURCES, 'Number of main cameras')
    _safe(fallthrough, df_before, df_after, SELFIE_CAM_SOURCES, 'Number of selfie cameras')
    _safe(fallthrough, df_before, df_after, MAIN_CAM_SOURCES, 'Highest_maincam_res')
    _safe(fallthrough, df_before, df_after, SELFIE_CAM_SOURCES, 'Highest_selfiecam_res')

    _safe(fallthrough, df_before, df_after, 'Body_Dimensions', 'length')
    _safe(fallthrough, df_before, df_after, 'Body_Dimensions', 'width')
    _safe(fallthrough, df_before, df_after, 'Body_Dimensions', 'height')
    _safe(fallthrough, df_before, df_after, 'Body_Dimensions', 'volume')

    _safe(fallthrough, df_before, df_after, 'Body_Weight', 'weight')

    _safe(fallthrough, df_before, df_after, 'Battery_Type', 'Battery_capacity')

    _safe(fallthrough, df_before, df_after, 'Body_SIM', 'SIM_type')
    _safe(fallthrough, df_before, df_after, 'Body_SIM', 'SIM_count')

    _safe(distribution, df_after, '2G')
    _safe(distribution, df_after, '3G')
    _safe(distribution, df_after, '4G')
    _safe(distribution, df_after, '5G')

    _safe(fallthrough, df_before, df_after, 'Display_Size', 'Display_Size_Inch')
    _safe(fallthrough, df_before, df_after, 'Display_Size', 'Display_Size_Cm')
    _safe(fallthrough, df_before, df_after, 'Display_Size', 'Screen_To_Body_Ratio')

    _safe(fallthrough, df_before, df_after, 'Display_Resolution', 'Resolution_Pixels')
    _safe(fallthrough, df_before, df_after, 'Display_Resolution', 'Resolution_Ratio')
    _safe(fallthrough, df_before, df_after, 'Display_Resolution', 'PPI_Density')

    _safe(fallthrough, df_before, df_after, 'Platform_OS', 'base_os')
    _safe(fallthrough, df_before, df_after, 'Platform_OS', 'OS_Version')
    _safe(fallthrough, df_before, df_after, 'Platform_Chipset', 'Chipset_Manufacturer')
    _safe(fallthrough, df_before, df_after, 'Platform_CPU', 'CPU_Core_Count')

    _safe(fallthrough, df_before, df_after, 'Features_Sensors', 'Sensors')


if __name__ == '__main__':
    audit_all()
