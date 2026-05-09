"""Integration tests for /api/analytics endpoints.

Each endpoint maps to a pre-built market-analytics query. Tests assert the
HTTP shape and that the result has the expected aggregation columns.
"""

from __future__ import annotations


class TestBrandSummary:
    def test_returns_list_of_dicts(self, client):
        r = client.get("/api/analytics/brand-summary")
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list)
        # Seed has 5 devices across 3 brands but HAVING COUNT >= 3 may filter;
        # the response shape is the contract being tested, not row count.
        for row in rows:
            assert {"brand", "device_count", "avg_price_eur", "first_year", "last_year"} <= set(row)


class TestAnnualLaunches:
    def test_year_grouping(self, client):
        r = client.get("/api/analytics/annual-launches")
        assert r.status_code == 200
        rows = r.json()
        years = [row["year"] for row in rows]
        # Must be ascending and unique
        assert years == sorted(set(years))

    def test_left_join_counts_null_platform_devices(self, client):
        """The 2024 row must include id=7 (NULL platform_id) because the route
        LEFT-joins to Platform. Under old INNER JOIN id=7 would be filtered out."""
        rows = client.get("/api/analytics/annual-launches").json()
        year_2024 = next((row for row in rows if row["year"] == 2024), None)
        assert year_2024 is not None
        # Seed: id=2,3,5 (phones) + id=6 (watch) + id=7 (NULL platform) = 5 launches in 2024
        assert year_2024["launches"] == 5


class TestChipsetPopularity:
    def test_returns_chipset_rows(self, client):
        r = client.get("/api/analytics/chipset-popularity")
        assert r.status_code == 200
        rows = r.json()
        names = [row["chipset_manufacturer"] for row in rows]
        assert "Apple" in names or "Qualcomm" in names or "Mediatek" in names

    def test_sorted_descending_by_count(self, client):
        rows = client.get("/api/analytics/chipset-popularity").json()
        counts = [row["device_count"] for row in rows]
        assert counts == sorted(counts, reverse=True)


class TestPriceVsBattery:
    def test_returns_per_device_rows(self, client):
        r = client.get("/api/analytics/price-vs-battery")
        assert r.status_code == 200
        rows = r.json()
        # Excludes price-NULL rows by query construction
        assert all(row["price_eur"] is not None for row in rows)
        assert all(row["battery_mah"] is not None for row in rows)


class TestRamDistribution:
    def test_ascending_by_ram(self, client):
        r = client.get("/api/analytics/ram-distribution")
        assert r.status_code == 200
        rows = r.json()
        rams = [row["ram_gb"] for row in rows]
        assert rams == sorted(rams)


# ---------------------------------------------------------------------------
# Section 2 — Distribution / ranking / trend endpoints (notebook Q1-Q8)
# ---------------------------------------------------------------------------


class TestNetworkTechnology:
    def test_returns_four_generations(self, client):
        r = client.get("/api/analytics/network-technology")
        assert r.status_code == 200
        rows = r.json()
        labels = [row["generation"] for row in rows]
        assert labels == ["2G", "3G", "4G", "5G"]
        for row in rows:
            assert {"generation", "device_count", "pct"} <= set(row)
            assert 0 <= row["pct"] <= 100

    def test_5g_count_includes_seed_phones(self, client):
        # Seed: ids 1,2,3,5,7 use '... / 5G' tech (5 phones); id=4 uses non-5G
        rows = client.get("/api/analytics/network-technology").json()
        gen_5g = next(row for row in rows if row["generation"] == "5G")
        assert gen_5g["device_count"] == 5


class TestSimTypeDistribution:
    def test_returns_phone_sim_types(self, client):
        r = client.get("/api/analytics/sim-type-distribution")
        assert r.status_code == 200
        rows = r.json()
        for row in rows:
            assert {"sim_type", "device_count"} <= set(row)
        sim_types = {row["sim_type"] for row in rows}
        # Seed phones: nano (id=2,3,4,7), esim (id=1,5)
        assert {"nano", "esim"} <= sim_types


class TestTopAndroidVersions:
    def test_returns_versions(self, client):
        r = client.get("/api/analytics/top-android-versions")
        assert r.status_code == 200
        rows = r.json()
        for row in rows:
            assert {"os_version", "device_count"} <= set(row)
        # Seed Android phones: id=2,3,4,7 with version "14"
        assert any(row["os_version"] == "14" for row in rows)

    def test_limit_respected(self, client):
        r = client.get("/api/analytics/top-android-versions?limit=1")
        assert r.status_code == 200
        assert len(r.json()) <= 1


class TestTopExpensivePhones:
    def test_returns_expensive_first(self, client):
        r = client.get("/api/analytics/top-expensive-phones?limit=10")
        assert r.status_code == 200
        rows = r.json()
        prices = [row["price_eur"] for row in rows]
        assert prices == sorted(prices, reverse=True)
        # Watch (id=6, 449) must NOT appear — endpoint filters form_factor='phone'.
        assert all(row["price_eur"] != 449.0 for row in rows)

    def test_excludes_null_price(self, client):
        rows = client.get("/api/analytics/top-expensive-phones").json()
        # Seed id=4 has NULL price; it must not appear.
        assert all(row["price_eur"] is not None for row in rows)


class TestPpiTrend:
    def test_only_three_brands(self, client):
        rows = client.get("/api/analytics/ppi-trend").json()
        brands = {row["brand"] for row in rows}
        assert brands <= {"Samsung", "Xiaomi", "Apple"}

    def test_sorted_by_year_then_brand(self, client):
        rows = client.get("/api/analytics/ppi-trend").json()
        keys = [(row["year"], row["brand"]) for row in rows]
        assert keys == sorted(keys)


class TestCorrelationMatrix:
    def test_square_matrix(self, client):
        r = client.get("/api/analytics/correlation-matrix")
        assert r.status_code == 200
        body = r.json()
        n = len(body["columns"])
        assert n > 0
        assert len(body["matrix"]) == n
        for row in body["matrix"]:
            assert len(row) == n

    def test_diagonal_is_one(self, client):
        body = client.get("/api/analytics/correlation-matrix").json()
        for i in range(len(body["columns"])):
            diag = body["matrix"][i][i]
            # NaN if column was all-null in seed; otherwise 1.0
            assert diag is None or abs(diag - 1.0) < 1e-9


class TestQuantitativeDistributions:
    def test_returns_dict_of_lists(self, client):
        r = client.get("/api/analytics/quantitative-distributions")
        assert r.status_code == 200
        body = r.json()
        assert "weight" in body and "ppi_density" in body
        for key, values in body.items():
            assert isinstance(values, list)
            assert all(v is None or isinstance(v, (int, float)) for v in values)


# ---------------------------------------------------------------------------
# Section 3 — Inferential stats (notebook Estimation + HT1-HT6)
# ---------------------------------------------------------------------------


class TestPriceCi2023:
    def test_returns_one_row_per_brand(self, client):
        r = client.get("/api/analytics/price-ci-2023")
        assert r.status_code == 200
        rows = r.json()
        brands = [row["brand"] for row in rows]
        assert brands == ["Apple", "Samsung", "Huawei", "Xiaomi", "Nokia"]
        for row in rows:
            assert {"brand", "n", "mean", "std", "lower", "upper", "alpha"} <= set(row)

    def test_lower_under_upper_when_data_present(self, client):
        rows = client.get("/api/analytics/price-ci-2023").json()
        for row in rows:
            if row["n"] >= 2:
                assert row["lower"] <= row["mean"] <= row["upper"]


def _assert_ht_envelope(body: dict) -> None:
    """All HT endpoints share this envelope."""
    assert {"name", "description", "test", "alpha", "conclusion", "groups"} <= set(body)
    assert isinstance(body["groups"], list)
    for group in body["groups"]:
        assert {"n", "mean", "std", "values"} <= set(group)


class TestHypothesisTests:
    def test_ht_price_by_sim_and_size(self, client):
        r = client.get("/api/analytics/ht-price-by-sim-and-size")
        assert r.status_code == 200
        body = r.json()
        _assert_ht_envelope(body)
        assert body["test"] == "two-way ANOVA"
        assert "anova" in body
        assert isinstance(body["anova"], list)

    def test_ht_ppi_by_size(self, client):
        r = client.get("/api/analytics/ht-ppi-by-size")
        assert r.status_code == 200
        body = r.json()
        _assert_ht_envelope(body)
        assert body["test"] in ("Welch t-test", "Mann-Whitney U", "insufficient_data")

    def test_ht_weight_android_vs_ios(self, client):
        r = client.get("/api/analytics/ht-weight-android-vs-ios")
        assert r.status_code == 200
        _assert_ht_envelope(r.json())

    def test_ht_battery_by_brand_and_size(self, client):
        r = client.get("/api/analytics/ht-battery-by-brand-and-size")
        assert r.status_code == 200
        body = r.json()
        _assert_ht_envelope(body)
        assert body["test"] == "two-way ANOVA"

    def test_ht_price_by_brand_and_size(self, client):
        r = client.get("/api/analytics/ht-price-by-brand-and-size")
        assert r.status_code == 200
        body = r.json()
        _assert_ht_envelope(body)
        assert body["test"] == "two-way ANOVA"

    def test_ht_weight_by_size(self, client):
        r = client.get("/api/analytics/ht-weight-by-size")
        assert r.status_code == 200
        _assert_ht_envelope(r.json())

    def test_ht_p_values_in_range(self, client):
        """Every HT endpoint either reports insufficient_data or a p-value in [0,1]."""
        urls = [
            "/api/analytics/ht-price-by-sim-and-size",
            "/api/analytics/ht-ppi-by-size",
            "/api/analytics/ht-weight-android-vs-ios",
            "/api/analytics/ht-battery-by-brand-and-size",
            "/api/analytics/ht-price-by-brand-and-size",
            "/api/analytics/ht-weight-by-size",
            "/api/analytics/ht-battery-by-cpu",
            "/api/analytics/ht-price-by-chipset",
            "/api/analytics/ht-price-by-main-camera",
        ]
        for url in urls:
            body = client.get(url).json()
            p = body.get("p_value")
            assert p is None or (0.0 <= p <= 1.0), f"{url}: p_value out of range"


class TestOneWayAnovas:
    """Notebook cells 76, 78, 80 — three additional one-way ANOVAs."""

    def test_ht_battery_by_cpu(self, client):
        r = client.get("/api/analytics/ht-battery-by-cpu")
        assert r.status_code == 200
        body = r.json()
        _assert_ht_envelope(body)
        assert body["test"] == "one-way ANOVA"

    def test_ht_price_by_chipset(self, client):
        r = client.get("/api/analytics/ht-price-by-chipset")
        assert r.status_code == 200
        body = r.json()
        _assert_ht_envelope(body)
        assert body["test"] == "one-way ANOVA"

    def test_ht_price_by_main_camera(self, client):
        r = client.get("/api/analytics/ht-price-by-main-camera")
        assert r.status_code == 200
        body = r.json()
        _assert_ht_envelope(body)
        assert body["test"] == "one-way ANOVA"


class TestOlsRegressions:
    """Notebook cells 18, 74 — multivariate / categorical OLS."""

    def _assert_ols_envelope(self, body):
        assert {"name", "description", "n", "r_squared", "coefficients"} <= set(body) or "error" in body
        if "error" in body:
            return  # degenerate seed — that's a valid response
        assert isinstance(body["coefficients"], list)
        if body["r_squared"] is not None:
            assert -0.01 <= body["r_squared"] <= 1.0
        for coef in body["coefficients"]:
            assert {"name", "coef", "std_err", "t", "p_value"} <= set(coef)
            if coef["p_value"] is not None:
                assert 0.0 <= coef["p_value"] <= 1.0

    def test_price_regression_specs(self, client):
        r = client.get("/api/analytics/price-regression-specs")
        assert r.status_code == 200
        self._assert_ols_envelope(r.json())

    def test_price_regression_os(self, client):
        r = client.get("/api/analytics/price-regression-os")
        assert r.status_code == 200
        self._assert_ols_envelope(r.json())
