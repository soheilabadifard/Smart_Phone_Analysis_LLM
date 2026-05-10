"""Unit tests for Data_cleaning.DataPreProcess.

Each cleaner method gets exercised individually on a tiny sample DataFrame.
This is the most fragile part of the codebase — regex chains have
historically had silent fall-throughs — so the tests are deliberately
exhaustive.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from etl.Data_cleaning import DataPreProcess, GBP_TO_EUR, INR_TO_EUR, USD_TO_EUR


# ---------------------------------------------------------------------------
# Storage / RAM extraction (extract_storage_and_ram)
# ---------------------------------------------------------------------------


class TestExtractStorageAndRam:
    def setup_method(self):
        self.proc = DataPreProcess(pd.DataFrame())

    @pytest.mark.parametrize(
        "config,expected_storage,expected_ram",
        [
            ("128GB 6GB RAM", "128GB", "6GB"),
            ("256GB 12GB RAM", "256GB", "12GB"),
            ("64GB 4GB RAM", "64GB", "4GB"),
        ],
    )
    def test_general_pattern(self, config, expected_storage, expected_ram):
        s, r = self.proc.extract_storage_and_ram(config)
        assert s.replace(" ", "") == expected_storage
        assert r.replace(" ", "") == expected_ram

    def test_user_available_pattern(self):
        s, r = self.proc.extract_storage_and_ram(
            "128GB (122GB user available), 6GB RAM"
        )
        # the cleaner picks user_available as storage when present
        assert "GB" in s
        assert "6GB" in r.replace(" ", "")

    def test_ram_before_rom_pattern(self):
        s, r = self.proc.extract_storage_and_ram("4GB RAM, 64GB ROM")
        assert s.replace(" ", "") == "64GB"
        assert r.replace(" ", "") == "4GB"

    def test_carrier_specific_with_slash(self):
        # Documented behavior: when input is "X/Y, Zram RAM", the `general`
        # regex matches *the rightmost* storage option (Y) before
        # `carrier_specific` ever runs — so storage = "256GB", not "128GB".
        # The `carrier_specific` case-handler that splits on `/` and picks
        # the first option is unreachable for this input shape. Pinning here
        # so a future refactor that fixes it shows up as a test failure.
        s, r = self.proc.extract_storage_and_ram("128GB/256GB, 8GB RAM")
        assert s.replace(" ", "") == "256GB"
        assert r.replace(" ", "") == "8GB"

    def test_unparseable_returns_none(self):
        s, r = self.proc.extract_storage_and_ram("foldable variant")
        assert s is None
        assert r is None


# ---------------------------------------------------------------------------
# SIM_process
# ---------------------------------------------------------------------------


class TestSIMProcess:
    @pytest.mark.parametrize(
        "raw,expected_type,expected_count",
        [
            # "Dual eSIM" → 'dual' wins because the substring 'dual' is in
            # x_lower; this is correct per the cleaner's substring scan.
            ("Nano-SIM and eSIM or Dual eSIM", "nano", "dual"),
            ("Single SIM (Nano-SIM)", "nano", "single"),
            ("Dual SIM (Nano-SIM, dual stand-by)", "nano", "dual"),
            ("Triple SIM (Nano-SIM)", "nano", "triple"),
            ("Micro-SIM", "micro", "single"),
            ("Mini-SIM", "mini", "single"),
            ("eSIM", "esim", "single"),
            ("No", "none", "none"),
            ("none", "none", "none"),
            ("-", "none", "none"),
        ],
    )
    def test_known_patterns(self, raw, expected_type, expected_count):
        df = pd.DataFrame({"Body_SIM": [raw]})
        proc = DataPreProcess(df)
        proc.SIM_process()
        assert proc.df["SIM_type"].iloc[0] == expected_type
        assert proc.df["SIM_count"].iloc[0] == expected_count

    def test_non_string_returns_nan(self):
        df = pd.DataFrame({"Body_SIM": [None]})
        proc = DataPreProcess(df)
        proc.SIM_process()
        assert pd.isna(proc.df["SIM_type"].iloc[0])
        assert pd.isna(proc.df["SIM_count"].iloc[0])


# ---------------------------------------------------------------------------
# Body weight + dimensions
# ---------------------------------------------------------------------------


class TestWeightAndDimensions:
    def test_weight_in_grams(self):
        df = pd.DataFrame({"Body_Weight": ["171 g (6.03 oz)", "196 g"]})
        proc = DataPreProcess(df)
        proc.weight_process()
        assert proc.df["weight"].tolist() == [171.0, 196.0]

    def test_weight_kg_bug_documented(self):
        # KNOWN ISSUE (per project_data_quirks.md): kg vs g not normalized.
        # "0.5 kg" produces 0.5 (interpreted as g). This test pins the bug
        # so we know if/when it gets fixed.
        df = pd.DataFrame({"Body_Weight": ["0.5 kg"]})
        proc = DataPreProcess(df)
        proc.weight_process()
        assert proc.df["weight"].iloc[0] == 0.5  # NOT 500 — known bug

    def test_dimensions_extract_three_axes(self):
        df = pd.DataFrame({
            "Body_Dimensions": ["147.6 x 71.6 x 7.8 mm", "162.3 x 79.0 x 8.6 mm"],
        })
        proc = DataPreProcess(df)
        proc.demintions_process()
        assert proc.df["length"].tolist() == [147.6, 162.3]
        assert proc.df["width"].tolist() == [71.6, 79.0]
        assert proc.df["height"].tolist() == [7.8, 8.6]
        # volume = l * w * h
        assert proc.df["volume"].iloc[0] == pytest.approx(147.6 * 71.6 * 7.8)

    def test_dimensions_unparseable(self):
        df = pd.DataFrame({"Body_Dimensions": ["Foldable", None]})
        proc = DataPreProcess(df)
        proc.demintions_process()
        assert all(pd.isna(proc.df["length"]))
        assert all(pd.isna(proc.df["volume"]))

    def test_dimensions_dash_is_missing(self):
        """GSMArena uses '-' as a placeholder; should be treated as NaN, not
        counted as a parse failure."""
        df = pd.DataFrame({"Body_Dimensions": ["-", "  -  "]})
        proc = DataPreProcess(df)
        proc.demintions_process()
        assert all(pd.isna(proc.df["length"]))
        assert all(pd.isna(proc.df["height"]))
        assert all(pd.isna(proc.df["volume"]))

    def test_dimensions_two_axes_only(self):
        """'247 x 179 mm' — length + width, no thickness."""
        df = pd.DataFrame({"Body_Dimensions": ["247 x 179 mm"]})
        proc = DataPreProcess(df)
        proc.demintions_process()
        assert proc.df["length"].iloc[0] == 247
        assert proc.df["width"].iloc[0] == 179
        assert pd.isna(proc.df["height"].iloc[0])
        assert pd.isna(proc.df["volume"].iloc[0])

    def test_dimensions_unknown_width(self):
        """'156.8 x Unknown x 8 mm' — keep length and thickness."""
        df = pd.DataFrame({"Body_Dimensions": [
            "156.8 x Unknown x 8 mm",
            "126.1 x 50.5 x X.X mm",
        ]})
        proc = DataPreProcess(df)
        proc.demintions_process()
        # Row 0: length=156.8, width=NaN, height=8
        assert proc.df["length"].iloc[0] == 156.8
        assert pd.isna(proc.df["width"].iloc[0])
        assert proc.df["height"].iloc[0] == 8
        # Row 1: length=126.1, width=NaN (X.X is the placeholder), height=NaN
        # (the regex matches '<L> x <placeholder> x <H>' where H must be numeric;
        # 'X.X' isn't numeric so the partial-xyz regex won't match this row)
        assert proc.df["length"].iloc[1] == 126.1 or pd.isna(proc.df["length"].iloc[1])

    def test_dimensions_thickness_only(self):
        """'8.1 mm thickness' or 'Folded thickness: 10 mm' — height only."""
        df = pd.DataFrame({"Body_Dimensions": [
            "8.1 mm thickness",
            "Folded thickness: 10 mm",
        ]})
        proc = DataPreProcess(df)
        proc.demintions_process()
        assert proc.df["height"].iloc[0] == 8.1
        assert proc.df["height"].iloc[1] == 10
        assert pd.isna(proc.df["length"].iloc[0])
        assert pd.isna(proc.df["width"].iloc[1])

    def test_dimensions_volume_only(self):
        """'100 cc' — volume only."""
        df = pd.DataFrame({"Body_Dimensions": ["100 cc"]})
        proc = DataPreProcess(df)
        proc.demintions_process()
        assert proc.df["volume"].iloc[0] == 100
        assert pd.isna(proc.df["length"].iloc[0])


# ---------------------------------------------------------------------------
# Network technology indicator columns
# ---------------------------------------------------------------------------


class TestNetworkTechProcess:
    def test_5g_row_marked(self):
        df = pd.DataFrame({
            "Network_2G bands": ["GSM 850", None],
            "Network_3G bands": ["HSDPA 850", None],
            "Network_4G bands": ["LTE 1, 2", None],
            "Network_5G bands": ["1, 3, 5 SA/NSA", None],
        })
        proc = DataPreProcess(df)
        proc.network_tech_process()
        assert proc.df["5G"].tolist() == [1, 0]
        assert proc.df["4G"].tolist() == [1, 0]


# ---------------------------------------------------------------------------
# Battery
# ---------------------------------------------------------------------------


class TestBatteryProcess:
    def test_extracts_capacity(self):
        df = pd.DataFrame({
            "Battery_Type": [
                "Li-Ion 3349 mAh, non-removable",
                "Li-Po 5000 mAh, fast charging 33W",
                None,
            ],
        })
        proc = DataPreProcess(df)
        proc.battery_capacity_process()
        cap = proc.df["Battery_capacity"].tolist()
        assert cap[0] == 3349
        assert cap[1] == 5000
        assert pd.isna(cap[2])

    def test_wh_only_returns_nan(self):
        """Watt-hour-only entries had silently corrupted the column with the
        Wh number. Without cell voltage we can't convert, so we return NaN."""
        df = pd.DataFrame({
            "Battery_Type": [
                "Non-removable Li-Po battery (25 Wh)",
                "Li-Po (28.93 Wh)",
                "Li-Ion, non-removable (32.4 Wh)",
            ],
        })
        proc = DataPreProcess(df)
        proc.battery_capacity_process()
        cap = proc.df["Battery_capacity"].tolist()
        assert all(pd.isna(c) for c in cap)

    def test_mah_wins_over_wh(self):
        """When both are present, the mAh number is the right answer."""
        df = pd.DataFrame({
            "Battery_Type": ["Li-Ion 250 mAh (0.94 Wh), non-removable"],
        })
        proc = DataPreProcess(df)
        proc.battery_capacity_process()
        assert proc.df["Battery_capacity"].iloc[0] == 250

    def test_decimal_mah_rounded(self):
        """Schema is integer mAh; '303.8 mAh' should round to 304, not truncate to 303."""
        df = pd.DataFrame({
            "Battery_Type": ["Li-Ion 303.8 mAh (1.19 Wh), non-removable"],
        })
        proc = DataPreProcess(df)
        proc.battery_capacity_process()
        assert proc.df["Battery_capacity"].iloc[0] == 304

    def test_thousands_separator_in_mah(self):
        """GSMArena formats large tablet batteries as '10,050 mAh' — the
        regex must accept commas inside the digit run."""
        df = pd.DataFrame({
            "Battery_Type": [
                "Li-Po 10,050 mAh, non-removable",
                "Li-Ion 10,891 mAh, non-removable (41 Wh)",
            ],
        })
        proc = DataPreProcess(df)
        proc.battery_capacity_process()
        cap = proc.df["Battery_capacity"].tolist()
        assert cap[0] == 10050
        assert cap[1] == 10891

    def test_no_capacity_listed_returns_nan(self):
        """Pages that only list chemistry / removable status without a number."""
        df = pd.DataFrame({
            "Battery_Type": [
                "Removable Li-Ion battery",
                "Li-Ion, non-removable",
                "Removable battery",
            ],
        })
        proc = DataPreProcess(df)
        proc.battery_capacity_process()
        cap = proc.df["Battery_capacity"].tolist()
        assert all(pd.isna(c) for c in cap)


# ---------------------------------------------------------------------------
# Display extraction
# ---------------------------------------------------------------------------


class TestDisplayExtraction:
    def test_size_inch_and_cm(self):
        df = pd.DataFrame({
            "Display_Size": [
                "6.1 inches, 90.2 cm2 (~86.4% screen-to-body ratio)",
                "6.7 inches, 110.0 cm2 (~89.0%)",
            ],
        })
        proc = DataPreProcess(df)
        proc.extract_display_characteristics()
        assert proc.df["Display_Size_Inch"].tolist() == ["6.1", "6.7"]
        assert proc.df["Display_Size_Cm"].tolist() == ["90.2", "110.0"]

    def test_screen_to_body_ratio_strips_tilde_and_percent(self):
        df = pd.DataFrame({
            "Display_Size": ["6.1 inches, 90.2 cm2 (~86.4% screen-to-body ratio)"],
        })
        proc = DataPreProcess(df)
        proc.extract_display_characteristics()
        assert proc.df["Screen_To_Body_Ratio"].iloc[0] == 86.4

    def test_resolution_extraction(self):
        df = pd.DataFrame({
            "Display_Resolution": [
                "1179 x 2556 pixels, 19.5:9 ratio (~460 ppi density)",
                "720 x 1560 pixels, 19.5:9 ratio (~282 ppi density)",
                "480 x 800 pixels, 5:3 ratio (~233 ppi density)",
                "1080 x 2400 pixels, 20:9 ratio",
            ],
        })
        proc = DataPreProcess(df)
        proc.extract_resolution_details()
        assert proc.df["Resolution_Pixels"].iloc[0] == "1179 x 2556"
        # Regex now allows the decimal prefix — "19.5:9" stays "19.5:9".
        # Integer ratios like "5:3" / "20:9" still extracted unchanged.
        assert proc.df["Resolution_Ratio"].tolist() == [
            "19.5:9", "19.5:9", "5:3", "20:9",
        ]
        assert proc.df["PPI_Density"].iloc[0] == "460"


# ---------------------------------------------------------------------------
# Platform / OS / chipset / CPU
# ---------------------------------------------------------------------------


class TestOSExtraction:
    def test_base_os_first_token(self):
        df = pd.DataFrame({"Platform_OS": ["iOS 17.4", "Android 14, One UI 6.1"]})
        proc = DataPreProcess(df)
        proc.extract_base_os()
        assert proc.df["base_os"].tolist() == ["iOS", "Android"]

    def test_base_os_canonical_map(self):
        df = pd.DataFrame({"Platform_OS": [
            "Harmony OS 4.0",        # → HarmonyOS (was 23 rows)
            "Android-based 11",       # → Android (was 1 row)
            "Symbian^3, Anna",        # → Symbian (was 2 rows)
            "EMUI 12",                # unchanged — kept distinct
            "MagicOS 7",              # unchanged — kept distinct
            "Microsoft Windows Phone 8.1",  # unchanged — kept as 'Microsoft'
            "Proprietary",            # unchanged
        ]})
        proc = DataPreProcess(df)
        proc.extract_base_os()
        assert proc.df["base_os"].tolist() == [
            "HarmonyOS", "Android", "Symbian",
            "EMUI", "MagicOS", "Microsoft", "Proprietary",
        ]

    def test_version_extraction(self):
        df = pd.DataFrame({"Platform_OS": ["Android 14, One UI 6.1", "iOS 17"]})
        proc = DataPreProcess(df)
        proc.extract_os_version()
        assert proc.df["OS_Version"].tolist() == ["14", "17"]


class TestBrandCanonicalization:
    def test_alcatel_capitalized(self):
        df = pd.DataFrame({"brand": ["alcatel", "Samsung", "ZTE", "LG"]})
        proc = DataPreProcess(df)
        proc.canonicalize_brand()
        # alcatel → Alcatel; all-caps brands left alone.
        assert proc.df["brand"].tolist() == ["Alcatel", "Samsung", "ZTE", "LG"]


class TestChipsetExtraction:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Apple A16 Bionic", "Apple"),
            ("Qualcomm SM8650-AC Snapdragon 8 Gen 3", "Qualcomm"),
            ("Mediatek Dimensity 7050", "Mediatek"),
            ("Samsung Exynos 2400", "Samsung"),
            ("Some Unknown Chip", "Other"),
        ],
    )
    def test_known_manufacturers(self, raw, expected):
        df = pd.DataFrame({"Platform_Chipset": [raw]})
        proc = DataPreProcess(df)
        proc.extract_chipset_manufacturer()
        assert proc.df["Chipset_Manufacturer"].iloc[0] == expected


class TestCPUCoreCount:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Octa-core (1x3.39 GHz Cortex-X4 & ...)", 8),
            ("Hexa-core (2x3.46 GHz)", 6),
            ("Quad-core 1.4 GHz", 4),
            ("Dual-core 2.0 GHz", 2),
            ("Deca-core 2.0 GHz", 10),
            ("Single-core", 1),
            ("", None),
        ],
    )
    def test_known_keywords(self, raw, expected):
        df = pd.DataFrame({"Platform_CPU": [raw]})
        proc = DataPreProcess(df)
        proc.extract_cpu_core_count()
        result = proc.df["CPU_Core_Count"].iloc[0]
        if expected is None:
            assert pd.isna(result)
        else:
            assert result == expected


# ---------------------------------------------------------------------------
# Currency conversion — pins the known GBP→INR bug
# ---------------------------------------------------------------------------


class TestCurrencyConversion:
    def _run(self, prices):
        df = pd.DataFrame({"Misc_Price": prices})
        proc = DataPreProcess(df)
        proc.clean_and_extract_price()
        return proc.df

    def test_eur_passthrough(self):
        out = self._run(["About 800 EUR"])
        assert out["Price_EUR"].iloc[0] == 800.0

    def test_usd_converted(self):
        out = self._run(["$ 999.00"])
        assert out["Price_EUR"].iloc[0] == pytest.approx(999.0 * USD_TO_EUR)

    def test_inr_converted(self):
        out = self._run(["₹ 12,499"])
        assert out["Price_EUR"].iloc[0] == pytest.approx(12499 * INR_TO_EUR)

    def test_gbp_converted_correctly(self):
        # Regression test for the GBP→EUR conversion bug fixed on 2026-05-08.
        # Before: Data_cleaning.py:430 multiplied row['Price_INR'] (often None)
        # by gbp_to_eur_rate, producing NaN for GBP-only-priced devices.
        out = self._run(["£ 849.00"])
        assert out["Price_EUR"].iloc[0] == pytest.approx(849.0 * GBP_TO_EUR)

    def test_unparseable_currency_stays_nan(self):
        out = self._run(["1234.56"])
        # No recognised currency symbol → Price_EUR is NaN.
        # (Previously the cleaner extracted this into a Price_Other column
        # which was immediately dropped — dead code, removed 2026-05-10.)
        assert pd.isna(out["Price_EUR"].iloc[0])

    def test_intermediate_columns_not_emitted(self):
        """Refactor 2026-05-10: Price_USD/GBP/INR/Other are no longer added
        to the DataFrame as intermediate columns — only Price_EUR survives."""
        out = self._run(["About 800 EUR"])
        assert "Price_EUR" in out.columns
        for col in ("Price_USD", "Price_GBP", "Price_INR", "Price_Other"):
            assert col not in out.columns, f"intermediate column {col!r} should not be emitted"

    def test_eur_preferred_over_other_currencies_on_multi_row(self):
        """Multi-currency rows like '€800 / $899 / £729 / ₹74,999' should
        store the native EUR figure with no conversion applied."""
        out = self._run(["€ 800 / $ 899 / £ 729 / ₹ 74,999"])
        assert out["Price_EUR"].iloc[0] == 800.0  # exact, not 899 * USD_TO_EUR

    def test_loop_variable_bug_regression(self):
        """Earlier the cleaner reassigned the loop variable to the captured
        digit string, so `re.search(pattern, price)` on the next iteration
        searched '549' instead of the original. A USD-only row whose extracted
        digits accidentally match another regex would silently misclassify.
        Verify EUR is correctly identified even when the row also contains
        currency-shaped digits in a non-recognised position."""
        out = self._run(["Listed at $549 (was £499). About 600 EUR"])
        # Now that we always search the original string: EUR is recognised
        # and preferred — Price_EUR should be 600 exactly.
        assert out["Price_EUR"].iloc[0] == 600.0


class TestPriceImputation:
    """Cascade fills NaN Price_EUR with within-model → brand×year → brand."""

    def test_within_model_uses_priced_sibling(self):
        # Two configs of the same model; one priced, one NaN.
        df = pd.DataFrame({
            "brand": ["Apple", "Apple"],
            "model": ["iPhone 15", "iPhone 15"],
            "year": [2023, 2023],
            "Price_EUR": [800.0, None],
        })
        proc = DataPreProcess(df)
        proc.impute_missing_prices()
        assert proc.df["Price_EUR"].tolist() == [800.0, 800.0]

    def test_brand_year_median_when_no_model_match(self):
        # Three priced same-brand-same-year phones + one NaN.
        df = pd.DataFrame({
            "brand": ["Samsung"] * 4,
            "model": ["A", "B", "C", "Mystery"],
            "year": [2024, 2024, 2024, 2024],
            "Price_EUR": [400.0, 500.0, 600.0, None],
        })
        proc = DataPreProcess(df)
        proc.impute_missing_prices()
        # Median of [400, 500, 600] = 500 → fills "Mystery"
        assert proc.df.loc[3, "Price_EUR"] == 500.0

    def test_brand_only_fallback(self):
        # 5 same-brand priced phones (across years), one NaN in a year with no neighbours.
        df = pd.DataFrame({
            "brand": ["Xiaomi"] * 6,
            "model": list("ABCDEF"),
            "year": [2020, 2020, 2021, 2021, 2022, 2099],
            "Price_EUR": [200.0, 300.0, 400.0, 500.0, 600.0, None],
        })
        proc = DataPreProcess(df)
        proc.impute_missing_prices()
        # 2099 has no priced sibling — falls back to brand-only median
        # = median of [200, 300, 400, 500, 600] = 400
        assert proc.df.loc[5, "Price_EUR"] == 400.0

    def test_orphan_brand_stays_nan(self):
        # Brand has only one priced phone (< 5 needed for fallback).
        df = pd.DataFrame({
            "brand": ["Obscure", "Obscure"],
            "model": ["X", "Y"],
            "year": [2020, 2020],
            "Price_EUR": [123.0, None],
        })
        proc = DataPreProcess(df)
        proc.impute_missing_prices()
        # Within-model misses (different models), brand×year misses (count<3),
        # brand-only misses (count<5) → stays NaN.
        assert pd.isna(proc.df.loc[1, "Price_EUR"])

    def test_cascade_priority_within_model_wins(self):
        # Both within-model and brand×year would fill, but within-model wins.
        df = pd.DataFrame({
            "brand": ["Apple"] * 5,
            "model": ["iPhone 15", "iPhone 15", "Watch", "Pad", "AirPods"],
            "year": [2023, 2023, 2023, 2023, 2023],
            "Price_EUR": [800.0, None, 400.0, 1200.0, 200.0],
        })
        proc = DataPreProcess(df)
        proc.impute_missing_prices()
        # Within-model uses the priced sibling = 800. (Brand×year median
        # of [800, 400, 1200, 200] = 600, which is NOT what we expect.)
        assert proc.df.loc[1, "Price_EUR"] == 800.0

    def test_imputation_does_not_overwrite_native_prices(self):
        df = pd.DataFrame({
            "brand": ["Apple"] * 4,
            "model": ["A", "B", "C", "D"],
            "year": [2023] * 4,
            "Price_EUR": [800.0, 900.0, 1000.0, 700.0],
        })
        proc = DataPreProcess(df)
        before = proc.df["Price_EUR"].tolist()
        proc.impute_missing_prices()
        # Nothing should change — no NaNs to fill.
        assert proc.df["Price_EUR"].tolist() == before

    def test_imputation_uses_only_native_prices(self):
        """Brand×year median must be computed from the *original* priced
        rows, not from imputed values added in step 1. Otherwise step-2
        medians drift."""
        # Brand-A iPhone 15 priced at 800, sibling NaN → step 1 fills 800.
        # Brand-A 2024 cluster has 3 other priced rows with median 500.
        # The "Mystery" 2024 row should get 500 (brand-year), NOT something
        # influenced by the within-model fill.
        df = pd.DataFrame({
            "brand": ["Apple"] * 6,
            "model": ["iPhone 15", "iPhone 15", "X", "Y", "Z", "Mystery"],
            "year": [2024] * 6,
            "Price_EUR": [800.0, None, 400.0, 500.0, 600.0, None],
        })
        proc = DataPreProcess(df)
        proc.impute_missing_prices()
        # Index 1: within-model match → 800
        # Index 5: brand×year median of original [800, 400, 500, 600] = 550
        assert proc.df.loc[1, "Price_EUR"] == 800.0
        assert proc.df.loc[5, "Price_EUR"] == 550.0


# ---------------------------------------------------------------------------
# Camera columns
# ---------------------------------------------------------------------------


class TestMainCameraCounts:
    def test_count_picked_from_first_match(self):
        df = pd.DataFrame({
            "Main Camera_Single": [None, None, None, "13 MP, f/2.2"],
            "Main Camera_Dual": [None, "12+50 MP", None, None],
            "Main Camera_Triple": ["48+12+12 MP", None, "108+8+2", None],
            "Main Camera_Quad": [None] * 4,
            "Main Camera_Dual or Triple": [None] * 4,
            "Main Camera_Penta": [None] * 4,
            "Main Camera_Five": [None] * 4,
        })
        proc = DataPreProcess(df)
        proc.process_main_camera_columns()
        assert proc.df["Number of main cameras"].tolist() == [3, 2, 3, 1]


class TestMemoryCardSlot:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("microSDXC", "Microsd"),
            ("No", "No"),
            ("Yes", "Yes"),
            ("microSDXC (dedicated slot)", "Microsd"),
            (None, None),
        ],
    )
    def test_card_slot_normalisation(self, raw, expected):
        df = pd.DataFrame({"Memory_Card slot": [raw]})
        proc = DataPreProcess(df)
        proc.preprocess_memory_card_slot()
        result = proc.df["Card_Slot_Type"].iloc[0]
        if expected is None:
            assert result is None
        else:
            assert result == expected


# ---------------------------------------------------------------------------
# Launch status normalization
# ---------------------------------------------------------------------------


class TestLaunchStatusNormalization:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Available. Released 2023, September", "Available"),
            ("Discontinued", "Discontinued"),
            ("Cancelled", "Canceled"),  # British spelling normalised
            ("Coming soon. Exp. release 2024", "Rumored"),
            ("Rumored", "Rumored"),
            ("garbage", None),
            (None, None),
        ],
    )
    def test_normalisation(self, raw, expected):
        result = DataPreProcess._normalize_launch_status(raw)
        assert result == expected
