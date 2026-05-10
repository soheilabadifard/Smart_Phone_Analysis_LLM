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

    def test_unparseable_currency_uses_other(self):
        out = self._run(["1234.56"])
        # No currency symbol → falls into Price_Other, so Price_EUR stays NaN
        assert pd.isna(out["Price_EUR"].iloc[0])


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
