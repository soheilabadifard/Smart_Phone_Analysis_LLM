"""Unit tests for the pure helper functions in newDatabase.py.

These functions are small, deterministic, and used at every stage of the
loader — they're cheap to test and catch regressions fast.
"""

from __future__ import annotations

import hashlib

import pandas as pd
import pytest

from etl.newDatabase import (
    build_lookup_signature,
    clean_text_value,
    extract_camera_resolution,
    extract_integer_value,
    extract_numeric_value,
    normalize_lookup_value,
    parse_sensor_list,
)


class TestExtractNumericValue:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("5.2 inches", 5.2),
            ("128 GB", 128),
            ("~460 ppi", 460),
            ("-3.14", -3.14),
            ("171 g (6.03 oz)", 171),
            ("3.0", 3),  # whole-number floats collapse to int
            ("no value here", None),
            ("", None),
        ],
    )
    def test_string_inputs(self, raw, expected):
        assert extract_numeric_value(raw) == expected

    def test_nan_returns_none(self):
        assert extract_numeric_value(float("nan")) is None

    def test_none_returns_none(self):
        assert extract_numeric_value(None) is None


class TestExtractIntegerValue:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("5.7 inch", 5),
            ("8GB", 8),
            ("not a number", None),
        ],
    )
    def test_truncates_to_int(self, raw, expected):
        assert extract_integer_value(raw) == expected


class TestExtractCameraResolution:
    def test_picks_highest_when_multiple(self):
        assert extract_camera_resolution("12 + 48 + 12 MP") == 48

    def test_single_value(self):
        assert extract_camera_resolution("50 MP, f/1.8") == 50

    def test_decimal_preserved(self):
        assert extract_camera_resolution("13.5 MP") == 13.5

    def test_no_digits_returns_none(self):
        assert extract_camera_resolution("LED flash only") is None

    def test_nan_returns_none(self):
        assert extract_camera_resolution(float("nan")) is None


class TestNormalizeLookupValue:
    def test_nan_becomes_sentinel(self):
        assert normalize_lookup_value(float("nan")) == "__missing__"

    def test_integer_collapses_floats(self):
        assert normalize_lookup_value(8.0) == "8"
        assert normalize_lookup_value("8.0") == "8"

    def test_decimal_preserved(self):
        assert normalize_lookup_value(8.5) == "8.5"

    def test_string_lowercased_and_stripped(self):
        assert normalize_lookup_value("  Apple  ") == "apple"
        assert normalize_lookup_value("Galaxy S24 Ultra") == "galaxy s24 ultra"


class TestParseSensorList:
    def test_python_list_literal(self):
        out = parse_sensor_list("['Face ID', 'gyro', 'proximity']")
        assert out == ["face id", "gyro", "proximity"]

    def test_csv_fallback(self):
        out = parse_sensor_list("Fingerprint, accelerometer, compass")
        assert "fingerprint" in out
        assert "accelerometer" in out
        assert "compass" in out

    def test_dedupes_case_insensitive(self):
        out = parse_sensor_list("['gyro', 'GYRO', 'Gyro']")
        assert out == ["gyro"]

    def test_empty_input(self):
        assert parse_sensor_list("") == []
        assert parse_sensor_list(float("nan")) == []

    def test_preserves_order(self):
        out = parse_sensor_list("['barometer', 'gyro', 'compass']")
        assert out == ["barometer", "gyro", "compass"]


class TestCleanTextValue:
    def test_collapses_whitespace(self):
        assert clean_text_value("  Apple   iPhone   15  ") == "Apple iPhone 15"

    def test_lowercase_flag(self):
        assert clean_text_value("Octa-Core", lowercase=True) == "octa-core"
        assert clean_text_value("Octa-Core", lowercase=False) == "Octa-Core"

    def test_nan_returns_none(self):
        assert clean_text_value(float("nan")) is None

    def test_string_nan_returns_none(self):
        # final_adjustments fills with 'nan' strings — confirm they collapse
        assert clean_text_value("nan") is None


class TestBuildLookupSignature:
    def test_signature_is_sha256(self):
        df = pd.DataFrame([{"a": "Apple", "b": "iPhone 15"}])
        out = build_lookup_signature(df, ["a", "b"])
        assert len(out) == 1
        assert len(out.iloc[0]) == 64

    def test_signature_stable_across_normalisation(self):
        # Same brand+model, different casing/whitespace, must hash equal
        df = pd.DataFrame([
            {"a": "Apple", "b": "iPhone 15"},
            {"a": "apple", "b": "  IPHONE 15 "},
        ])
        out = build_lookup_signature(df, ["a", "b"])
        assert out.iloc[0] == out.iloc[1]

    def test_signature_differs_for_distinct_keys(self):
        df = pd.DataFrame([
            {"a": "Apple", "b": "iPhone 15"},
            {"a": "Apple", "b": "iPhone 14"},
        ])
        out = build_lookup_signature(df, ["a", "b"])
        assert out.iloc[0] != out.iloc[1]
