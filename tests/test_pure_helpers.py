"""Direct unit tests for pure helper functions across the ETL + generators.

These functions had 0% coverage because their host modules read files or
hit a DB. Each function tested here is side-effect-free and worth pinning
because they're consumed by the loader / cleaner / deliverable scripts.
"""

from __future__ import annotations

import pandas as pd
import pytest

from etl.JsonToDataframe import flatten_json, process_json
from etl.audit_cleaning import is_sentinel

# generate_records_sql lives at the repo root and is intentionally untracked
# (a developer-workstation deliverable generator). The two test classes that
# exercise it are skipped cleanly when it isn't on PYTHONPATH, so CI can still
# run TestFlattenJson / TestProcessJson / TestIsSentinel.
try:
    from generate_records_sql import emit_inserts, format_value
    _grs_available = True
except ModuleNotFoundError:
    emit_inserts = None  # type: ignore[assignment]
    format_value = None  # type: ignore[assignment]
    _grs_available = False

requires_grs = pytest.mark.skipif(
    not _grs_available,
    reason="generate_records_sql.py is a local-only deliverable generator",
)


# ---------------------------------------------------------------------------
# flatten_json — recursive nested dict / list flattener
# ---------------------------------------------------------------------------


class TestFlattenJson:
    def test_empty_dict(self):
        assert flatten_json({}) == {}

    def test_flat_dict_unchanged(self):
        assert flatten_json({"a": 1, "b": "two"}) == {"a": 1, "b": "two"}

    def test_one_level_nested(self):
        out = flatten_json({"Network": {"2G bands": "GSM 850"}})
        assert out == {"Network_2G bands": "GSM 850"}

    def test_two_levels_nested(self):
        out = flatten_json({"Body": {"Dimensions": {"value": "147x71"}}})
        assert out == {"Body_Dimensions_value": "147x71"}

    def test_list_indices_become_keys(self):
        out = flatten_json({"items": ["a", "b"]})
        assert out == {"items_0": "a", "items_1": "b"}

    def test_mixed_dict_and_list(self):
        out = flatten_json({"k": [{"x": 1}, {"x": 2}]})
        assert out == {"k_0_x": 1, "k_1_x": 2}

    def test_terminal_values_preserved(self):
        # Numbers, None, bools — passed through verbatim.
        out = flatten_json({"a": 1, "b": None, "c": True, "d": 2.5})
        assert out == {"a": 1, "b": None, "c": True, "d": 2.5}


# ---------------------------------------------------------------------------
# process_json — brand → model → details nested JSON to DataFrame
# ---------------------------------------------------------------------------


class TestProcessJson:
    def test_simple_brand_model_row(self):
        data = {
            "Apple": {
                "iPhone 15": {"Body": {"Weight": "171 g"}},
            }
        }
        df = process_json(data)
        assert len(df) == 1
        row = df.iloc[0]
        assert row["brand"] == "Apple"
        assert row["model"] == "iPhone 15"
        assert row["Body_Weight"] == "171 g"

    def test_multi_brand_multi_model(self):
        data = {
            "Apple":   {"iPhone 15": {"x": 1}, "iPhone 14": {"x": 2}},
            "Samsung": {"Galaxy S24": {"x": 3}},
        }
        df = process_json(data)
        assert len(df) == 3
        assert set(df["brand"]) == {"Apple", "Samsung"}
        assert set(df["model"]) == {"iPhone 15", "iPhone 14", "Galaxy S24"}

    def test_empty_data(self):
        df = process_json({})
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0


# ---------------------------------------------------------------------------
# is_sentinel — pandas predicate for "missing or sentinel" values
# ---------------------------------------------------------------------------


class TestIsSentinel:
    def test_numeric_series_only_nan(self):
        s = pd.Series([1.0, 2.0, float("nan"), 4.0])
        out = is_sentinel(s)
        assert out.tolist() == [False, False, True, False]

    def test_string_series_recognises_sentinels(self):
        s = pd.Series(["Apple", "unknown", "", "None", " None ", None])
        out = is_sentinel(s)
        # 'Apple' real; 'unknown', '', 'None' (case/whitespace-insensitive), None all sentinel
        assert out.tolist() == [False, True, True, True, True, True]

    def test_string_series_case_insensitive(self):
        s = pd.Series(["UNKNOWN", "Unknown", "uNkNoWn"])
        out = is_sentinel(s)
        assert out.tolist() == [True, True, True]

    def test_real_strings_not_sentinel(self):
        s = pd.Series(["Apple", "Samsung", "Xiaomi"])
        assert is_sentinel(s).tolist() == [False, False, False]


# ---------------------------------------------------------------------------
# format_value — Python value → SQL literal
# ---------------------------------------------------------------------------


@requires_grs
class TestFormatValue:
    def test_none_is_null(self):
        assert format_value(None) == "NULL"

    def test_bool_is_one_or_zero(self):
        assert format_value(True) == "1"
        assert format_value(False) == "0"

    def test_int_no_quoting(self):
        assert format_value(42) == "42"
        assert format_value(-7) == "-7"

    def test_float_uses_repr(self):
        # repr(3.14) == "3.14"; we want the SQL form to round-trip exactly
        assert format_value(3.14) == "3.14"

    def test_string_is_quoted_and_escaped(self):
        # pymysql quoting wraps in single quotes; embedded quotes are escaped
        out = format_value("O'Brien")
        assert out.startswith("'") and out.endswith("'")
        assert "O" in out and "Brien" in out
        # Verify single-quote escape (one of the standard MySQL forms)
        assert "\\'" in out or "''" in out

    def test_plain_string(self):
        assert format_value("Apple") == "'Apple'"


# ---------------------------------------------------------------------------
# emit_inserts — INSERT statement batcher
# ---------------------------------------------------------------------------


@requires_grs
class TestEmitInserts:
    def test_empty_rows_emits_comment(self):
        out = emit_inserts("Device", ["id", "year"], [], batch_size=10)
        assert out == ["-- (no rows in Device)"]

    def test_single_row(self):
        out = emit_inserts("Device", ["id", "year"], [(1, 2024)], batch_size=10)
        assert len(out) == 1
        stmt = out[0]
        assert stmt.startswith("INSERT INTO `Device` (`id`, `year`) VALUES")
        assert "(1, 2024)" in stmt
        assert stmt.endswith(";")

    def test_batches_split_at_batch_size(self):
        rows = [(i, 2020 + i) for i in range(5)]
        out = emit_inserts("Device", ["id", "year"], rows, batch_size=2)
        # 5 rows / batch=2 → 3 INSERT statements (2, 2, 1)
        assert len(out) == 3
        for stmt in out:
            assert stmt.startswith("INSERT INTO `Device`")
            assert stmt.endswith(";")

    def test_null_in_row(self):
        out = emit_inserts("Device", ["id", "weight"], [(1, None)], batch_size=10)
        assert "(1, NULL)" in out[0]

    def test_string_value_quoted(self):
        out = emit_inserts("Device_Name", ["brand", "model"], [("Apple", "iPhone 15")], batch_size=10)
        # Both string values appear quoted in the values clause
        assert "'Apple'" in out[0]
        assert "'iPhone 15'" in out[0]
