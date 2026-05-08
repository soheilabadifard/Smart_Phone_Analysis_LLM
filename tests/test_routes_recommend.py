"""Integration tests for /api/recommend.

Uses the FastAPI TestClient with the DB pointed at the seeded SQLite engine
(see conftest.py::populated_engine). Each test asserts both the HTTP shape
and the actual filtering / sorting behavior.
"""

from __future__ import annotations


class TestRecommendList:
    def test_brands_endpoint(self, client):
        r = client.get("/api/recommend/brands")
        assert r.status_code == 200
        brands = r.json()
        assert {"Apple", "Samsung", "Xiaomi"}.issubset(set(brands))

    def test_os_endpoint(self, client):
        r = client.get("/api/recommend/os")
        assert r.status_code == 200
        os_list = r.json()
        assert "iOS" in os_list
        assert "Android" in os_list


class TestRecommendQuery:
    def test_no_filters_returns_devices(self, client):
        r = client.post("/api/recommend", json={})
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) >= 1
        # At least one phone has a price (the NULL filter excludes id=4)
        assert all(r_["price_eur"] is not None for r_ in rows)

    def test_max_price_filter(self, client):
        r = client.post("/api/recommend", json={"max_price_eur": 300})
        assert r.status_code == 200
        rows = r.json()
        assert all(row["price_eur"] <= 300 for row in rows)
        assert any(row["brand"] == "Xiaomi" for row in rows)

    def test_brands_filter_uses_in_clause(self, client):
        # This is the regression test for the `IN :brands` expanding bug.
        r = client.post("/api/recommend", json={"brands": ["Apple"]})
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) >= 1
        assert all(row["brand"] == "Apple" for row in rows)

    def test_brands_multi_select(self, client):
        r = client.post("/api/recommend", json={"brands": ["Apple", "Xiaomi"]})
        assert r.status_code == 200
        rows = r.json()
        assert {row["brand"] for row in rows} <= {"Apple", "Xiaomi"}

    def test_min_ram_filter(self, client):
        r = client.post("/api/recommend", json={"min_ram_gb": 12})
        assert r.status_code == 200
        rows = r.json()
        assert all(row["ram_gb"] >= 12 for row in rows)

    def test_5g_filter(self, client):
        r = client.post("/api/recommend", json={"require_5g": True})
        assert r.status_code == 200
        rows = r.json()
        assert all("5G" in row["network"] for row in rows)

    def test_sort_by_price_ascending_excludes_nulls(self, client):
        # Regression for the NULL-first sort bug — id=4 has price_eur = NULL
        # and should NOT appear at the top.
        r = client.post("/api/recommend", json={"sort_by": "price", "sort_order": "asc"})
        assert r.status_code == 200
        rows = r.json()
        prices = [row["price_eur"] for row in rows]
        assert None not in prices
        assert prices == sorted(prices)

    def test_sort_by_battery_descending(self, client):
        r = client.post(
            "/api/recommend", json={"sort_by": "battery", "sort_order": "desc"}
        )
        assert r.status_code == 200
        battery = [row["battery_mah"] for row in r.json()]
        assert battery == sorted(battery, reverse=True)

    def test_limit_respected(self, client):
        r = client.post("/api/recommend", json={"limit": 1})
        assert r.status_code == 200
        assert len(r.json()) == 1

    def test_invalid_sort_returns_422(self, client):
        r = client.post("/api/recommend", json={"sort_by": "haxor"})
        assert r.status_code == 422  # Pydantic Literal validation

    def test_default_form_factor_excludes_non_phones(self, client):
        # Seed has 5 phones (one with NULL price) + 1 watch. Default
        # form_factor='phone' + NULL-price filter → 4 phone rows.
        r = client.post(
            "/api/recommend", json={"sort_by": "price", "sort_order": "asc"}
        )
        assert r.status_code == 200
        rows = r.json()
        # The watch (price 449) sits between id=3 (249) and id=1 (799). If
        # the form_factor filter is broken, it would appear in the result.
        prices = [row["price_eur"] for row in rows]
        assert 449.0 not in prices

    def test_form_factor_watch_returns_only_watches(self, client):
        r = client.post("/api/recommend", json={"form_factor": "watch"})
        assert r.status_code == 200
        rows = r.json()
        # Seed has exactly one watch (price 449)
        assert len(rows) == 1
        assert rows[0]["price_eur"] == 449.0

    def test_form_factor_any_includes_watches_and_phones(self, client):
        r = client.post(
            "/api/recommend",
            json={"form_factor": "any", "sort_by": "price", "sort_order": "asc"},
        )
        assert r.status_code == 200
        rows = r.json()
        # 4 phones with prices + 1 watch = 5 (id=4 still excluded for NULL price)
        assert len(rows) == 5
        assert 449.0 in [row["price_eur"] for row in rows]

    def test_form_factor_invalid_returns_422(self, client):
        r = client.post("/api/recommend", json={"form_factor": "spaceship"})
        assert r.status_code == 422
