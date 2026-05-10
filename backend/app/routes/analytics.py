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
from typing import Any, Literal

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

# All analytics endpoints accept a form_factor query param so the same set of
# charts can be rendered for phones / watches / tablets / bands / 'other'.
# The phone tab is the default for backwards compatibility.
FormFactor = Literal['phone', 'watch', 'tablet', 'band', 'other']
_PHONE = "d.form_factor = 'phone'"  # legacy constant; prefer _form_filter()


def _form_filter(form_factor: str) -> str:
    """SQL fragment restricting `Device d` to the given form factor.

    Inlined into each endpoint's WHERE clause. Uses single quotes so it can
    sit in an f-string without an extra parameter binding.
    """
    # Defensive: parameter is FastAPI-validated against the Literal, but this
    # also runs from tests / direct calls. Reject anything unexpected.
    if form_factor not in ('phone', 'watch', 'tablet', 'band', 'other'):
        raise ValueError(f"unknown form_factor: {form_factor!r}")
    return f"d.form_factor = '{form_factor}'"


def _rows(sql: str) -> list[dict]:
    with ro_engine().connect() as conn:
        return [dict(r) for r in conn.execute(text(sql)).mappings().all()]


def _df(sql: str) -> pd.DataFrame:
    with ro_engine().connect() as conn:
        return pd.read_sql(text(sql), conn)


def _top_brands(form_factor: str, n: int) -> list[str]:
    """Return the N most-populous brand names within the given form factor.

    Used by analyses that previously hardcoded phone-only brand sets
    (Apple/Samsung/Xiaomi for trends, Apple/Samsung/Huawei/Xiaomi/Nokia for
    confidence intervals). Auto-picking lets the same endpoint produce
    sensible output for watches and tablets without code changes.
    """
    df = _df(f"""
        SELECT dn.brand, COUNT(*) AS n
        FROM Device d
        JOIN Device_Name dn ON dn.id = d.device_name_id
        WHERE {_form_filter(form_factor)}
        GROUP BY dn.brand
        ORDER BY n DESC, dn.brand ASC
        LIMIT {int(n)}
    """)
    return df['brand'].tolist()


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


def _residual_diagnostics(model, max_points: int = 500) -> dict:
    """Compute the standard OLS residual-diagnostic suite for a fitted model.

    Returns fitted/residual sample for scatter plot, QQ-plot data, formal
    tests for heteroscedasticity (Breusch-Pagan) and normality (Jarque-Bera),
    VIF per predictor, top influential observations by Cook's distance, and
    the count of large standardized residuals.
    """
    from statsmodels.stats.diagnostic import het_breuschpagan
    from statsmodels.stats.outliers_influence import variance_inflation_factor
    from statsmodels.stats.stattools import jarque_bera

    fitted = model.fittedvalues.to_numpy()
    resid = model.resid.to_numpy()
    std_resid = (resid - resid.mean()) / resid.std() if resid.std() > 0 else np.zeros_like(resid)
    n = len(resid)

    rng = np.random.default_rng(0)
    sample_idx = rng.choice(n, min(max_points, n), replace=False)
    sample = [
        {"fitted": float(fitted[i]), "residual": float(resid[i]),
         "standardized": float(std_resid[i])}
        for i in sample_idx
    ]

    # QQ data: sort standardized residuals against theoretical normal quantiles.
    order = np.argsort(std_resid)
    theoretical = stats.norm.ppf((np.arange(n) + 0.5) / n)
    qq_step = max(1, n // max_points)
    qq = [
        {"theoretical": float(theoretical[i]), "sample": float(std_resid[order[i]])}
        for i in range(0, n, qq_step)
    ]

    # Heteroscedasticity (Breusch-Pagan).
    try:
        bp_lm, bp_lm_p, bp_f, bp_f_p = het_breuschpagan(resid, model.model.exog)
        breusch_pagan = {"lm": float(bp_lm), "p_value": float(bp_lm_p),
                         "f": float(bp_f), "f_p_value": float(bp_f_p)}
    except (ValueError, np.linalg.LinAlgError):
        breusch_pagan = {"lm": None, "p_value": None, "f": None, "f_p_value": None}

    # Normality (Jarque-Bera).
    try:
        jb, jb_p, skew_v, kurt_v = jarque_bera(resid)
        jarque_bera_block = {"statistic": float(jb), "p_value": float(jb_p),
                             "skew": float(skew_v), "kurtosis": float(kurt_v)}
    except (ValueError, np.linalg.LinAlgError):
        jarque_bera_block = {"statistic": None, "p_value": None,
                             "skew": None, "kurtosis": None}

    # VIF per predictor (skip Intercept).
    vif_rows: list[dict] = []
    exog = model.model.exog
    for i, name in enumerate(model.model.exog_names):
        if name == "Intercept":
            continue
        try:
            v = variance_inflation_factor(exog, i)
            v = None if (np.isnan(v) or np.isinf(v)) else float(v)
        except (ValueError, np.linalg.LinAlgError, ZeroDivisionError):
            v = None
        vif_rows.append({"predictor": str(name), "vif": v})

    # Cook's distance: top-10 most influential observations.
    try:
        influence = model.get_influence()
        cooks_d = influence.cooks_distance[0]
        top_idx = np.argsort(cooks_d)[-10:][::-1]
        top_cooks = [
            {"index": int(i), "cooks_d": float(cooks_d[i]),
             "fitted": float(fitted[i]), "residual": float(resid[i])}
            for i in top_idx
        ]
    except (ValueError, np.linalg.LinAlgError, AttributeError):
        top_cooks = []

    return {
        "n": int(n),
        "mean_residual": float(np.mean(resid)),
        "std_residual": float(np.std(resid, ddof=1)) if n > 1 else None,
        "sample_residuals": sample,
        "qq_plot": qq,
        "breusch_pagan": breusch_pagan,
        "jarque_bera": jarque_bera_block,
        "vif": vif_rows,
        "top_cooks_d": top_cooks,
        "n_outliers_z3": int(np.sum(np.abs(std_resid) > 3)),
    }


def _forward_stepwise(data: pd.DataFrame, response: str,
                      candidates: list[str]) -> dict:
    """Forward stepwise selection by adjusted R².

    At each step, fit `response ~ <selected> + <candidate>` for every
    remaining candidate and keep the one giving the highest adjusted R².
    Stop when no addition improves adj R². Returns the step-by-step path
    and a summary of the final (best) model.
    """
    selected: list[str] = []
    history: list[dict] = []
    best_adj_r2 = -float("inf")
    best_model = None

    while True:
        best_step = None
        best_step_score = best_adj_r2
        best_step_model = None
        for feat in candidates:
            if feat in selected:
                continue
            terms = selected + [feat]
            formula = f"{response} ~ " + " + ".join(terms)
            try:
                m = ols(formula, data=data).fit()
            except (ValueError, np.linalg.LinAlgError):
                continue
            if m.rsquared_adj > best_step_score:
                best_step_score = m.rsquared_adj
                best_step = feat
                best_step_model = m
        if best_step is None:
            break
        selected.append(best_step)
        best_adj_r2 = best_step_score
        best_model = best_step_model
        history.append({
            "step": len(selected),
            "added": best_step,
            "formula": f"{response} ~ " + " + ".join(selected),
            "adj_r_squared": float(best_step_model.rsquared_adj),
            "r_squared": float(best_step_model.rsquared),
            "aic": float(best_step_model.aic),
            "bic": float(best_step_model.bic),
            "n_predictors": int(best_step_model.df_model),
        })

    if best_model is None:
        return {"error": "no candidate could improve adjusted R²",
                "history": [], "final_summary": None}

    final_formula = f"{response} ~ " + " + ".join(selected)
    return {
        "history": history,
        "final_features": selected,
        "final_formula": final_formula,
        "final_summary": _ols_summary(final_formula, data),
    }


def _safe_ols_fit(df: pd.DataFrame, response: str,
                  numeric: list[str], categorical: list[str],
                  min_rows: int = 10) -> dict:
    """Fit OLS resiliently — drops predictors whose column is entirely NaN
    (e.g. `screen_to_body_ratio` for watches, where GSMArena doesn't publish
    a S2B figure). The previous code called `df.dropna()` first, which would
    delete every row whenever any single predictor was 100% NaN.

    Returns the same shape as `_ols_summary`, plus `dropped_predictors`
    listing the columns that were excluded for this form factor.
    """
    available_num = [c for c in numeric if c in df.columns and df[c].notna().any()]
    available_cat = [c for c in categorical if c in df.columns and df[c].notna().any()]
    dropped = [c for c in numeric + categorical
               if c not in available_num + available_cat]

    keep_cols = [response] + available_num + available_cat
    df_clean = df[keep_cols].dropna()

    if not available_num and not available_cat:
        return {"error": "no usable predictors for this form factor",
                "n": 0, "dropped_predictors": dropped, "coefficients": []}
    if len(df_clean) < min_rows:
        return {"error": f"only {len(df_clean)} rows after dropna; need ≥{min_rows}",
                "n": len(df_clean), "dropped_predictors": dropped,
                "coefficients": []}

    terms = available_num + [f'C({c})' for c in available_cat]
    formula = f"{response} ~ " + ' + '.join(terms)
    summary = _ols_summary(formula, df_clean)
    summary['dropped_predictors'] = dropped
    summary['formula'] = formula
    return summary


def _ols_summary(model_formula: str, data: pd.DataFrame) -> dict:
    """Fit OLS and return coefficient table + overall fit stats.

    Output shape:
      {
        "n": int, "r_squared": float, "adj_r_squared": float,
        "f_statistic": float, "f_p_value": float,
        "coefficients": [
          {"name": "battery_mah", "coef": ..., "std_err": ..., "t": ..., "p_value": ...},
          ...
        ],
      }

    Returns a dict with `error` if the design is degenerate.
    """
    try:
        model = ols(model_formula, data=data).fit()
    except (ValueError, np.linalg.LinAlgError) as exc:
        return {"error": str(exc), "n": int(len(data))}

    def _safe(value: Any) -> float | None:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return None
        return None if (np.isnan(v) or np.isinf(v)) else v

    coefs = []
    for name in model.params.index:
        coefs.append({
            "name": str(name),
            "coef": _safe(model.params[name]),
            "std_err": _safe(model.bse[name]),
            "t": _safe(model.tvalues[name]),
            "p_value": _safe(model.pvalues[name]),
        })
    return {
        "n": int(model.nobs),
        "r_squared": _safe(model.rsquared),
        "adj_r_squared": _safe(model.rsquared_adj),
        "f_statistic": _safe(model.fvalue),
        "f_p_value": _safe(model.f_pvalue),
        "coefficients": coefs,
    }


# ===========================================================================
# Section 1 — R-style summary endpoints
# ===========================================================================


@router.get("/brand-summary")
def brand_summary(form_factor: FormFactor = "phone") -> list[dict]:
    """R1 — Brand catalogue summary: model count, avg price, year span."""
    return _rows(
        f"""
        SELECT
            dn.brand,
            COUNT(*) AS device_count,
            ROUND(AVG(d.price_eur), 2) AS avg_price_eur,
            MIN(d.year) AS first_year,
            MAX(d.year) AS last_year
        FROM Device d
        JOIN Device_Name dn ON dn.id = d.device_name_id
        WHERE {_form_filter(form_factor)} AND d.price_eur IS NOT NULL
        GROUP BY dn.brand
        HAVING COUNT(*) >= 3
        ORDER BY device_count DESC
        """
    )


@router.get("/annual-launches")
def annual_launches(form_factor: FormFactor = "phone") -> list[dict]:
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
        WHERE {_form_filter(form_factor)} AND d.year BETWEEN 2010 AND {current_year}
        GROUP BY d.year
        ORDER BY d.year
        """
    )


@router.get("/chipset-popularity")
def chipset_popularity(form_factor: FormFactor = "phone") -> list[dict]:
    """Q10 variant — chipset manufacturer share."""
    return _rows(
        f"""
        SELECT
            p.chipset_manufacturer,
            COUNT(*) AS device_count
        FROM Device d
        JOIN Platform p ON p.id = d.platform_id
        WHERE {_form_filter(form_factor)} AND p.chipset_manufacturer IS NOT NULL
        GROUP BY p.chipset_manufacturer
        ORDER BY device_count DESC
        LIMIT 15
        """
    )


@router.get("/price-vs-battery")
def price_vs_battery(form_factor: FormFactor = "phone") -> list[dict]:
    """Scatter: price vs battery capacity (one point per device)."""
    return _rows(
        f"""
        SELECT
            dn.brand,
            d.price_eur,
            d.battery_capacity_mah AS battery_mah,
            p.ram_gb,
            d.year
        FROM Device d
        JOIN Device_Name dn ON dn.id = d.device_name_id
        JOIN Platform p ON p.id = d.platform_id
        WHERE {_form_filter(form_factor)}
          AND d.price_eur IS NOT NULL
          AND d.battery_capacity_mah IS NOT NULL
        """
    )


@router.get("/ram-distribution")
def ram_distribution(form_factor: FormFactor = "phone") -> list[dict]:
    """RAM bucket distribution."""
    return _rows(
        f"""
        SELECT
            p.ram_gb,
            COUNT(*) AS device_count
        FROM Device d
        JOIN Platform p ON p.id = d.platform_id
        WHERE {_form_filter(form_factor)} AND p.ram_gb IS NOT NULL
        GROUP BY p.ram_gb
        ORDER BY p.ram_gb
        """
    )


# ===========================================================================
# Section 2 — Distribution / ranking / trend endpoints (notebook Q1-Q8)
# ===========================================================================


@router.get("/network-technology")
def network_technology_distribution(form_factor: FormFactor = "phone") -> list[dict]:
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
        WHERE {_form_filter(form_factor)}
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
def sim_type_distribution(form_factor: FormFactor = "phone") -> list[dict]:
    """Q3 — SIM-type distribution across phones."""
    return _rows(
        f"""
        SELECT s.sim_type, COUNT(*) AS device_count
        FROM Device d
        JOIN Sim s ON s.id = d.sim_id
        WHERE {_form_filter(form_factor)}
        GROUP BY s.sim_type
        ORDER BY device_count DESC
        """
    )


@router.get("/top-android-versions")
def top_android_versions(limit: int = 10, form_factor: FormFactor = "phone") -> list[dict]:
    """Q4 — Top-N most common Android versions."""
    return _rows(
        f"""
        SELECT o.os_version, COUNT(*) AS device_count
        FROM Device d
        JOIN OS o ON o.id = d.os_id
        WHERE {_form_filter(form_factor)} AND o.os_name = 'Android' AND o.os_version IS NOT NULL
        GROUP BY o.os_version
        ORDER BY device_count DESC
        LIMIT {int(limit)}
        """
    )


@router.get("/top-expensive-phones")
def top_expensive_phones(limit: int = 50, form_factor: FormFactor = "phone") -> list[dict]:
    """Q5 — Top-N most expensive phones with their OS.

    `Device` is per-configuration (a phone with 3 storage tiers is 3 rows),
    so a naive `ORDER BY price LIMIT N` produces duplicate model rows.
    The window function picks the most-expensive config of each
    (brand, model) and ranks across those representatives.
    """
    return _rows(
        f"""
        WITH ranked AS (
            SELECT dn.brand, dn.model, d.year, d.price_eur,
                   o.os_name, o.os_version,
                   ROW_NUMBER() OVER (
                       PARTITION BY dn.brand, dn.model
                       ORDER BY d.price_eur DESC
                   ) AS rn
            FROM Device d
            JOIN Device_Name dn ON dn.id = d.device_name_id
            LEFT JOIN OS o ON o.id = d.os_id
            WHERE {_form_filter(form_factor)} AND d.price_eur IS NOT NULL
        )
        SELECT brand, model, year, price_eur, os_name, os_version
        FROM ranked
        WHERE rn = 1
        ORDER BY price_eur DESC
        LIMIT {int(limit)}
        """
    )


@router.get("/ppi-trend")
def ppi_trend(form_factor: FormFactor = "phone") -> list[dict]:
    """Q7 — PPI density trend by year for the top-3 brands of this form factor."""
    brands = _top_brands(form_factor, 3)
    if not brands:
        return []
    brand_list = ", ".join(f"'{b.replace(chr(39), chr(39) * 2)}'" for b in brands)
    return _rows(
        f"""
        SELECT dn.brand, d.year, ROUND(AVG(disp.ppi_density), 2) AS avg_ppi,
               COUNT(*) AS device_count
        FROM Device d
        JOIN Device_Name dn ON dn.id = d.device_name_id
        JOIN Display disp ON disp.id = d.display_id
        WHERE {_form_filter(form_factor)}
          AND dn.brand IN ({brand_list})
          AND disp.ppi_density IS NOT NULL
        GROUP BY dn.brand, d.year
        ORDER BY d.year, dn.brand
        """
    )


@router.get("/correlation-matrix")
def correlation_matrix(form_factor: FormFactor = "phone") -> dict:
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
        WHERE {_form_filter(form_factor)}
        """
    )
    matrix = df.corr(numeric_only=True).round(3)
    return {
        "columns": list(matrix.columns),
        "matrix": [[None if pd.isna(v) else float(v) for v in row] for row in matrix.values.tolist()],
    }


@router.get("/quantitative-distributions")
def quantitative_distributions(form_factor: FormFactor = "phone") -> dict:
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
        WHERE {_form_filter(form_factor)}
        """
    )
    return {
        col: df[col].dropna().tolist() for col in df.columns
    }


# ===========================================================================
# Section 3 — Inferential stats (notebook Estimation + HT1-HT6)
# ===========================================================================


def _t_ci_per_brand(
    column: str,
    alpha: float,
    form_factor: str,
    year: int | None = None,
) -> list[dict]:
    """Parametric t-distribution CI for `column` across the top-5 brands.

    `column` must be a quantitative column on `Device` (e.g. price_eur,
    battery_capacity_mah). When `year` is None, all rows for the form factor
    are pooled; otherwise only rows for that year are used.
    """
    brands = _top_brands(form_factor, 5)
    if not brands:
        return []
    brand_list = ", ".join(f"'{b.replace(chr(39), chr(39) * 2)}'" for b in brands)
    year_filter = f" AND d.year = {int(year)}" if year is not None else ""
    df = _df(
        f"""
        SELECT dn.brand, d.{column} AS value
        FROM Device d
        JOIN Device_Name dn ON dn.id = d.device_name_id
        WHERE {_form_filter(form_factor)}{year_filter}
          AND d.{column} IS NOT NULL
          AND dn.brand IN ({brand_list})
        """
    )
    out: list[dict] = []
    for brand in brands:
        group = df.loc[df['brand'] == brand, 'value'].dropna().to_numpy()
        n = len(group)
        row: dict[str, Any] = {
            "brand": brand, "n": n, "alpha": alpha,
            "mean": None, "std": None, "lower": None, "upper": None,
        }
        if year is not None:
            row["year"] = int(year)
        if n >= 2:
            mean = float(np.mean(group))
            std = float(np.std(group, ddof=1))
            t_score = float(stats.t.ppf(1 - alpha / 2, df=n - 1))
            margin = t_score * std / np.sqrt(n)
            row.update({
                "mean": round(mean, 2),
                "std": round(std, 2),
                "lower": round(mean - margin, 2),
                "upper": round(mean + margin, 2),
            })
        out.append(row)
    return out


def _resolve_year(year: int | None, form_factor: str) -> int | None:
    """If `year` is None, pick the most-recent year present for the form
    factor. Returns None only when the form factor has no rows at all.
    """
    if year is not None:
        return int(year)
    df = _df(
        f"SELECT MAX(d.year) AS y FROM Device d WHERE {_form_filter(form_factor)}"
    )
    if df.empty or df["y"].isna().all():
        return None
    return int(df["y"].iloc[0])


@router.get("/price-ci-by-brand")
def price_ci_by_brand(
    year: int | None = None,
    alpha: float = 0.05,
    form_factor: FormFactor = "phone",
) -> list[dict]:
    """Estimation — per-brand price CI for one year across the top-5 brands.

    `year` defaults to the most-recent year present for the given form factor.
    `alpha` defaults to 0.05 (95% CI), matching the rest of the endpoints.
    """
    resolved = _resolve_year(year, form_factor)
    if resolved is None:
        return []
    return _t_ci_per_brand("price_eur", alpha, form_factor, year=resolved)


@router.get("/battery-ci-by-brand")
def battery_ci_by_brand(
    alpha: float = 0.05,
    form_factor: FormFactor = "phone",
) -> list[dict]:
    """Estimation — per-brand battery-capacity (mAh) CI across the top-5 brands.

    No year filter: battery capacity is comparatively stable across release
    years, so pooling all rows for the form factor gives the tightest interval.
    """
    return _t_ci_per_brand("battery_capacity_mah", alpha, form_factor)


def _ht_response(name: str, description: str, test_block: dict,
                 groups: list[dict],
                 null_hypothesis: str = "",
                 alternative_hypothesis: str = "",
                 alpha: float = 0.05) -> dict:
    """Common envelope for hypothesis-test endpoints."""
    p = test_block.get("p_value")
    decision = (
        "reject H₀" if (p is not None and p < alpha)
        else ("fail to reject H₀" if p is not None else "insufficient data")
    )
    return {
        "name": name,
        "description": description,
        "null_hypothesis": null_hypothesis,
        "alternative_hypothesis": alternative_hypothesis,
        **test_block,
        "alpha": alpha,
        "decision": decision,
        "conclusion": _conclusion(p, alpha),
        "groups": groups,
    }


@router.get("/ht-price-by-sim-and-size")
def ht_price_by_sim_and_size(form_factor: FormFactor = "phone") -> dict:
    """HT1 — Two-way ANOVA: price ~ sim_type * size. SIM types: nano/micro/mini."""
    df = _df(
        f"""
        SELECT d.price_eur AS price, s.sim_type, disp.display_size_inch
        FROM Device d
        JOIN Sim s ON s.id = d.sim_id
        JOIN Display disp ON disp.id = d.display_id
        WHERE {_form_filter(form_factor)} AND d.price_eur IS NOT NULL
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
        null_hypothesis="Mean price is the same across every SIM-type × size group.",
        alternative_hypothesis="At least one SIM-type × size combination has a different mean price.",
        test_block={"test": "two-way ANOVA", "anova": anova,
                    "p_value": main_effect["p_value"] if main_effect else None},
        groups=groups,
    )


@router.get("/ht-ppi-by-size")
def ht_ppi_by_size(form_factor: FormFactor = "phone") -> dict:
    """HT2 — t-test (or Mann-Whitney U) on PPI between small and large devices."""
    df = _df(
        f"""
        SELECT disp.ppi_density, disp.display_size_inch
        FROM Device d
        JOIN Display disp ON disp.id = d.display_id
        WHERE {_form_filter(form_factor)} AND disp.ppi_density IS NOT NULL
        """
    ).dropna()
    df['size'] = _classify_size(df['display_size_inch'])
    small = df.loc[df['size'] == 'small', 'ppi_density'].to_numpy()
    large = df.loc[df['size'] == 'large', 'ppi_density'].to_numpy()
    test = _t_or_mannwhitney(small, large)
    return _ht_response(
        name="PPI differs between small and large devices?",
        description="Two-sample test on screen PPI density. Small = display size <7\", large = ≥7\".",
        null_hypothesis="Mean PPI density is the same in small and large devices.",
        alternative_hypothesis="Mean PPI density differs between small and large devices.",
        test_block=test,
        groups=[
            {"size": "small", **_group_summary(small)},
            {"size": "large", **_group_summary(large)},
        ],
    )


@router.get("/ht-weight-android-vs-ios")
def ht_weight_android_vs_ios(form_factor: FormFactor = "phone") -> dict:
    """HT3 — t-test (or Mann-Whitney U) on weight between Android and iOS phones."""
    df = _df(
        f"""
        SELECT d.weight, o.os_name
        FROM Device d
        JOIN OS o ON o.id = d.os_id
        WHERE {_form_filter(form_factor)} AND d.weight IS NOT NULL
          AND o.os_name IN ('Android', 'iOS')
        """
    ).dropna()
    android = df.loc[df['os_name'] == 'Android', 'weight'].to_numpy()
    ios = df.loc[df['os_name'] == 'iOS', 'weight'].to_numpy()
    test = _t_or_mannwhitney(android, ios)
    return _ht_response(
        name="Phone weight differs between Android and iOS?",
        description="Two-sample test on body weight (g) between Android and iOS phones.",
        null_hypothesis="Mean body weight is the same on Android and iOS phones.",
        alternative_hypothesis="Mean body weight differs between Android and iOS phones.",
        test_block=test,
        groups=[
            {"os_name": "Android", **_group_summary(android)},
            {"os_name": "iOS", **_group_summary(ios)},
        ],
    )


@router.get("/ht-battery-by-brand-and-size")
def ht_battery_by_brand_and_size(form_factor: FormFactor = "phone") -> dict:
    """HT4 — Two-way ANOVA: battery ~ brand × size for the top-3 brands of
    this form factor."""
    brands = _top_brands(form_factor, 3)
    if not brands:
        return _ht_response(
            name="Battery capacity differs by brand and device size?",
            description="No brands available for this form factor.",
            test_block={"test": "two-way ANOVA", "anova": [], "p_value": None},
            groups=[],
        )
    brand_list = ", ".join(f"'{b.replace(chr(39), chr(39) * 2)}'" for b in brands)
    df = _df(
        f"""
        SELECT dn.brand, d.battery_capacity_mah AS battery, disp.display_size_inch
        FROM Device d
        JOIN Device_Name dn ON dn.id = d.device_name_id
        JOIN Display disp ON disp.id = d.display_id
        WHERE {_form_filter(form_factor)}
          AND dn.brand IN ({brand_list})
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
        description=f"Two-way ANOVA on battery capacity (mAh) for {' / '.join(brands)}, factoring small vs large size.",
        null_hypothesis="Mean battery capacity is the same across every brand × size group.",
        alternative_hypothesis="At least one brand × size combination has a different mean battery capacity.",
        test_block={"test": "two-way ANOVA", "anova": anova,
                    "p_value": main_effect["p_value"] if main_effect else None},
        groups=groups,
    )


@router.get("/ht-price-by-brand-and-size")
def ht_price_by_brand_and_size(form_factor: FormFactor = "phone") -> dict:
    """HT5 — Two-way ANOVA: price ~ brand × size for the top-3 brands of
    this form factor."""
    brands = _top_brands(form_factor, 3)
    if not brands:
        return _ht_response(
            name="Price differs by brand and device size?",
            description="No brands available for this form factor.",
            test_block={"test": "two-way ANOVA", "anova": [], "p_value": None},
            groups=[],
        )
    brand_list = ", ".join(f"'{b.replace(chr(39), chr(39) * 2)}'" for b in brands)
    df = _df(
        f"""
        SELECT dn.brand, d.price_eur AS price, disp.display_size_inch
        FROM Device d
        JOIN Device_Name dn ON dn.id = d.device_name_id
        JOIN Display disp ON disp.id = d.display_id
        WHERE {_form_filter(form_factor)}
          AND dn.brand IN ({brand_list})
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
        description=f"Two-way ANOVA on price for {' / '.join(brands)}, factoring small vs large size.",
        null_hypothesis="Mean price is the same across every brand × size group.",
        alternative_hypothesis="At least one brand × size combination has a different mean price.",
        test_block={"test": "two-way ANOVA", "anova": anova,
                    "p_value": main_effect["p_value"] if main_effect else None},
        groups=groups,
    )


@router.get("/ht-weight-by-size")
def ht_weight_by_size(form_factor: FormFactor = "phone") -> dict:
    """HT6 — t-test (or Mann-Whitney U) on weight between small and large devices."""
    df = _df(
        f"""
        SELECT d.weight, disp.display_size_inch
        FROM Device d
        JOIN Display disp ON disp.id = d.display_id
        WHERE {_form_filter(form_factor)} AND d.weight IS NOT NULL
        """
    ).dropna()
    df['size'] = _classify_size(df['display_size_inch'])
    small = df.loc[df['size'] == 'small', 'weight'].to_numpy()
    large = df.loc[df['size'] == 'large', 'weight'].to_numpy()
    test = _t_or_mannwhitney(small, large)
    return _ht_response(
        name="Weight differs between small and large devices?",
        description="Two-sample test on body weight (g). Small = display <7\", large = ≥7\".",
        null_hypothesis="Mean body weight is the same in small and large devices.",
        alternative_hypothesis="Mean body weight differs between small and large devices.",
        test_block=test,
        groups=[
            {"size": "small", **_group_summary(small)},
            {"size": "large", **_group_summary(large)},
        ],
    )


# --- One-way ANOVAs (notebook cells 76, 78, 80) ---


@router.get("/ht-battery-by-cpu")
def ht_battery_by_cpu(form_factor: FormFactor = "phone") -> dict:
    """One-way ANOVA: battery_capacity_mah ~ cpu_core_count."""
    df = _df(
        f"""
        SELECT d.battery_capacity_mah AS battery, p.cpu_core_count
        FROM Device d
        JOIN Platform p ON p.id = d.platform_id
        WHERE {_form_filter(form_factor)} AND d.battery_capacity_mah IS NOT NULL
          AND p.cpu_core_count IS NOT NULL
        """
    ).dropna()
    anova = _anova_table('battery ~ C(cpu_core_count)', df)
    main = next((row for row in anova if 'cpu_core_count' in row['factor']), None)
    groups = [
        {"cpu_core_count": int(g), **_group_summary(sub['battery'].to_numpy())}
        for g, sub in df.groupby('cpu_core_count')
    ]
    return _ht_response(
        name="Battery capacity differs by CPU core count?",
        description="One-way ANOVA on battery_capacity_mah grouped by CPU core count.",
        null_hypothesis="Mean battery capacity is the same for every CPU core count.",
        alternative_hypothesis="At least one CPU-core-count group has a different mean battery capacity.",
        test_block={"test": "one-way ANOVA", "anova": anova,
                    "p_value": main["p_value"] if main else None},
        groups=groups,
    )


@router.get("/ht-price-by-chipset")
def ht_price_by_chipset(form_factor: FormFactor = "phone") -> dict:
    """One-way ANOVA: price ~ chipset_manufacturer."""
    df = _df(
        f"""
        SELECT d.price_eur AS price, p.chipset_manufacturer
        FROM Device d
        JOIN Platform p ON p.id = d.platform_id
        WHERE {_form_filter(form_factor)} AND d.price_eur IS NOT NULL
          AND p.chipset_manufacturer IS NOT NULL
        """
    ).dropna()
    anova = _anova_table('price ~ C(chipset_manufacturer)', df)
    main = next((row for row in anova if 'chipset_manufacturer' in row['factor']), None)
    groups = [
        {"chipset_manufacturer": str(g), **_group_summary(sub['price'].to_numpy())}
        for g, sub in df.groupby('chipset_manufacturer')
    ]
    return _ht_response(
        name="Price differs by chipset manufacturer?",
        description="One-way ANOVA on price grouped by chipset manufacturer (Qualcomm / Mediatek / Apple / Exynos / …).",
        null_hypothesis="Mean price is the same across all chipset manufacturers.",
        alternative_hypothesis="At least one chipset manufacturer has a different mean price.",
        test_block={"test": "one-way ANOVA", "anova": anova,
                    "p_value": main["p_value"] if main else None},
        groups=groups,
    )


@router.get("/ht-price-by-main-camera")
def ht_price_by_main_camera(form_factor: FormFactor = "phone") -> dict:
    """One-way ANOVA: price ~ main_cameras_num."""
    df = _df(
        f"""
        SELECT d.price_eur AS price, c.main_cameras_num
        FROM Device d
        JOIN Camera c ON c.id = d.camera_id
        WHERE {_form_filter(form_factor)} AND d.price_eur IS NOT NULL
          AND c.main_cameras_num IS NOT NULL
        """
    ).dropna()
    anova = _anova_table('price ~ C(main_cameras_num)', df)
    main = next((row for row in anova if 'main_cameras_num' in row['factor']), None)
    groups = [
        {"main_cameras_num": int(g), **_group_summary(sub['price'].to_numpy())}
        for g, sub in df.groupby('main_cameras_num')
    ]
    return _ht_response(
        name="Price differs by main-camera count?",
        description="One-way ANOVA on price grouped by the number of rear cameras.",
        null_hypothesis="Mean price is the same regardless of the number of rear cameras.",
        alternative_hypothesis="At least one main-camera count has a different mean price.",
        test_block={"test": "one-way ANOVA", "anova": anova,
                    "p_value": main["p_value"] if main else None},
        groups=groups,
    )


# ===========================================================================
# Section 4 — OLS regression models (notebook cells 18, 74)
# ===========================================================================


@router.get("/price-regression-specs")
def price_regression_specs(form_factor: FormFactor = "phone") -> dict:
    """OLS: price ~ battery + weight + display_size + resolution_pixels +
    screen_to_body_ratio + ppi_density. Mirrors notebook cell 74."""
    df = _df(
        f"""
        SELECT d.price_eur AS price,
               d.battery_capacity_mah AS battery_mah,
               d.weight,
               disp.display_size_inch,
               disp.resolution_pixels,
               disp.screen_to_body_ratio,
               disp.ppi_density
        FROM Device d
        JOIN Display disp ON disp.id = d.display_id
        WHERE {_form_filter(form_factor)} AND d.price_eur IS NOT NULL
        """
    )
    summary = _safe_ols_fit(
        df, response='price',
        numeric=['battery_mah', 'weight', 'display_size_inch',
                 'resolution_pixels', 'screen_to_body_ratio', 'ppi_density'],
        categorical=[],
    )
    return {
        "name": "Price ~ physical specs (multivariate OLS)",
        "description": (
            "Predict price (€) from numeric specs. "
            "Predictors that are entirely NaN for this form factor are dropped "
            "automatically (see `dropped_predictors`)."
        ),
        **summary,
    }


@router.get("/price-regression-os")
def price_regression_os(form_factor: FormFactor = "phone") -> dict:
    """OLS: price ~ OS dummies (one-hot, drop-first). Mirrors notebook cell 18."""
    df = _df(
        f"""
        SELECT d.price_eur AS price, o.os_name
        FROM Device d
        JOIN OS o ON o.id = d.os_id
        WHERE {_form_filter(form_factor)} AND d.price_eur IS NOT NULL AND o.os_name IS NOT NULL
        """
    ).dropna()
    summary = _ols_summary('price ~ C(os_name)', df)
    return {
        "name": "Price ~ OS (categorical OLS)",
        "description": (
            "Per-OS price intercept relative to the reference OS (alphabetically first, "
            "typically 'Android'). A positive coefficient means devices on that OS cost "
            "more than the reference, holding nothing else equal."
        ),
        **summary,
    }


def _full_model_data(form_factor: str) -> pd.DataFrame:
    """Pull the catalogue with every candidate predictor present.

    Shared by `/price-regression-full`, `/price-residuals`, and
    `/price-feature-selection`. Does NOT call `.dropna()` — when one
    predictor is entirely NaN for a form factor (e.g. screen_to_body_ratio
    on watches), a global dropna would delete every row. Callers must
    drop empty predictor columns first (see `_safe_ols_fit`).
    """
    return _df(
        f"""
        SELECT d.price_eur AS price,
               d.battery_capacity_mah AS battery_mah,
               d.weight, d.year,
               dn.brand,
               disp.display_size_inch,
               disp.resolution_pixels,
               disp.screen_to_body_ratio,
               disp.ppi_density,
               p.chipset_manufacturer,
               p.ram_gb,
               p.internal_storage_gb AS storage_gb,
               o.os_name
        FROM Device d
        JOIN Device_Name dn ON dn.id = d.device_name_id
        JOIN Display disp ON disp.id = d.display_id
        JOIN Platform p ON p.id = d.platform_id
        JOIN OS o ON o.id = d.os_id
        WHERE {_form_filter(form_factor)} AND d.price_eur IS NOT NULL
        """
    )


_RESIDUAL_PREDICTORS = {
    "specs": {
        "numeric": ['battery_mah', 'weight', 'display_size_inch',
                    'resolution_pixels', 'screen_to_body_ratio', 'ppi_density'],
        "categorical": [],
    },
    "full": {
        "numeric": ['battery_mah', 'weight', 'display_size_inch', 'resolution_pixels',
                    'screen_to_body_ratio', 'ram_gb', 'storage_gb', 'year'],
        "categorical": ['brand', 'chipset_manufacturer'],
    },
}


@router.get("/price-residuals")
def price_residuals(model: str = "full", form_factor: FormFactor = "phone") -> dict:
    """Residual diagnostics for the OLS price model.

    Pass `model=specs` to inspect the simpler numeric-only model, or `model=full`
    for the brand+chipset+year-augmented one. Predictors entirely NaN for the
    given form factor (e.g. `screen_to_body_ratio` for watches) are dropped
    automatically; the actual fitted formula is returned in `formula`.
    """
    if model not in _RESIDUAL_PREDICTORS:
        return {"error": f"unknown model '{model}'; expected one of {list(_RESIDUAL_PREDICTORS)}"}
    df = _full_model_data(form_factor)
    spec = _RESIDUAL_PREDICTORS[model]

    available_num = [c for c in spec['numeric'] if c in df.columns and df[c].notna().any()]
    available_cat = [c for c in spec['categorical'] if c in df.columns and df[c].notna().any()]
    dropped = [c for c in spec['numeric'] + spec['categorical']
               if c not in available_num + available_cat]
    keep = ['price'] + available_num + available_cat
    df_clean = df[keep].dropna()

    if not (available_num or available_cat) or len(df_clean) < 10:
        return {"error": f"insufficient data: {len(df_clean)} rows after dropping empty predictors",
                "model": model, "dropped_predictors": dropped, "n": len(df_clean)}

    terms = available_num + [f'C({c})' for c in available_cat]
    formula = f"price ~ " + ' + '.join(terms)
    try:
        fit = ols(formula, data=df_clean).fit()
    except (ValueError, np.linalg.LinAlgError) as exc:
        return {"error": str(exc), "model": model, "dropped_predictors": dropped}
    diagnostics = _residual_diagnostics(fit)
    return {"model": model, "formula": formula, "dropped_predictors": dropped,
            "r_squared": float(fit.rsquared),
            "adj_r_squared": float(fit.rsquared_adj), **diagnostics}


@router.get("/price-feature-selection")
def price_feature_selection(form_factor: FormFactor = "phone") -> dict:
    """Forward stepwise selection over numeric and categorical predictors.

    Candidates: 9 numerics (battery, weight, display_size, resolution_pixels,
    screen_to_body_ratio, ppi_density, ram_gb, storage_gb, year) plus three
    categoricals (brand, chipset_manufacturer, os_name). The procedure adds
    the feature that maximises adjusted R² at each step and stops when no
    candidate improves it. Returns the path plus the final model's
    coefficients.
    """
    df = _full_model_data(form_factor)
    candidates = [
        "battery_mah", "weight", "display_size_inch", "resolution_pixels",
        "screen_to_body_ratio", "ppi_density", "ram_gb", "storage_gb", "year",
        "C(brand)", "C(chipset_manufacturer)", "C(os_name)",
    ]
    return _forward_stepwise(df, "price", candidates)


@router.get("/price-regression-full")
def price_regression_full(form_factor: FormFactor = "phone") -> dict:
    """OLS with brand, chipset, year, RAM, storage + physical specs.

    The simpler `/price-regression-specs` model (R² ≈ 0.41) suffers from
    omitted-variable bias because brand / year / chipset are huge price
    drivers it cannot see. This endpoint adds them. `ppi_density` is
    intentionally dropped (perfectly collinear with resolution + size).
    Predictors entirely NaN for the given form factor are dropped
    automatically (see `dropped_predictors`).
    """
    df = _df(
        f"""
        SELECT d.price_eur AS price,
               d.battery_capacity_mah AS battery_mah,
               d.weight, d.year,
               dn.brand,
               disp.display_size_inch,
               disp.resolution_pixels,
               disp.screen_to_body_ratio,
               p.chipset_manufacturer,
               p.ram_gb,
               p.internal_storage_gb AS storage_gb
        FROM Device d
        JOIN Device_Name dn ON dn.id = d.device_name_id
        JOIN Display disp ON disp.id = d.display_id
        JOIN Platform p ON p.id = d.platform_id
        WHERE {_form_filter(form_factor)} AND d.price_eur IS NOT NULL
        """
    )
    summary = _safe_ols_fit(
        df, response='price',
        numeric=['battery_mah', 'weight', 'display_size_inch',
                 'resolution_pixels', 'screen_to_body_ratio',
                 'ram_gb', 'storage_gb', 'year'],
        categorical=['brand', 'chipset_manufacturer'],
    )
    return {
        "name": "Price ~ all predictors (full OLS)",
        "description": (
            "Multivariate OLS including brand, chipset manufacturer, year, RAM, storage, "
            "and physical specs. Brand and chipset enter as categoricals "
            "(reference = alphabetically first level). `ppi_density` is omitted "
            "because it's collinear with `resolution_pixels` and `display_size_inch`."
        ),
        **summary,
    }
