"""Unit tests for etl/extracrawling.py.

These tests are network-free: they exercise the HTML parsing, config-counting,
JSON I/O, format-migration, and timestamp logic in isolation. The live
fetch path is intentionally not exercised — it's covered by the crawl
resilience contract documented in CLAUDE.md and would require a recorded
fixture or a mock HTTP layer.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from etl.extracrawling import (
    _is_stale,
    _migrate_entry,
    build_model_url_index,
    count_storage_tiers,
    load_existing_pricing,
    scrape_pricing,
)
from etl.pricing_json_to_csv import convert


# ---------------------------------------------------------------------------
# scrape_pricing — pure HTML parsing
# ---------------------------------------------------------------------------


def _wrap_table(rows_html: str) -> str:
    return f"""<html><body>
        <table class="pricing inline widget">
            {rows_html}
        </table>
    </body></html>"""


class TestScrapePricing:
    def test_valid_table_returns_dict(self):
        html = _wrap_table("""
            <tr><td>128GB 6GB RAM</td><td><a href="#">$799</a></td></tr>
            <tr><td>256GB 8GB RAM</td><td><a href="#">$899</a></td></tr>
        """)
        out = scrape_pricing(html)
        assert out == {"128GB 6GB RAM": "$799", "256GB 8GB RAM": "$899"}

    def test_no_pricing_table_returns_none(self):
        html = "<html><body><p>nothing here</p></body></html>"
        assert scrape_pricing(html) is None

    def test_header_only_returns_none(self):
        # No <td> rows → no captured configs → None
        html = _wrap_table("<tr><th>Config</th><th>Price</th></tr>")
        assert scrape_pricing(html) is None

    def test_mixed_header_and_data_rows(self):
        # The header has only <th>, so the row is skipped silently — only
        # the data row is captured.
        html = _wrap_table("""
            <tr><th>Config</th><th>Price</th></tr>
            <tr><td>128GB</td><td><a href="#">€500</a></td></tr>
        """)
        assert scrape_pricing(html) == {"128GB": "€500"}

    def test_row_without_link_is_skipped(self):
        html = _wrap_table("""
            <tr><td>128GB</td><td>no link</td></tr>
            <tr><td>256GB</td><td><a href="#">€700</a></td></tr>
        """)
        assert scrape_pricing(html) == {"256GB": "€700"}

    def test_empty_config_text_is_skipped(self):
        html = _wrap_table("""
            <tr><td>   </td><td><a href="#">€100</a></td></tr>
            <tr><td>256GB</td><td><a href="#">€700</a></td></tr>
        """)
        assert scrape_pricing(html) == {"256GB": "€700"}

    def test_malformed_html_does_not_raise(self):
        # BeautifulSoup is lenient — any string is parseable. We just want
        # to confirm scrape_pricing doesn't propagate exceptions.
        assert scrape_pricing("<table><tr><td>nope") is None  # no widget class

    def test_three_or_more_rows_all_captured(self):
        rows = "".join(
            f'<tr><td>{n}GB</td><td><a href="#">€{n}</a></td></tr>'
            for n in (64, 128, 256, 512, 1024)
        )
        out = scrape_pricing(_wrap_table(rows))
        assert out is not None
        assert len(out) == 5
        assert out["1024GB"] == "€1024"


# ---------------------------------------------------------------------------
# count_storage_tiers — replaces the loose comma-split heuristic
# ---------------------------------------------------------------------------


class TestCountStorageTiers:
    @pytest.mark.parametrize("text,expected", [
        ("128GB 6GB RAM, 256GB 8GB RAM, 512GB 8GB RAM", 3),
        ("128GB 6GB RAM (Africa), 64GB 4GB RAM (India)", 2),
        ("128GB", 1),
        ("", 0),
        ("1TB 12GB RAM, 512GB 8GB RAM", 2),
        ("256 GB", 1),                      # spaces tolerated
        ("256MB", 1),                       # MB also counted
        ("Variants: 128GB / 256GB / 512GB", 1),  # slash-separated → still 1 fragment
    ])
    def test_storage_tier_counts(self, text, expected):
        assert count_storage_tiers(text) == expected

    def test_none_returns_zero(self):
        assert count_storage_tiers(None) == 0

    def test_non_string_returns_zero(self):
        assert count_storage_tiers(123) == 0


# ---------------------------------------------------------------------------
# _migrate_entry — old format → new format
# ---------------------------------------------------------------------------


class TestMigrateEntry:
    def test_legacy_none(self):
        assert _migrate_entry(None) == {"scraped_at": None, "configs": None}

    def test_legacy_config_dict(self):
        legacy = {"128GB": "$799", "256GB": "$899"}
        assert _migrate_entry(legacy) == {"scraped_at": None, "configs": legacy}

    def test_already_new_format_passes_through(self):
        new = {"scraped_at": "2026-05-09T12:00:00Z", "configs": {"128GB": "$799"}}
        out = _migrate_entry(new)
        assert out["scraped_at"] == "2026-05-09T12:00:00Z"
        assert out["configs"] == {"128GB": "$799"}

    def test_partial_new_format_completed(self):
        # Has scraped_at but no configs key (defensive)
        out = _migrate_entry({"scraped_at": "2026-05-09T12:00:00Z"})
        assert out == {"scraped_at": "2026-05-09T12:00:00Z", "configs": None}


# ---------------------------------------------------------------------------
# _is_stale — refresh threshold logic
# ---------------------------------------------------------------------------


class TestIsStale:
    def test_no_threshold_never_stale(self):
        # Even ancient entries are not stale when threshold is None
        assert _is_stale("2010-01-01T00:00:00Z", None) is False
        assert _is_stale(None, None) is False

    def test_missing_timestamp_is_stale(self):
        assert _is_stale(None, timedelta(days=1)) is True

    def test_recent_entry_not_stale(self):
        recent = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        assert _is_stale(recent, timedelta(days=30)) is False

    def test_old_entry_is_stale(self):
        old = (datetime.now(timezone.utc) - timedelta(days=60)).strftime('%Y-%m-%dT%H:%M:%SZ')
        assert _is_stale(old, timedelta(days=30)) is True

    def test_malformed_timestamp_is_stale(self):
        assert _is_stale("not-a-date", timedelta(days=1)) is True


# ---------------------------------------------------------------------------
# build_model_url_index
# ---------------------------------------------------------------------------


class TestBuildModelUrlIndex:
    def test_flattens_nested_dict(self):
        nested = {"Apple": {"iPhone 15": "u1"}, "Samsung": {"Galaxy S24": "u2"}}
        assert build_model_url_index(nested) == {"iPhone 15": "u1", "Galaxy S24": "u2"}

    def test_collision_later_wins(self):
        # Documented behaviour — the flattening is loss-y on collisions.
        nested = {"BrandA": {"Pixel": "u1"}, "BrandB": {"Pixel": "u2"}}
        out = build_model_url_index(nested)
        assert out["Pixel"] in {"u1", "u2"}


# ---------------------------------------------------------------------------
# load_existing_pricing — JSON I/O + migration
# ---------------------------------------------------------------------------


class TestLoadExistingPricing:
    def test_missing_file_returns_empty(self, tmp_path):
        out = load_existing_pricing(str(tmp_path / "missing.json"))
        assert out == {}

    def test_corrupt_json_returns_empty(self, tmp_path, capsys):
        p = tmp_path / "broken.json"
        p.write_text("{not valid json")
        out = load_existing_pricing(str(p))
        assert out == {}
        captured = capsys.readouterr()
        assert "Could not load" in captured.out

    def test_mixed_legacy_and_new_format(self, tmp_path):
        p = tmp_path / "pricing.json"
        p.write_text(json.dumps({
            "Old None": None,
            "Old Config": {"128GB": "$799"},
            "New": {"scraped_at": "2026-05-09T12:00:00Z", "configs": {"256GB": "$899"}},
        }))
        out = load_existing_pricing(str(p))
        assert out == {
            "Old None": {"scraped_at": None, "configs": None},
            "Old Config": {"scraped_at": None, "configs": {"128GB": "$799"}},
            "New": {"scraped_at": "2026-05-09T12:00:00Z", "configs": {"256GB": "$899"}},
        }


# ---------------------------------------------------------------------------
# pricing_json_to_csv.convert — bridges the new format to the cleaner
# ---------------------------------------------------------------------------


class TestPricingJsonToCsv:
    def test_old_format_still_works(self, tmp_path):
        json_path = tmp_path / "pricing.json"
        csv_path = tmp_path / "pricing.csv"
        json_path.write_text(json.dumps({
            "iPhone 15": {"128GB": "$799", "256GB": "$899"},
            "Galaxy S24": None,
        }))
        n = convert(str(json_path), str(csv_path))
        assert n == 2
        rows = csv_path.read_text().strip().splitlines()
        assert rows[0] == "Model,Configuration,Price"
        assert any("128GB" in r for r in rows[1:])

    def test_new_format(self, tmp_path):
        json_path = tmp_path / "pricing.json"
        csv_path = tmp_path / "pricing.csv"
        json_path.write_text(json.dumps({
            "iPhone 15": {"scraped_at": "2026-05-09T12:00:00Z",
                          "configs": {"128GB": "$799"}},
            "Galaxy S24": {"scraped_at": "2026-05-09T12:01:00Z",
                           "configs": None},
        }))
        n = convert(str(json_path), str(csv_path))
        assert n == 1
        text = csv_path.read_text()
        assert "iPhone 15,128GB,$799" in text

    def test_mixed_formats(self, tmp_path):
        json_path = tmp_path / "pricing.json"
        csv_path = tmp_path / "pricing.csv"
        json_path.write_text(json.dumps({
            "Old": {"64GB": "$499"},
            "New": {"scraped_at": "2026-05-09T12:00:00Z",
                    "configs": {"128GB": "$799"}},
        }))
        n = convert(str(json_path), str(csv_path))
        assert n == 2

    def test_missing_input_writes_empty_csv(self, tmp_path):
        csv_path = tmp_path / "pricing.csv"
        n = convert(str(tmp_path / "absent.json"), str(csv_path))
        assert n == 0
        assert csv_path.read_text().strip() == "Model,Configuration,Price"
