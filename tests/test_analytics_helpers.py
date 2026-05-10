"""Direct unit tests for the analytics helper functions.

The endpoint-level tests in test_routes_analytics.py cover the integration
shape but exercise the helpers only through whatever paths the seed/live
data happens to hit. These tests deliberately drive each branch.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.routes.analytics import (
    _anova_table,
    _classify_size,
    _conclusion,
    _forward_stepwise,
    _group_summary,
    _ols_summary,
    _residual_diagnostics,
    _t_or_mannwhitney,
)


# ---------------------------------------------------------------------------
# _classify_size
# ---------------------------------------------------------------------------


class TestClassifySize:
    def test_below_seven_is_small(self):
        s = pd.Series([3.5, 6.1, 6.9, 6.99])
        assert list(_classify_size(s)) == ["small", "small", "small", "small"]

    def test_seven_and_above_is_large(self):
        s = pd.Series([7.0, 8.0, 11.0])
        assert list(_classify_size(s)) == ["large", "large", "large"]

    def test_boundary_seven_is_large(self):
        s = pd.Series([7.0])
        assert list(_classify_size(s)) == ["large"]


# ---------------------------------------------------------------------------
# _group_summary
# ---------------------------------------------------------------------------


class TestGroupSummary:
    def test_empty(self):
        out = _group_summary(np.array([]))
        assert out["n"] == 0
        assert out["mean"] is None
        assert out["std"] is None
        assert out["values"] == []

    def test_single_value(self):
        out = _group_summary(np.array([42.0]))
        assert out["n"] == 1
        assert out["mean"] == pytest.approx(42.0)
        # std with ddof=1 is undefined for n=1
        assert out["std"] is None
        assert out["median"] == pytest.approx(42.0)

    def test_multi_value_has_full_stats(self):
        out = _group_summary(np.array([1.0, 2.0, 3.0, 4.0, 5.0]))
        assert out["n"] == 5
        assert out["mean"] == pytest.approx(3.0)
        assert out["std"] == pytest.approx(np.std([1, 2, 3, 4, 5], ddof=1))
        assert out["median"] == pytest.approx(3.0)
        assert out["values"] == [1.0, 2.0, 3.0, 4.0, 5.0]


# ---------------------------------------------------------------------------
# _conclusion
# ---------------------------------------------------------------------------


class TestConclusion:
    def test_significant(self):
        assert _conclusion(0.01) == "reject H0 at α=0.05"

    def test_not_significant(self):
        assert _conclusion(0.5) == "fail to reject H0 at α=0.05"

    def test_at_boundary(self):
        # exactly 0.05 → fail to reject (uses < not <=)
        assert _conclusion(0.05) == "fail to reject H0 at α=0.05"

    def test_none_pvalue_returns_insufficient(self):
        assert _conclusion(None) == "insufficient data"

    def test_custom_alpha(self):
        assert _conclusion(0.03, alpha=0.01) == "fail to reject H0 at α=0.01"
        assert _conclusion(0.005, alpha=0.01) == "reject H0 at α=0.01"


# ---------------------------------------------------------------------------
# _t_or_mannwhitney
# ---------------------------------------------------------------------------


class TestTOrMannWhitney:
    def test_insufficient_data_when_group_too_small(self):
        out = _t_or_mannwhitney(np.array([1.0, 2.0]), np.array([1.0, 2.0, 3.0]))
        assert out["test"] == "insufficient_data"
        assert out["p_value"] is None

    def test_picks_t_test_for_normal_data(self):
        rng = np.random.default_rng(42)
        a = rng.normal(loc=0, scale=1, size=200)
        b = rng.normal(loc=0.3, scale=1, size=200)
        out = _t_or_mannwhitney(a, b)
        # Both groups passed Shapiro at p>0.05 most likely → Welch t-test.
        assert out["test"] == "Welch t-test"
        assert 0.0 <= out["p_value"] <= 1.0

    def test_picks_mann_whitney_for_skewed_data(self):
        rng = np.random.default_rng(42)
        # Exponential — not normal → Shapiro-Wilk rejects → fall through to U.
        a = rng.exponential(scale=1.0, size=200)
        b = rng.exponential(scale=1.5, size=200)
        out = _t_or_mannwhitney(a, b)
        assert out["test"] == "Mann-Whitney U"
        assert 0.0 <= out["p_value"] <= 1.0

    def test_returned_p_value_is_float(self):
        rng = np.random.default_rng(0)
        a = rng.normal(0, 1, 100)
        b = rng.normal(0, 1, 100)
        out = _t_or_mannwhitney(a, b)
        assert isinstance(out["p_value"], float)
        assert isinstance(out["statistic"], float)


# ---------------------------------------------------------------------------
# _anova_table
# ---------------------------------------------------------------------------


class TestAnovaTable:
    def test_valid_one_way(self):
        rng = np.random.default_rng(0)
        df = pd.DataFrame({
            "y": np.concatenate([rng.normal(0, 1, 50), rng.normal(2, 1, 50), rng.normal(4, 1, 50)]),
            "g": ["a"] * 50 + ["b"] * 50 + ["c"] * 50,
        })
        rows = _anova_table("y ~ C(g)", df)
        # Should have at least the factor row + Residual row
        assert len(rows) >= 1
        # Each row has the contract fields
        for row in rows:
            assert {"factor", "sum_sq", "df", "F", "p_value"} <= set(row)
        # The C(g) factor should be highly significant (means differ a lot)
        factor_row = next(r for r in rows if "g" in r["factor"])
        assert factor_row["p_value"] is not None
        assert factor_row["p_value"] < 0.001

    def test_degenerate_returns_empty(self):
        # Single factor level → constraint matrix has zero rows → ValueError
        df = pd.DataFrame({"y": [1.0, 2.0, 3.0], "g": ["only", "only", "only"]})
        rows = _anova_table("y ~ C(g)", df)
        assert rows == []


# ---------------------------------------------------------------------------
# _ols_summary
# ---------------------------------------------------------------------------


class TestOlsSummary:
    def test_valid_simple_regression(self):
        rng = np.random.default_rng(0)
        x = rng.normal(0, 1, 200)
        df = pd.DataFrame({"y": 2.0 + 3.0 * x + rng.normal(0, 0.5, 200), "x": x})
        out = _ols_summary("y ~ x", df)
        assert out["n"] == 200
        # Slope should be ~3, intercept ~2
        coefs = {c["name"]: c["coef"] for c in out["coefficients"]}
        assert abs(coefs["x"] - 3.0) < 0.2
        assert abs(coefs["Intercept"] - 2.0) < 0.2
        # Strong fit → high R²
        assert out["r_squared"] > 0.95
        # Each coefficient row has the contract
        for c in out["coefficients"]:
            assert {"name", "coef", "std_err", "t", "p_value"} <= set(c)
            if c["p_value"] is not None:
                assert 0.0 <= c["p_value"] <= 1.0

    def test_degenerate_returns_error(self):
        # No variation in x → singular design matrix
        df = pd.DataFrame({"y": [1.0, 2.0, 3.0], "x": [5.0, 5.0, 5.0]})
        out = _ols_summary("y ~ x", df)
        # Either errors out gracefully or returns a valid (rank-deficient) summary;
        # the contract is that we don't raise.
        assert "n" in out


# ---------------------------------------------------------------------------
# _residual_diagnostics
# ---------------------------------------------------------------------------


class TestResidualDiagnostics:
    @pytest.fixture
    def fitted_model(self):
        from statsmodels.formula.api import ols
        rng = np.random.default_rng(0)
        x = rng.normal(0, 1, 300)
        df = pd.DataFrame({"y": 1.0 + 2.0 * x + rng.normal(0, 1, 300), "x": x})
        return ols("y ~ x", data=df).fit()

    def test_envelope_shape(self, fitted_model):
        out = _residual_diagnostics(fitted_model, max_points=50)
        assert {"n", "mean_residual", "std_residual", "sample_residuals",
                "qq_plot", "breusch_pagan", "jarque_bera", "vif",
                "top_cooks_d", "n_outliers_z3"} <= set(out)
        assert out["n"] == 300

    def test_qq_plot_shape(self, fitted_model):
        out = _residual_diagnostics(fitted_model, max_points=50)
        assert len(out["qq_plot"]) <= 300
        for p in out["qq_plot"]:
            assert {"theoretical", "sample"} == set(p)

    def test_sample_size_capped(self, fitted_model):
        out = _residual_diagnostics(fitted_model, max_points=50)
        assert len(out["sample_residuals"]) == 50

    def test_breusch_pagan_pvalue_in_range(self, fitted_model):
        out = _residual_diagnostics(fitted_model)
        bp = out["breusch_pagan"]
        if bp["p_value"] is not None:
            assert 0.0 <= bp["p_value"] <= 1.0

    def test_jarque_bera_pvalue_in_range(self, fitted_model):
        out = _residual_diagnostics(fitted_model)
        jb = out["jarque_bera"]
        if jb["p_value"] is not None:
            assert 0.0 <= jb["p_value"] <= 1.0

    def test_vif_at_least_one(self, fitted_model):
        out = _residual_diagnostics(fitted_model)
        for v in out["vif"]:
            if v["vif"] is not None:
                # VIF >= 1 by definition (allow tiny float slack)
                assert v["vif"] >= 0.99

    def test_outlier_count_non_negative(self, fitted_model):
        out = _residual_diagnostics(fitted_model)
        assert out["n_outliers_z3"] >= 0
        assert out["n_outliers_z3"] <= out["n"]


# ---------------------------------------------------------------------------
# _forward_stepwise
# ---------------------------------------------------------------------------


class TestForwardStepwise:
    def test_picks_predictive_features_first(self):
        rng = np.random.default_rng(0)
        n = 500
        x_strong = rng.normal(0, 1, n)
        x_weak = rng.normal(0, 1, n)
        x_noise = rng.normal(0, 1, n)
        df = pd.DataFrame({
            "y": 5 * x_strong + 0.2 * x_weak + rng.normal(0, 1, n),
            "x_strong": x_strong,
            "x_weak": x_weak,
            "x_noise": x_noise,
        })
        out = _forward_stepwise(df, "y", ["x_strong", "x_weak", "x_noise"])
        assert "history" in out
        # First selected feature should be x_strong (highest contribution)
        assert out["history"][0]["added"] == "x_strong"

    def test_history_is_monotone_in_adj_r_squared(self):
        rng = np.random.default_rng(1)
        df = pd.DataFrame({
            "y": rng.normal(0, 1, 200),
            "a": rng.normal(0, 1, 200),
            "b": rng.normal(0, 1, 200),
            "c": rng.normal(0, 1, 200),
        })
        out = _forward_stepwise(df, "y", ["a", "b", "c"])
        if len(out["history"]) >= 2:
            prev = out["history"][0]["adj_r_squared"]
            for step in out["history"][1:]:
                assert step["adj_r_squared"] >= prev - 1e-9
                prev = step["adj_r_squared"]

    def test_final_summary_when_features_were_added(self):
        rng = np.random.default_rng(2)
        x = rng.normal(0, 1, 200)
        df = pd.DataFrame({"y": 3 * x + rng.normal(0, 0.5, 200), "x": x})
        out = _forward_stepwise(df, "y", ["x"])
        assert out["final_features"] == ["x"]
        assert out["final_formula"] == "y ~ x"
        assert "coefficients" in out["final_summary"]

    def test_no_useful_features_returns_history(self):
        # Pure noise predictors. The algorithm may or may not pick something
        # by chance — what we care about is that it returns gracefully.
        rng = np.random.default_rng(3)
        df = pd.DataFrame({
            "y": rng.normal(0, 1, 100),
            "a": rng.normal(0, 1, 100),
            "b": rng.normal(0, 1, 100),
        })
        out = _forward_stepwise(df, "y", ["a", "b"])
        assert "history" in out
