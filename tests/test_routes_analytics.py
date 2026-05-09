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
