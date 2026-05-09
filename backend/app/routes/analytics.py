"""Pre-built market analytics.

Three sections:
  1. R-style summary endpoints (mirror R1-R5 in Deliverables/queries.sql).
  2. Distribution / ranking / trend endpoints (mirror Q1-Q8 of the
     `Statistics - With Scraped data.ipynb` notebook).
  3. Inferential statistics: confidence intervals + hypothesis tests
     (mirrors the Estimation + HT1-HT6 sections of the same notebook).

Section 3 endpoints recompute on every call because data changes only when
the pipeline runs and the row counts are small enough that recomputation is
sub-millisecond. If that ever stops being true, add module-level caching.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm
from fastapi import APIRouter
from scipy import stats
from sqlalchemy import text
from statsmodels.formula.api import ols

from app.db import ro_engine

router = APIRouter()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

# Phone-only is the consistent default for these analyses; the dataset also
# contains watches/tablets/bands which would skew comparisons.
_PHONE = "d.form_factor = 'phone'"


def _rows(sql: str) -> list[dict]:
    with ro_engine().connect() as conn:
        return [dict(r) for r in conn.execute(text(sql)).mappings().all()]


def _df(sql: str) -> pd.DataFrame:
    with ro_engine().connect() as conn:
        return pd.read_sql(text(sql), conn)


def _classify_size(display_size_inch: pd.Series) -> pd.Series:
    """Notebook's size_classifier: ≥7 inch → 'large', else 'small'."""
    return np.where(display_size_inch >= 7, "large", "small")


def _t_or_mannwhitney(group_a: np.ndarray, group_b: np.ndarray) -> dict:
    """Pick t-test if both groups pass Shapiro-Wilk, else Mann-Whitney U.

    Mirrors the notebook's Hypothesis_testing flow. Two-sided alternative.
    Returns a dict with test name, statistic, p-value.
    """
    if len(group_a) < 3 or len(group_b) < 3:
        return {"test": "insufficient_data", "statistic": None, "p_value": None}

    # Shapiro-Wilk normality test on each group (sample size limit guard).
    sample_a = group_a if len(group_a) <= 5000 else np.random.default_rng(0).choice(group_a, 5000, replace=False)
    sample_b = group_b if len(group_b) <= 5000 else np.random.default_rng(0).choice(group_b, 5000, replace=False)
    _, p_norm_a = stats.shapiro(sample_a)
    _, p_norm_b = stats.shapiro(sample_b)
    both_normal = p_norm_a > 0.05 and p_norm_b > 0.05

    if both_normal:
        stat, pvalue = stats.ttest_ind(group_a, group_b, equal_var=False)
        return {"test": "Welch t-test", "statistic": float(stat), "p_value": float(pvalue),
                "shapiro_p_a": float(p_norm_a), "shapiro_p_b": float(p_norm_b)}
    stat, pvalue = stats.mannwhitneyu(group_a, group_b, alternative="two-sided")
    return {"test": "Mann-Whitney U", "statistic": float(stat), "p_value": float(pvalue),
            "shapiro_p_a": float(p_norm_a), "shapiro_p_b": float(p_norm_b)}


def _group_summary(values: np.ndarray) -> dict:
    return {
        "n": int(len(values)),
        "mean": float(np.mean(values)) if len(values) else None,
        "std": float(np.std(values, ddof=1)) if len(values) > 1 else None,
        "median": float(np.median(values)) if len(values) else None,
        "values": values.tolist(),
    }


def _conclusion(p_value: float | None, alpha: float = 0.05) -> str:
    if p_value is None:
        return "insufficient data"
    return f"reject H0 at α={alpha}" if p_value < alpha else f"fail to reject H0 at α={alpha}"


def _anova_table(model_formula: str, data: pd.DataFrame) -> list[dict]:
    """Run statsmodels OLS + anova_lm(typ=2) and return tidy rows.

    Returns [] when the design is degenerate (single factor level, too few
    observations, perfect collinearity). The HT response will then carry a
    None p_value and "insufficient data" conclusion.
    """
    try:
        model = ols(model_formula, data=data).fit()
        table = sm.stats.anova_lm(model, typ=2)
    except (ValueError, np.linalg.LinAlgError):
        return []
    out = []
    for factor, row in table.iterrows():
        out.append({
            "factor": str(factor),
            "sum_sq": float(row["sum_sq"]),
            "df": float(row["df"]),
            "F": float(row["F"]) if not pd.isna(row["F"]) else None,
            "p_value": float(row["PR(>F)"]) if not pd.isna(row["PR(>F)"]) else None,
        })
    return out


# ===========================================================================
# Section 1 — R-style summary endpoints
# ===========================================================================


@router.get("/brand-summary")
def brand_summary() -> list[dict]:
    """R1 — Brand catalogue summary: model count, avg price, year span."""
    return _rows(
        """
        SELECT
            dn.brand,
            COUNT(*) AS device_count,
            ROUND(AVG(d.price_eur), 2) AS avg_price_eur,
            MIN(d.year) AS first_year,
            MAX(d.year) AS last_year
        FROM Device d
        JOIN Device_Name dn ON dn.id = d.device_name_id
        WHERE d.price_eur IS NOT NULL
        GROUP BY dn.brand
        HAVING COUNT(*) >= 3
        ORDER BY device_count DESC
        """
    )


@router.get("/annual-launches")
def annual_launches() -> list[dict]:
    """R2 — Year-over-year launches and avg specs.

    LEFT JOIN to Platform so the launches count includes devices whose chipset
    info is missing. AVG(p.ram_gb) / AVG(p.internal_storage_gb) ignore NULL
    automatically, so those are computed only over devices with known platform.
    """
    current_year = datetime.now().year
    return _rows(
        f"""
        SELECT
            d.year,
            COUNT(*) AS launches,
            ROUND(AVG(d.price_eur), 2) AS avg_price_eur,
            ROUND(AVG(d.battery_capacity_mah)) AS avg_battery_mah,
            ROUND(AVG(p.ram_gb), 2) AS avg_ram_gb,
            ROUND(AVG(p.internal_storage_gb), 2) AS avg_storage_gb
        FROM Device d
        LEFT JOIN Platform p ON p.id = d.platform_id
        WHERE d.year BETWEEN 2010 AND {current_year}
        GROUP BY d.year
        ORDER BY d.year
        """
    )


@router.get("/chipset-popularity")
def chipset_popularity() -> list[dict]:
    """Q10 variant — chipset manufacturer share."""
    return _rows(
        """
        SELECT
            p.chipset_manufacturer,
            COUNT(*) AS device_count
        FROM Device d
        JOIN Platform p ON p.id = d.platform_id
        WHERE p.chipset_manufacturer IS NOT NULL
        GROUP BY p.chipset_manufacturer
        ORDER BY device_count DESC
        LIMIT 15
        """
    )


@router.get("/price-vs-battery")
def price_vs_battery() -> list[dict]:
    """Scatter: price vs battery capacity (one point per device)."""
    return _rows(
        """
        SELECT
            dn.brand,
            d.price_eur,
            d.battery_capacity_mah AS battery_mah,
            p.ram_gb,
            d.year
        FROM Device d
        JOIN Device_Name dn ON dn.id = d.device_name_id
        JOIN Platform p ON p.id = d.platform_id
        WHERE d.price_eur IS NOT NULL
          AND d.battery_capacity_mah IS NOT NULL
        """
    )


@router.get("/ram-distribution")
def ram_distribution() -> list[dict]:
    """RAM bucket distribution."""
    return _rows(
        """
        SELECT
            p.ram_gb,
            COUNT(*) AS device_count
        FROM Device d
        JOIN Platform p ON p.id = d.platform_id
        WHERE p.ram_gb IS NOT NULL
        GROUP BY p.ram_gb
        ORDER BY p.ram_gb
        """
    )


# ===========================================================================
# Section 2 — Distribution / ranking / trend endpoints (notebook Q1-Q8)
# ===========================================================================


@router.get("/network-technology")
def network_technology_distribution() -> list[dict]:
    """Q1 — Share of phones supporting each network generation.

    A device may support multiple generations (e.g. a 5G phone also speaks 4G
    and 3G), so percentages do not sum to 100. Detection uses LIKE patterns
    on the joined technology string.
    """
    df = _df(
        f"""
        SELECT nt.technology
        FROM Device d
        JOIN Network_Technology nt ON nt.id = d.network_technology_id
        WHERE {_PHONE}
        """
    )
    total = len(df)
    patterns = [
        ("2G", lambda s: s.str.contains('GSM', na=False) | s.str.contains('CDMA', na=False)),
        ("3G", lambda s: s.str.contains('HSPA', na=False) | s.str.contains('EVDO', na=False) | s.str.contains('CDMA2000', na=False)),
        ("4G", lambda s: s.str.contains('LTE', na=False)),
        ("5G", lambda s: s.str.contains('5G', na=False)),
    ]
    out: list[dict] = []
    for label, predicate in patterns:
        count = int(predicate(df['technology']).sum()) if total else 0
        out.append({
            "generation": label,
            "device_count": count,
            "pct": round(100.0 * count / total, 2) if total else 0.0,
        })
    return out


@router.get("/sim-type-distribution")
def sim_type_distribution() -> list[dict]:
    """Q3 — SIM-type distribution across phones."""
    return _rows(
        f"""
        SELECT s.sim_type, COUNT(*) AS device_count
        FROM Device d
        JOIN Sim s ON s.id = d.sim_id
        WHERE {_PHONE}
        GROUP BY s.sim_type
        ORDER BY device_count DESC
        """
    )


@router.get("/top-android-versions")
def top_android_versions(limit: int = 10) -> list[dict]:
    """Q4 — Top-N most common Android versions."""
    return _rows(
        f"""
        SELECT o.os_version, COUNT(*) AS device_count
        FROM Device d
        JOIN OS o ON o.id = d.os_id
        WHERE {_PHONE} AND o.os_name = 'Android' AND o.os_version IS NOT NULL
        GROUP BY o.os_version
        ORDER BY device_count DESC
        LIMIT {int(limit)}
        """
    )


@router.get("/top-expensive-phones")
def top_expensive_phones(limit: int = 50) -> list[dict]:
    """Q5 — Top-N most expensive phones with their OS."""
    return _rows(
        f"""
        SELECT dn.brand, dn.model, d.year, d.price_eur,
               o.os_name, o.os_version
        FROM Device d
        JOIN Device_Name dn ON dn.id = d.device_name_id
        LEFT JOIN OS o ON o.id = d.os_id
        WHERE {_PHONE} AND d.price_eur IS NOT NULL
        ORDER BY d.price_eur DESC
        LIMIT {int(limit)}
        """
    )


@router.get("/ppi-trend")
def ppi_trend() -> list[dict]:
    """Q7 — PPI density trend by year for Samsung / Xiaomi / Apple."""
    return _rows(
        f"""
        SELECT dn.brand, d.year, ROUND(AVG(disp.ppi_density), 2) AS avg_ppi,
               COUNT(*) AS device_count
        FROM Device d
        JOIN Device_Name dn ON dn.id = d.device_name_id
        JOIN Display disp ON disp.id = d.display_id
        WHERE {_PHONE}
          AND dn.brand IN ('Samsung', 'Xiaomi', 'Apple')
          AND disp.ppi_density IS NOT NULL
        GROUP BY dn.brand, d.year
        ORDER BY d.year, dn.brand
        """
    )


@router.get("/correlation-matrix")
def correlation_matrix() -> dict:
    """Q2 — Pearson correlation across the quantitative spec columns."""
    df = _df(
        f"""
        SELECT d.weight, d.length, d.width, d.height, d.volume,
               d.battery_capacity_mah AS battery_mah, d.price_eur,
               disp.display_size_inch, disp.screen_to_body_ratio,
               disp.resolution_pixels, disp.ppi_density,
               p.cpu_core_count, p.internal_storage_gb, p.ram_gb
        FROM Device d
        LEFT JOIN Display disp ON disp.id = d.display_id
        LEFT JOIN Platform p ON p.id = d.platform_id
        WHERE {_PHONE}
        """
    )
    matrix = df.corr(numeric_only=True).round(3)
    return {
        "columns": list(matrix.columns),
        "matrix": [[None if pd.isna(v) else float(v) for v in row] for row in matrix.values.tolist()],
    }


@router.get("/quantitative-distributions")
def quantitative_distributions() -> dict:
    """Q8 — Raw values for each quantitative column. Frontend bins them."""
    df = _df(
        f"""
        SELECT d.weight, d.length, d.width, d.height, d.volume,
               d.battery_capacity_mah AS battery_mah, d.price_eur,
               disp.display_size_inch, disp.screen_to_body_ratio,
               disp.ppi_density, p.ram_gb, p.internal_storage_gb
        FROM Device d
        LEFT JOIN Display disp ON disp.id = d.display_id
        LEFT JOIN Platform p ON p.id = d.platform_id
        WHERE {_PHONE}
        """
    )
    return {
        col: df[col].dropna().tolist() for col in df.columns
    }


# ===========================================================================
# Section 3 — Inferential stats (notebook Estimation + HT1-HT6)
# ===========================================================================


@router.get("/price-ci-2023")
def price_ci_2023(alpha: float = 0.02) -> list[dict]:
    """Estimation — per-brand price 98% CI for 2023 (Apple, Samsung, Huawei,
    Xiaomi, Nokia). Uses parametric t-distribution CI; mirrors notebook cell 35."""
    df = _df(
        f"""
        SELECT dn.brand, d.price_eur
        FROM Device d
        JOIN Device_Name dn ON dn.id = d.device_name_id
        WHERE {_PHONE} AND d.year = 2023 AND d.price_eur IS NOT NULL
          AND dn.brand IN ('Apple', 'Samsung', 'Huawei', 'Xiaomi', 'Nokia')
        """
    )
    out: list[dict] = []
    for brand in ['Apple', 'Samsung', 'Huawei', 'Xiaomi', 'Nokia']:
        group = df.loc[df['brand'] == brand, 'price_eur'].dropna().to_numpy()
        n = len(group)
        if n < 2:
            out.append({"brand": brand, "n": n, "mean": None, "std": None,
                        "lower": None, "upper": None, "alpha": alpha})
            continue
        mean = float(np.mean(group))
        std = float(np.std(group, ddof=1))
        t_score = float(stats.t.ppf(1 - alpha / 2, df=n - 1))
        margin = t_score * std / np.sqrt(n)
        out.append({
            "brand": brand, "n": n,
            "mean": round(mean, 2), "std": round(std, 2),
            "lower": round(mean - margin, 2), "upper": round(mean + margin, 2),
            "alpha": alpha,
        })
    return out


def _ht_response(name: str, description: str, test_block: dict,
                 groups: list[dict], alpha: float = 0.05) -> dict:
    """Common envelope for hypothesis-test endpoints."""
    return {
        "name": name,
        "description": description,
        **test_block,
        "alpha": alpha,
        "conclusion": _conclusion(test_block.get("p_value"), alpha),
        "groups": groups,
    }


@router.get("/ht-price-by-sim-and-size")
def ht_price_by_sim_and_size() -> dict:
    """HT1 — Two-way ANOVA: price ~ sim_type * size. SIM types: nano/micro/mini."""
    df = _df(
        f"""
        SELECT d.price_eur AS price, s.sim_type, disp.display_size_inch
        FROM Device d
        JOIN Sim s ON s.id = d.sim_id
        JOIN Display disp ON disp.id = d.display_id
        WHERE {_PHONE} AND d.price_eur IS NOT NULL
          AND s.sim_type IN ('nano', 'micro', 'mini')
        """
    ).dropna()
    df['size'] = _classify_size(df['display_size_inch'])
    anova = _anova_table('price ~ C(sim_type) * C(size)', df)
    groups = [
        {"sim_type": str(g[0]), "size": str(g[1]), **_group_summary(sub['price'].to_numpy())}
        for g, sub in df.groupby(['sim_type', 'size'])
    ]
    main_effect = next((row for row in anova if 'sim_type' in row['factor'] and ':' not in row['factor']), None)
    return _ht_response(
        name="Price differs by SIM type and device size?",
        description="Two-way ANOVA on price with SIM type (nano/micro/mini) and size (small/large) as factors.",
        test_block={"test": "two-way ANOVA", "anova": anova,
                    "p_value": main_effect["p_value"] if main_effect else None},
        groups=groups,
    )


@router.get("/ht-ppi-by-size")
def ht_ppi_by_size() -> dict:
    """HT2 — t-test (or Mann-Whitney U) on PPI between small and large devices."""
    df = _df(
        f"""
        SELECT disp.ppi_density, disp.display_size_inch
        FROM Device d
        JOIN Display disp ON disp.id = d.display_id
        WHERE {_PHONE} AND disp.ppi_density IS NOT NULL
        """
    ).dropna()
    df['size'] = _classify_size(df['display_size_inch'])
    small = df.loc[df['size'] == 'small', 'ppi_density'].to_numpy()
    large = df.loc[df['size'] == 'large', 'ppi_density'].to_numpy()
    test = _t_or_mannwhitney(small, large)
    return _ht_response(
        name="PPI differs between small and large devices?",
        description="Two-sample test on screen PPI density. Small = display size <7\", large = ≥7\".",
        test_block=test,
        groups=[
            {"size": "small", **_group_summary(small)},
            {"size": "large", **_group_summary(large)},
        ],
    )


@router.get("/ht-weight-android-vs-ios")
def ht_weight_android_vs_ios() -> dict:
    """HT3 — t-test (or Mann-Whitney U) on weight between Android and iOS phones."""
    df = _df(
        f"""
        SELECT d.weight, o.os_name
        FROM Device d
        JOIN OS o ON o.id = d.os_id
        WHERE {_PHONE} AND d.weight IS NOT NULL
          AND o.os_name IN ('Android', 'iOS')
        """
    ).dropna()
    android = df.loc[df['os_name'] == 'Android', 'weight'].to_numpy()
    ios = df.loc[df['os_name'] == 'iOS', 'weight'].to_numpy()
    test = _t_or_mannwhitney(android, ios)
    return _ht_response(
        name="Phone weight differs between Android and iOS?",
        description="Two-sample test on body weight (g) between Android and iOS phones.",
        test_block=test,
        groups=[
            {"os_name": "Android", **_group_summary(android)},
            {"os_name": "iOS", **_group_summary(ios)},
        ],
    )


@router.get("/ht-battery-by-brand-and-size")
def ht_battery_by_brand_and_size() -> dict:
    """HT4 — Two-way ANOVA: battery ~ brand * size for Samsung/Xiaomi/Apple."""
    df = _df(
        f"""
        SELECT dn.brand, d.battery_capacity_mah AS battery, disp.display_size_inch
        FROM Device d
        JOIN Device_Name dn ON dn.id = d.device_name_id
        JOIN Display disp ON disp.id = d.display_id
        WHERE {_PHONE}
          AND dn.brand IN ('Samsung', 'Xiaomi', 'Apple')
          AND d.battery_capacity_mah IS NOT NULL
        """
    ).dropna()
    df['size'] = _classify_size(df['display_size_inch'])
    anova = _anova_table('battery ~ C(brand) * C(size)', df)
    groups = [
        {"brand": str(g[0]), "size": str(g[1]), **_group_summary(sub['battery'].to_numpy())}
        for g, sub in df.groupby(['brand', 'size'])
    ]
    main_effect = next((row for row in anova if 'brand' in row['factor'] and ':' not in row['factor']), None)
    return _ht_response(
        name="Battery capacity differs by brand and device size?",
        description="Two-way ANOVA on battery capacity (mAh) for Samsung / Xiaomi / Apple, factoring small vs large size.",
        test_block={"test": "two-way ANOVA", "anova": anova,
                    "p_value": main_effect["p_value"] if main_effect else None},
        groups=groups,
    )


@router.get("/ht-price-by-brand-and-size")
def ht_price_by_brand_and_size() -> dict:
    """HT5 — Two-way ANOVA: price ~ brand * size for Samsung/Xiaomi/Apple."""
    df = _df(
        f"""
        SELECT dn.brand, d.price_eur AS price, disp.display_size_inch
        FROM Device d
        JOIN Device_Name dn ON dn.id = d.device_name_id
        JOIN Display disp ON disp.id = d.display_id
        WHERE {_PHONE}
          AND dn.brand IN ('Samsung', 'Xiaomi', 'Apple')
          AND d.price_eur IS NOT NULL
        """
    ).dropna()
    df['size'] = _classify_size(df['display_size_inch'])
    anova = _anova_table('price ~ C(brand) * C(size)', df)
    groups = [
        {"brand": str(g[0]), "size": str(g[1]), **_group_summary(sub['price'].to_numpy())}
        for g, sub in df.groupby(['brand', 'size'])
    ]
    main_effect = next((row for row in anova if 'brand' in row['factor'] and ':' not in row['factor']), None)
    return _ht_response(
        name="Price differs by brand and device size?",
        description="Two-way ANOVA on price for Samsung / Xiaomi / Apple, factoring small vs large size.",
        test_block={"test": "two-way ANOVA", "anova": anova,
                    "p_value": main_effect["p_value"] if main_effect else None},
        groups=groups,
    )


@router.get("/ht-weight-by-size")
def ht_weight_by_size() -> dict:
    """HT6 — t-test (or Mann-Whitney U) on weight between small and large devices."""
    df = _df(
        f"""
        SELECT d.weight, disp.display_size_inch
        FROM Device d
        JOIN Display disp ON disp.id = d.display_id
        WHERE {_PHONE} AND d.weight IS NOT NULL
        """
    ).dropna()
    df['size'] = _classify_size(df['display_size_inch'])
    small = df.loc[df['size'] == 'small', 'weight'].to_numpy()
    large = df.loc[df['size'] == 'large', 'weight'].to_numpy()
    test = _t_or_mannwhitney(small, large)
    return _ht_response(
        name="Weight differs between small and large devices?",
        description="Two-sample test on body weight (g). Small = display <7\", large = ≥7\".",
        test_block=test,
        groups=[
            {"size": "small", **_group_summary(small)},
            {"size": "large", **_group_summary(large)},
        ],
    )
