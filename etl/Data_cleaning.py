import re
import sys


def _report_cleaner_misses(method: str, parse_fail: int, nan_input: int) -> None:
    """Print a per-method diagnostic separating real parse failures (a column
    has a value but the cleaner couldn't extract from it) from missing-source
    rows (the column was NaN to begin with). Empty inputs are normal data
    incompleteness; non-zero parse_fail is the actionable signal."""
    if parse_fail or nan_input:
        print(
            f"{method}: {parse_fail} unparseable, {nan_input} empty",
            file=sys.stderr,
        )
from pathlib import Path

import numpy as np
import pandas as pd


# FX rates used to normalize Misc_Price to EUR. Refreshed manually; the
# scraped prices are themselves point-in-time, so live rates would be
# misleading. Update these alongside any pipeline re-run.
# Last refreshed: 2026-05-08.
USD_TO_EUR = 0.93
GBP_TO_EUR = 1.17
INR_TO_EUR = 0.011

_FX_RATES = {
    'EUR': 1.0,
    'USD': USD_TO_EUR,
    'GBP': GBP_TO_EUR,
    'INR': INR_TO_EUR,
}

_PRICE_PATTERNS = {
    'EUR': re.compile(r'(?:About\s)?\€\s*(\d{1,3}(?:,\d{3})*\.?\d*)|(?:About\s)?(\d{1,3}(?:,\d{3})*\.?\d*)\s*EUR'),
    'USD': re.compile(r'(?:About\s)?\$\s*(\d{1,3}(?:,\d{3})*\.?\d*)'),
    'GBP': re.compile(r'(?:About\s)?£\s*(\d{1,3}(?:,\d{3})*\.?\d*)'),
    'INR': re.compile(r'(?:About\s)?₹\s*(\d{1,3}(?:,\d{3})*\.?\d*)|(?:About\s)?(\d{1,3}(?:,\d{3})*\.?\d*)\s*INR'),
}


def _extract_price_per_currency(raw):
    """Pull every recognised currency value out of a Misc_Price string.

    Returns a dict {currency: float}. The previous implementation reassigned
    the loop variable on each match (`price = match.group(1) or ...`), which
    meant subsequent currencies searched the captured digit string instead
    of the original — silently dropping later currencies on multi-currency
    rows. This version always searches the original string.
    """
    if not isinstance(raw, str):
        return {}
    out = {}
    for currency, pattern in _PRICE_PATTERNS.items():
        match = pattern.search(raw)
        if match is None:
            continue
        digits = match.group(1) or match.group(2)
        if not digits:
            continue
        try:
            out[currency] = float(digits.replace(',', ''))
        except (ValueError, TypeError):
            pass
    return out

DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


class DataPreProcess:
    def __init__(self, data_input):
        # If data_input is a string, assume it's a filename. Otherwise, assume it's a DataFrame.
        if isinstance(data_input, str):
            self.df = pd.read_csv(data_input, )
        else:
            self.df = data_input

    # Convert to string and remove leading "~"

    def process_main_camera_columns(self):
        camera_types = {
            'Main Camera_Single': 1,
            'Main Camera_Dual': 2,
            'Main Camera_Triple': 3,
            'Main Camera_Quad': 4,
            'Main Camera_Dual or Triple': 3,
            'Main Camera_Penta': 5,
            'Main Camera_Five': 5
        }
        self.df['Number of main cameras'] = 0
        for col, num in camera_types.items():
            self.df.loc[self.df[col].notnull(), 'Number of main cameras'] = num

    def process_selfie_camera_columns(self):
        camera_types = {
            'Selfie camera_Single': 1,
            'Selfie camera_Dual': 2,
            'Selfie camera_Triple': 3
        }
        self.df['Number of selfie cameras'] = 0
        for col, num in camera_types.items():
            self.df.loc[self.df[col].notnull(), 'Number of selfie cameras'] = num

    def get_highest_res(self, cell):
        cell = str(cell)
        matches = re.findall(r'(\d+(?:\.\d+)?)\s*MP', cell)
        if matches:
            return str(max(float(m) for m in matches))
        legacy_mp = {'qcif': 0.025, 'qvga': 0.077, 'cif': 0.101, 'vga': 0.307, 'svga': 0.480}
        cell_lower = cell.lower()
        legacy_hits = [v for k, v in legacy_mp.items() if re.search(r'\b' + k + r'\b', cell_lower)]
        if legacy_hits:
            return str(max(legacy_hits))
        return cell

    def get_video_res(self, cell):
        cell = str(cell)
        if '@' in cell:
            cell = cell.split('@')[0].strip()
        return cell

    def get_features_list(self, cell):
        cell = str(cell)
        if ',' in cell:
            cell = cell.split(',')
        return cell

    def process_camera_resolutions(self):
        self.df['Highest_maincam_res'] = self.df['Main Camera_Single'].combine_first(
            self.df['Main Camera_Dual']).combine_first(self.df['Main Camera_Triple']).combine_first(
            self.df['Main Camera_Quad']).combine_first(self.df['Main Camera_Dual or Triple']).combine_first(
            self.df['Main Camera_Penta']).combine_first(self.df['Main Camera_Five'])
        self.df['Highest_maincam_res'] = self.df['Highest_maincam_res'].apply(self.get_highest_res)
        self.df['Highest_selfiecam_res'] = self.df['Selfie camera_Single'].combine_first(
            self.df['Selfie camera_Dual']).combine_first(self.df['Selfie camera_Triple'])
        self.df['Highest_selfiecam_res'] = self.df['Highest_selfiecam_res'].apply(self.get_highest_res)

    def process_video_resolution(self):
        self.df['Main Camera_Video'] = self.df['Main Camera_Video'].apply(self.get_video_res)
        self.df['Selfie camera_Video'] = self.df['Selfie camera_Video'].apply(self.get_video_res)

    def camera_features_listing(self):
        self.df['Main Camera_Features'] = self.df['Main Camera_Features'].apply(self.get_features_list)
        self.df['Selfie camera_Features'] = self.df['Selfie camera_Features'].apply(self.get_features_list)

    def demintions_process(self):
        # Body_Dimensions takes several shapes on GSMArena:
        #   - Standard "147.6 x 71.6 x 7.8 mm"  (3 axes — happy path)
        #   - "247 x 179 mm"                     (2D, no thickness)
        #   - "156.8 x Unknown x 8 mm"           (length + thickness, width missing)
        #   - "8.1 mm thickness"                 (thickness only — typically a
        #                                          phone GSMArena hasn't sized yet)
        #   - "Folded thickness: 10 mm"          (foldable with only folded depth)
        #   - "100 cc"                           (volume only)
        #   - "-"                                (placeholder for missing data)
        # Partial extraction populates whichever axes we can parse and leaves
        # the rest NaN. Only rows that match no pattern at all count as
        # parse failures in the diagnostic.
        pat_three = re.compile(
            r'(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*mm',
            re.IGNORECASE,
        )
        pat_partial_xyz = re.compile(
            r'(\d+(?:\.\d+)?)\s*x\s*(?:unknown|x\.x|-)\s*x\s*(\d+(?:\.\d+)?)\s*mm',
            re.IGNORECASE,
        )
        pat_two = re.compile(
            r'(\d+(?:\.\d+)?)\s*x\s*(\d+(?:\.\d+)?)\s*mm\b',
            re.IGNORECASE,
        )
        pat_thickness = re.compile(
            r'(\d+(?:\.\d+)?)\s*mm\s*thick', re.IGNORECASE,
        )
        pat_thickness_label = re.compile(
            r'thickness[^0-9]*(\d+(?:\.\d+)?)\s*mm', re.IGNORECASE,
        )
        pat_volume = re.compile(r'(\d+(?:\.\d+)?)\s*cc\b', re.IGNORECASE)

        length, width, height, volume = [], [], [], []
        nan_input = 0
        parse_fail = 0
        for x in list(self.df['Body_Dimensions']):
            if pd.isna(x) or (isinstance(x, str) and x.strip() in ('', '-')):
                length.append(np.nan); width.append(np.nan)
                height.append(np.nan); volume.append(np.nan)
                nan_input += 1
                continue
            if not isinstance(x, str):
                length.append(np.nan); width.append(np.nan)
                height.append(np.nan); volume.append(np.nan)
                parse_fail += 1
                continue

            m = pat_three.search(x)
            if m:
                l, w, h = float(m.group(1)), float(m.group(2)), float(m.group(3))
                length.append(l); width.append(w); height.append(h)
                volume.append(l * w * h)
                continue

            # "L x Unknown x H mm" — keep length and thickness, width = NaN.
            m = pat_partial_xyz.search(x)
            if m:
                length.append(float(m.group(1))); width.append(np.nan)
                height.append(float(m.group(2))); volume.append(np.nan)
                continue

            # "L x W mm" — 2D dimensions, no thickness.
            m = pat_two.search(x)
            if m:
                length.append(float(m.group(1))); width.append(float(m.group(2)))
                height.append(np.nan); volume.append(np.nan)
                continue

            # Thickness-only forms, e.g. "8.1 mm thickness" or
            # "Folded thickness: 10 mm".
            m = pat_thickness.search(x) or pat_thickness_label.search(x)
            if m:
                length.append(np.nan); width.append(np.nan)
                height.append(float(m.group(1))); volume.append(np.nan)
                continue

            # Volume-only ("100 cc").
            m = pat_volume.search(x)
            if m:
                length.append(np.nan); width.append(np.nan)
                height.append(np.nan); volume.append(float(m.group(1)))
                continue

            # Nothing matched — true parse failure.
            length.append(np.nan); width.append(np.nan)
            height.append(np.nan); volume.append(np.nan)
            parse_fail += 1

        _report_cleaner_misses('demintions_process', parse_fail, nan_input)
        self.df['length'] = length
        self.df['width'] = width
        self.df['height'] = height
        self.df['volume'] = volume

    def weight_process(self):
        weight = []
        nan_input = 0
        parse_fail = 0
        for x in list(self.df['Body_Weight']):
            # NaN or GSMArena's "-" placeholder → semantic missing value.
            if pd.isna(x) or (isinstance(x, str) and x.strip() in ('', '-')):
                weight.append(np.nan)
                nan_input += 1
                continue
            try:
                m = re.findall(r'(\d+(?:\.\d+)?)', x)
                weight.append(float(m[0]))
            except (IndexError, ValueError, TypeError):
                weight.append(np.nan)
                parse_fail += 1
        _report_cleaner_misses('weight_process', parse_fail, nan_input)
        self.df['weight'] = weight

    def network_tech_process(self):
        for src, dst in [('Network_2G bands', '2G'),
                         ('Network_3G bands', '3G'),
                         ('Network_4G bands', '4G'),
                         ('Network_5G bands', '5G')]:
            self.df[dst] = self.df[src].notna().astype(int)

    def battery_capacity_process(self):
        # Anchor on the literal 'mAh' suffix so we never confuse Wh, V, or W
        # numbers for capacity. A typical row looks like
        # "Li-Ion 3349 mAh, non-removable" or "Li-Ion 303.8 mAh (1.19 Wh)".
        # Tablets sometimes use a thousands separator: "Li-Po 10,050 mAh" — we
        # allow commas inside the digit run and strip them before parsing.
        # Watt-hour-only entries (e.g. "Li-Po (25 Wh)") return NaN — without
        # the cell voltage we can't safely convert Wh to mAh.
        pattern = re.compile(r'(\d[\d,]*(?:\.\d+)?)\s*mAh', re.IGNORECASE)
        battery_capacity = []
        nan_input = 0
        parse_fail = 0
        for x in list(self.df['Battery_Type']):
            if pd.isna(x):
                battery_capacity.append(np.nan)
                nan_input += 1
                continue
            match = pattern.search(x)
            if match is None:
                battery_capacity.append(np.nan)
                parse_fail += 1
                continue
            try:
                # Strip thousands separator before float conversion.
                # round() collapses 303.8 → 304 (schema is integer mAh).
                battery_capacity.append(round(float(match.group(1).replace(',', ''))))
            except (ValueError, TypeError):
                battery_capacity.append(np.nan)
                parse_fail += 1
        _report_cleaner_misses('battery_capacity_process', parse_fail, nan_input)
        self.df['Battery_capacity'] = battery_capacity

    def sensors_process(self):
        sensors = []
        nan_input = 0
        parse_fail = 0
        for x in list(self.df['Features_Sensors']):
            if pd.isna(x):
                sensors.append(np.nan)
                nan_input += 1
                continue
            try:
                sensors.append(x.split(','))
            except (AttributeError, TypeError):
                sensors.append(np.nan)
                parse_fail += 1
        _report_cleaner_misses('sensors_process', parse_fail, nan_input)
        self.df['Sensors'] = sensors

    def extract_display_characteristics(self):
        self.df['Display_Size_Inch'] = self.df['Display_Size'].apply(
            lambda x: self._extract_with_regex(x, r'(\d+\.?\d*) inches')
        )
        self.df['Display_Size_Cm'] = self.df['Display_Size'].apply(
            lambda x: self._extract_with_regex(x, r'(\d+\.?\d*) cm2')
        )
        self.df['Screen_To_Body_Ratio'] = self.df['Display_Size'].apply(
            lambda x: self._extract_with_regex(x, r'(~\d+\.?\d*%)')
        )

        def remove_tilde_percent(value):
            cleaned = str(value).replace("~", "").replace("%", "")
            try:
                return float(cleaned)
            except (ValueError, TypeError):
                # Non-numeric residue (e.g. NaN literal). Keep the original
                # string so downstream cleanup can decide what to do.
                return cleaned

        self.df['Screen_To_Body_Ratio'] = self.df['Screen_To_Body_Ratio'].apply(remove_tilde_percent)
        self.df['Screen_To_Body_Ratio'].value_counts()

    def SIM_process(self):
        type_sim = []
        count = []
        for x in list(self.df['Body_SIM']):
            if not isinstance(x, str):
                type_sim.append(np.nan)
                count.append(np.nan)
                continue

            x_lower = x.lower().strip()

            if x_lower in ('no', 'none', '-'):
                type_sim.append('none')
                count.append('none')
                continue

            if 'nano' in x_lower:
                type_sim.append('nano')
            elif 'micro' in x_lower:
                type_sim.append('micro')
            elif 'mini' in x_lower:
                type_sim.append('mini')
            elif 'esim' in x_lower:
                type_sim.append('esim')
            else:
                type_sim.append('unknown')

            has_single = 'single' in x_lower
            has_dual = 'dual' in x_lower
            has_triple = 'triple' in x_lower
            if has_triple:
                count.append('triple')
            elif has_dual:
                count.append('dual')
            elif has_single:
                count.append('single')
            elif 'sim' in x_lower or x_lower == 'yes':
                count.append('single')
            else:
                count.append('none')
        self.df['SIM_type'] = type_sim
        self.df['SIM_count'] = count

    def extract_resolution_details(self):
        self.df['Resolution_Pixels'] = self.df['Display_Resolution'].apply(
            lambda x: self._extract_with_regex(x, r'(\d+ x \d+) pixels')
        )
        self.df['Resolution_Ratio'] = self.df['Display_Resolution'].apply(
            lambda x: self._extract_with_regex(x, r'(\d+(?:\.\d+)?:\d+) ratio')
        )
        self.df['PPI_Density'] = self.df['Display_Resolution'].apply(
            lambda x: self._extract_with_regex(x, r'(~?\d+) ppi')
        )

        def remove_tilde(value):
            return str(value).lstrip("~")

        self.df['PPI_Density'] = self.df['PPI_Density'].apply(remove_tilde)
        self.df['PPI_Density'].value_counts()

    # Trivial naming-variant fixes for base_os. Android skins (EMUI, MagicOS,
    # MIUI, ColorOS, …), `Microsoft`, and `Proprietary` are intentionally NOT
    # in this map — they're kept distinct on purpose.
    _OS_CANONICAL_MAP = {
        'Harmony': 'HarmonyOS',
        'Android-based': 'Android',
        'Symbian^3,': 'Symbian',
    }

    # Brand naming-variant fixes. All-caps brands (LG, ZTE, BLU, HTC) are
    # left alone — they're correctly that way upstream.
    _BRAND_CANONICAL_MAP = {
        'alcatel': 'Alcatel',
    }

    def canonicalize_brand(self):
        self.df['brand'] = self.df['brand'].apply(
            lambda x: self._BRAND_CANONICAL_MAP.get(x, x) if isinstance(x, str) else x
        )

    def extract_base_os(self):

        self.df['base_os'] = self.df['Platform_OS'].apply(
            lambda x: self._extract_os_from_first_space(x)
        )

    def _extract_os_from_first_space(self, os_string):

        if not isinstance(os_string, str):
            return os_string
        token = os_string.split(' ', 1)[0]
        return self._OS_CANONICAL_MAP.get(token, token)

    def extract_os_version(self):

        self.df['OS_Version'] = self.df['Platform_OS'].apply(
            lambda x: self._extract_version_number(x)
        )

    def _extract_version_number(self, os_string):
        if not isinstance(os_string, str):
            return np.nan
        match = re.search(r'\b(\d+(?:\.\d+)*)\b', os_string)
        if match:
            return match.group(1)
        return np.nan

    def extract_chipset_manufacturer(self):
        manufacturers = ["Qualcomm", "Mediatek", "Apple", "Samsung", "Exynos", "Intel Atom"]
        self.df['Chipset_Manufacturer'] = self.df['Platform_Chipset'].apply(
            lambda x: next((manufacturer for manufacturer in manufacturers if manufacturer in str(x)), "Other")
        )

    def extract_cpu_core_count(self):
        keyword_to_count = {'dual': 2, 'quad': 4, 'hexa': 6, 'octa': 8, 'deca': 10}

        def _count(value):
            if not isinstance(value, str) or not value.strip():
                return np.nan
            match = re.search(r'(Dual|Quad|Hexa|Octa|Deca)-core', value, re.IGNORECASE)
            if match:
                return keyword_to_count[match.group(1).lower()]
            return 1

        self.df['CPU_Core_Count'] = self.df['Platform_CPU'].apply(_count)

    def preprocess_memory_card_slot(self):

        self.df['Card_Slot_Type'] = self.df['Memory_Card slot'].apply(self._preprocess_memory_card_slot_value)

    def _preprocess_memory_card_slot_value(self, value):

        if pd.isna(value):
            return None  # Handle missing or null values
        value_str = str(value).lower()  # Standardize the string for comparison

        # Define keywords that imply card slot support
        keywords = ['microsd', 'sd', 'mmc', 'minisd', 'nanomemory']

        # Check for explicit "no" mention
        if 'no' in value_str:
            return 'No'

        # Check and return the specific keyword found in the value
        for keyword in keywords:
            if keyword in value_str:
                return keyword.capitalize()  # Return the keyword with the first letter capitalized for consistency

        # If "yes" is mentioned but no specific type is identified
        if 'yes' in value_str:
            return 'Yes'

        # Return 'Unknown' if none of the conditions are met
        return 'Unknown'

    def expand_memory_configurations(self, column_name='Memory_Internal', extraprice=None):
        expanded_df_list = []

        for _, row in self.df.iterrows():
            value = str(row[column_name]) if pd.notnull(row[column_name]) else ''
            configs = re.split(r',|;', value)

            for config in configs:
                storage, ram = self.extract_storage_and_ram(config.strip())

                if storage and ram:
                    new_row = row.copy()
                    new_row['Storage'] = storage
                    new_row['RAM'] = ram
                    expanded_df_list.append(new_row)

        self.df = pd.DataFrame(expanded_df_list).reset_index(drop=True)

        if extraprice is not None:
            for index, extra_row in extraprice.iterrows():
                for index1, df_row in self.df.iterrows():
                    if extra_row['Model'] == df_row['model']:
                        memory_config = f"{df_row.get('Storage', '')} {df_row.get('RAM', '')} RAM".strip()
                        if memory_config == extra_row['Configuration']:
                            self.df.at[index1, 'Misc_Price'] = extra_row['Price']

    def extract_storage_and_ram(self, config):
        patterns = {
            'general': re.compile(
                r'(?P<storage>\d+\.?\d*\s*[GTMB]B)(?:\s*\(\d+\.?\d*\s*[GTMB]B\s*user available\))?'
                r'(?:/\s*\d+\.?\d*\s*[GTMB]B\s*\([^)]+\))?'
                r',?\s*(?P<ram>\d+\.?\d*\s*[GTMB]B)\s*RAM'
            ),
            'user_available': re.compile(
                r'(?P<storage>\d+\.?\d*\s*[GTMB]B)\s*\((?P<user_available>\d+\.?\d*\s*[GTMB]B)\s*user available\),?\s*(?P<ram>\d+\.?\d*\s*[GTMB]B|\d+\.?\d*\s*[GM]B)\s*RAM'
            ),
            'ram_before_rom': re.compile(
                r'(?P<ram>\d+\.?\d*\s*[GM]B)\s*RAM,\s*(?P<storage>\d+\.?\d*\s*[GM]B)\s*ROM'
            ),
            'carrier_specific': re.compile(
                r'(?P<storage>\d+\.?\d*\s*[GTMB]B)(?:/\s*\d+\.?\d*\s*[GTMB]B)?(?:\s*\([^)]+\))?,\s*(?P<ram>\d+\.?\d*\s*[GTMB]B|\d+\.?\d*\s*[GM]B)\s*RAM'
            ),
            'multi_storage_user_available': re.compile(
                r'(?P<storage_options>\d+\.?\d*\s*[GTMB]B(?:/\d+\.?\d*\s*[GTMB]B)*)(?:\s*\(\d+\.?\d*\s*[GTMB]B\s*user available\))?,?\s*(?P<ram>\d+\.?\d*\s*[GTMB]B|\d+\.?\d*\s*[GM]B)\s*RAM'
            ),
            'multi_storage_single_ram': re.compile(
                r'(?P<storage>\d+\.?\d*\s*[GTMB]B)/(?P<additional_storage>\d+\.?\d*\s*[GTMB]B)(?:\s*\([^)]*\))?,\s*(?P<ram>\d+\.?\d*\s*[GTMB]B|\d+\.?\d*\s*[GM]B)\s*RAM'
            ),
            'rom_ram_explicit': re.compile(
                r'(?P<storage>\d+\.?\d*\s*[GTMB]B)\s*ROM,\s*(?P<ram>\d+\.?\d*\s*[GTMB]B)\s*RAM'
            ),
        }

        storage, ram = None, None

        for case, pattern in patterns.items():
            match = pattern.search(config)
            if match:
                if case == 'user_available' and 'user_available' in match.groupdict():
                    storage = match.group('user_available')
                else:
                    storage = match.group('storage')

                ram = match.group('ram')
                if storage and '/' in storage:
                    storage = storage.split('/')[0].strip()
                if case == 'carrier_specific' and '/' in match.group('storage'):
                    storage_options = re.split(r'/', match.group('storage'))
                    storage = storage_options[0].strip()

                break
        if not storage and not ram:
            simple_storage = re.match(r'^(\d+\.?\d*\s*[GTMB]B)$', config)
            simple_ram = re.match(r'^(\d+\.?\d*\s*[GM]B)\s*RAM$', config)

            if simple_storage:
                storage = simple_storage.group(1)
            elif simple_ram:
                ram = simple_ram.group(1)

        return storage, ram

    def clean_and_extract_price(self):
        """Resolve Misc_Price to a single Price_EUR per row.

        Preference order: native EUR > USD > GBP > INR. The first match in
        this order becomes Price_EUR (FX-converted via _FX_RATES if it isn't
        already EUR). Multi-currency rows like '€800 / $899' use the EUR
        figure directly without any conversion. Rows without any recognised
        currency stay NaN — the previous Price_Other fallback was extracted
        but immediately dropped, so we skip it.

        Prints a per-currency conversion summary so a stale FX rate or
        regex regression is visible at a glance.
        """
        counter = {'EUR-native': 0, 'from USD': 0, 'from GBP': 0, 'from INR': 0,
                   'unrecognised': 0, 'missing': 0}

        def per_row(raw):
            if pd.isna(raw):
                counter['missing'] += 1
                return None
            extracted = _extract_price_per_currency(raw)
            if 'EUR' in extracted:
                counter['EUR-native'] += 1
                return extracted['EUR']
            for currency in ('USD', 'GBP', 'INR'):
                if currency in extracted:
                    counter[f'from {currency}'] += 1
                    return extracted[currency] * _FX_RATES[currency]
            counter['unrecognised'] += 1
            return None

        self.df['Price_EUR'] = self.df['Misc_Price'].apply(per_row)

        summary = ', '.join(f'{n} {label}' for label, n in counter.items() if n)
        print(f"clean_and_extract_price: {summary}", file=sys.stderr)

    def impute_missing_prices(self):
        """Cascade-fill NaN Price_EUR with within-model → brand×year → brand
        medians. Imputed values overwrite NaN in Price_EUR directly — there
        is no marker column distinguishing native from imputed prices, so
        downstream analytics treat them identically. Documented in CLAUDE.md.

        All medians are computed from the *original* priced rows once at the
        start; we never recurse on imputed values to avoid bias drift.
        """
        priced = self.df[self.df['Price_EUR'].notna()]
        model_means = priced.groupby('model')['Price_EUR'].mean()

        by_grouped = priced.groupby(['brand', 'year'])['Price_EUR'].agg(['median', 'count'])
        by_medians = by_grouped[by_grouped['count'] >= 3]['median']

        brand_grouped = priced.groupby('brand')['Price_EUR'].agg(['median', 'count'])
        brand_medians = brand_grouped[brand_grouped['count'] >= 5]['median']

        counter = {'within_model': 0, 'brand_year': 0, 'brand_only': 0}
        for idx in self.df.index[self.df['Price_EUR'].isna()]:
            model = self.df.at[idx, 'model']
            brand = self.df.at[idx, 'brand']
            year = self.df.at[idx, 'year']
            if model in model_means.index:
                self.df.at[idx, 'Price_EUR'] = float(model_means[model])
                counter['within_model'] += 1
            elif (brand, year) in by_medians.index:
                self.df.at[idx, 'Price_EUR'] = float(by_medians[(brand, year)])
                counter['brand_year'] += 1
            elif brand in brand_medians.index:
                self.df.at[idx, 'Price_EUR'] = float(brand_medians[brand])
                counter['brand_only'] += 1

        still_missing = int(self.df['Price_EUR'].isna().sum())
        print(
            f"impute_missing_prices: {counter['within_model']} within-model, "
            f"{counter['brand_year']} brand×year, {counter['brand_only']} brand-only, "
            f"{still_missing} still NaN",
            file=sys.stderr,
        )

    def _extract_with_regex(self, text, pattern):
        if pd.isna(text):
            return None
        match = re.findall(pattern, str(text))
        return match[0] if match else None

    def drop_old_columns(self):
        self.df = self.df.drop(
            columns=[
                'Network_', 'Network_Speed', 'Display_Type', 'Memory_', 'Main Camera_Features',
                'Main Camera_Video', 'Selfie camera_Video',
                'Sound_Loudspeaker', 'Sound_3.5mm jack', 'Comms_WLAN',
                'Comms_Bluetooth', 'Comms_Positioning', 'Comms_NFC', 'Comms_Radio',
                'Comms_USB', 'Misc_Colors',
                "Main Camera_Single", "Main Camera_Dual", "Main Camera_Triple", "Main Camera_Quad",
                "Main Camera_Dual or Triple", "Main Camera_Penta", "Main Camera_Five", "Selfie camera_Single",
                "Selfie camera_Dual", "Selfie camera_Triple", "Selfie camera_", "Main Camera", "Selfie camera",
                "Main Camera_",
                'Display_Size', 'Display_Resolution', 'Platform_OS', 'Platform_Chipset', 'Platform_CPU',
                'Platform_GPU',
                'Memory_Card slot', 'Misc_Models', 'Misc_Price', 'Memory_Internal',
                'Body_Dimensions', 'Body_Weight', 'Network_2G bands', 'Network_3G bands', 'Network_4G bands',
                'Network_5G bands', 'Battery_Type', 'Features_Sensors',
                'Body_Build', 'Selfie camera_Features', 'Display_Protection',
                'Battery_Charging', 'Display_', 'Misc_SAR', 'Network_GPRS',
                'Network_EDGE', 'Body_', 'Comms_Infrared port',
                'Battery_Stand-by', 'Battery_Talk time', 'Features_', 'Sound_',
                'Battery_Music play', 'Platform', 'Memory_Phonebook', 'Memory_Call records',
                'Features_Messaging', 'Features_Games', 'Features_Java', 'Misc_SAR EU', 'Body_Keyboard',
                'Features_Browser', 'Sound_Alert types', 'Features_Clock', 'Features_Alarm', 'Features_Languages',
            ])

    def save_processed_data(self, file_name=str(DATA_DIR / 'processed_data.csv')):
        # Save the processed DataFrame to a CSV file
        self.df.to_csv(file_name, index=False)

    def final_adjustments(self):
        self.df['Launch_Announced'] = self.df['Launch_Announced'].replace('Not announced yet', np.nan)
        self.df['year'] = self.df['Launch_Announced'].str.extract(r'(\d{4})')
        self.df = self.df[self.df['year'].astype(float) > 2010]
        self.df['Launch_Status'] = self.df['Launch_Status'].apply(self._normalize_launch_status)
        self.df['Resolution_Pixels'] = self.df['Resolution_Pixels'].fillna('0 x 0')
        self.df['Resolution_Pixels'] = self.df['Resolution_Pixels'].astype(str)
        self.df['Resolution_Pixels'] = self.df['Resolution_Pixels'].apply(
            lambda x: int(x.split(' x ')[0]) * int(x.split(' x ')[1]) if x != 'nan' else np.nan)
        self.df['Screen_To_Body_Ratio'] = pd.to_numeric(self.df['Screen_To_Body_Ratio'], errors='coerce')
        self.df['PPI_Density'] = pd.to_numeric(self.df['PPI_Density'], errors='coerce')

    @staticmethod
    def _normalize_launch_status(value):
        if not isinstance(value, str):
            return None
        v = value.strip().lower()
        if v.startswith('available'): return 'Available'
        if 'discontinued' in v:        return 'Discontinued'
        if 'cancel' in v:              return 'Canceled'
        if 'rumor' in v or 'coming' in v: return 'Rumored'
        return None

    def year_to_int(self):
        int_year = []
        for x in list(self.df['year']):
            m = int(x)
            int_year.append(m)
        self.df['year'] = int_year

    def process(self, extra_data=None):
        self.process_main_camera_columns()
        self.process_selfie_camera_columns()
        self.process_camera_resolutions()
        self.process_video_resolution()
        self.camera_features_listing()
        self.weight_process()
        self.demintions_process()
        self.network_tech_process()
        self.battery_capacity_process()
        self.sensors_process()
        self.SIM_process()
        self.extract_display_characteristics()
        self.extract_resolution_details()
        self.extract_base_os()
        self.extract_os_version()
        self.extract_chipset_manufacturer()
        self.extract_cpu_core_count()
        self.preprocess_memory_card_slot()
        self.expand_memory_configurations(extraprice=extra_data)
        self.clean_and_extract_price()
        self.drop_old_columns()
        self.final_adjustments()
        self.year_to_int()
        self.canonicalize_brand()
        # Imputation must run AFTER canonicalize_brand so groupby keys are
        # consistent (e.g. 'alcatel' and 'Alcatel' don't form separate clusters).
        self.impute_missing_prices()
        return self.df


if __name__ == '__main__':
    extra = pd.read_csv(DATA_DIR / 'pricing.csv')
    data_processor = DataPreProcess(str(DATA_DIR / 'flattened_data.csv'))
    data_processor.process(extra)
    data_processor.save_processed_data(str(DATA_DIR / 'processed_data.csv'))
