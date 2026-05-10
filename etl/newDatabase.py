import ast
import hashlib
import os
import re
import sys
from pathlib import Path

# database_eng.py lives at the repo root (shared with backend/), not in etl/.
# When this module is run as `python etl/newDatabase.py`, sys.path[0] is etl/,
# so we add the parent dir explicitly so the import resolves.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import (
    CheckConstraint, Column, Float, ForeignKey, Integer, MetaData, String,
    UniqueConstraint, text,
)
from sqlalchemy.orm import declarative_base, relationship

from database_eng import *  # noqa: F401,F403 — provides create_table, create_schema

DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv()

Base = declarative_base()
def require_env(name):
    value = os.getenv(name)
    if value is None or value.strip() == "":
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def normalize_lookup_value(value):
    if pd.isna(value):
        return '__missing__'

    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value).strip().casefold()

    if number.is_integer():
        return str(int(number))

    return format(number, 'g')


def extract_numeric_value(value):
    if pd.isna(value):
        return None

    match = re.search(r'-?\d+(\.\d+)?', str(value))
    if not match:
        return None

    number = float(match.group())
    if number.is_integer():
        return int(number)
    return number


def extract_integer_value(value):
    number = extract_numeric_value(value)
    if number is None:
        return None
    return int(number)


def extract_memory_gb(value):
    """Parse a memory token like '768MB', '1.5 GB', '1TB' to integer GB.

    The cleaner preserves the unit suffix in processed_data.csv. The naive
    `extract_integer_value` strips the unit, so '768MB' silently became
    `ram_gb=768` and '1TB' became `internal_storage_gb=1`. This function
    converts MB→GB by /1024 and TB→GB by *1024. Any positive sub-GB value
    floors to 1 to satisfy the `> 0` CHECK constraint; unparseable input
    returns None so the row's platform_id resolves to NULL under the
    nullable-FK schema.
    """
    if pd.isna(value):
        return None
    match = re.search(r'(\d+(?:\.\d+)?)\s*(TB|GB|MB)\b', str(value), re.IGNORECASE)
    if not match:
        return None
    quantity = float(match.group(1))
    unit = match.group(2).upper()
    if unit == 'TB':
        gb = quantity * 1024
    elif unit == 'GB':
        gb = quantity
    else:  # MB
        gb = quantity / 1024
    if gb <= 0:
        return None
    if gb < 1:
        return 1
    return int(round(gb))


def extract_camera_resolution(value):
    if pd.isna(value):
        return None

    matches = [float(match.group()) for match in re.finditer(r'-?\d+(?:\.\d+)?', str(value))]
    if not matches:
        return None

    number = max(matches)
    if number.is_integer():
        return int(number)
    return number


def clean_text_value(value, lowercase=False):
    if pd.isna(value):
        return None

    text_value = re.sub(r'\s+', ' ', str(value)).strip()
    if not text_value or text_value.casefold() == 'nan':
        return None

    if lowercase:
        return text_value.casefold()

    return text_value


_WATCH_TOKENS = ('watch', 'gear ', 'fitbit')
_TABLET_TOKENS = ('tab ', 'tab a', 'tab s', 'tab pro', 'tab plus', 'tab active', 'ipad', 'matepad', 'mediapad', 'mipad', 'mi pad')
_BAND_TOKENS = ('band', 'mi band', 'smart band')


def derive_form_factor(model):
    """Derive a form-factor enum from the model string.

    Matches against case-folded model name. Returns one of:
    'watch', 'tablet', 'band', 'phone' (default), 'other'.

    Order matters — 'watch' wins over 'band' for things like 'Galaxy Watch
    Active Band'. We default to 'phone' rather than 'other' because the vast
    majority of GSMArena entries are phones; reserve 'other' for explicit use.
    """
    if pd.isna(model):
        return 'other'
    text = str(model).casefold()
    if any(token in text for token in _WATCH_TOKENS):
        return 'watch'
    if any(token in text for token in _TABLET_TOKENS):
        return 'tablet'
    if any(token in text for token in _BAND_TOKENS):
        return 'band'
    return 'phone'


def parse_sensor_list(value):
    if pd.isna(value):
        return []

    text_value = str(value).strip()
    if not text_value:
        return []

    try:
        parsed = ast.literal_eval(text_value)
    except (ValueError, SyntaxError):
        parsed = text_value.strip('[]').split(',')

    if not isinstance(parsed, (list, tuple, set)):
        parsed = [parsed]

    cleaned = []
    seen = set()
    for item in parsed:
        item_text = clean_text_value(str(item).strip().strip("'\""), lowercase=True)
        if item_text and item_text not in seen:
            seen.add(item_text)
            cleaned.append(item_text)

    return cleaned


def normalize_lookup_frame(df, columns):
    normalized = df.copy()
    for column in columns:
        normalized[column] = normalized[column].map(normalize_lookup_value)
    return normalized


def attach_lookup_id(dataframe, mapping, keys, id_column):
    left = normalize_lookup_frame(dataframe[keys], keys)
    right = normalize_lookup_frame(mapping[keys + [id_column]].drop_duplicates(subset=keys), keys)
    merged = left.merge(right[keys + [id_column]], on=keys, how='left')
    result = dataframe.copy()
    result[id_column] = merged[id_column]
    return result


def build_lookup_signature(dataframe, columns):
    normalized = normalize_lookup_frame(dataframe[columns], columns)
    joined = normalized[columns].astype(str).agg('|'.join, axis=1)
    return joined.map(lambda value: hashlib.sha256(value.encode('utf-8')).hexdigest())


def drop_all_database_tables(engine):
    metadata = MetaData()
    metadata.reflect(bind=engine)

    if not metadata.tables:
        return

    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        metadata.drop_all(bind=conn)
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))

class CreateTable:
    def __init__(self, database_name, username, password, host, port=3306, recreate_database=True, reset_tables=True):
        if recreate_database:
            engine = create_schema(username, password, host=host, port=port)
            with engine.begin() as conn:
                conn.execute(text(f"DROP DATABASE IF EXISTS `{database_name}`"))
                conn.execute(text(f"CREATE DATABASE `{database_name}`"))

        engine = create_table(username, password, database_name, host=host, port=port)
        if recreate_database or reset_tables:
            drop_all_database_tables(engine)
        Base.metadata.create_all(bind=engine, checkfirst=True)
 
#MAIN
class DeviceName(Base):
    __tablename__ = 'Device_Name'
    __table_args__ = (UniqueConstraint('brand', 'model', name='uq_device_name_brand_model'),)
    id = Column(Integer, primary_key=True,autoincrement=True)
    brand = Column(String(255), nullable=False)
    model = Column(String(255), nullable=False)

#MAIN
class NetworkTechnology(Base):
    __tablename__ = 'Network_Technology'
    __table_args__ = (UniqueConstraint('technology', name='uq_network_technology_name'),)
    id = Column(Integer, primary_key=True,autoincrement=True)
    technology = Column(String(255), nullable=False)

#MAIN
class Sim(Base):
    __tablename__ = 'Sim'
    __table_args__ = (
        UniqueConstraint('sim_count', 'sim_type', name='uq_sim_pair'),
        CheckConstraint("sim_count IN ('single', 'dual', 'triple', 'none')", name='ck_sim_count_valid'),
    )
    id = Column(Integer, primary_key=True,autoincrement=True)
    sim_count = Column(String(32), nullable=False)
    sim_type = Column(String(32), nullable=False)

#MAIN
class Camera(Base):
    __tablename__ = 'Camera'
    __table_args__ = (
        UniqueConstraint('main_cameras_num', 'selfie_cameras_num', 'highest_maincam_res', 'highest_selfiecam_res', name='uq_camera_profile'),
        CheckConstraint('main_cameras_num >= 0', name='ck_main_cameras_num_min'),
        CheckConstraint('selfie_cameras_num >= 0', name='ck_selfie_cameras_num_min'),
        CheckConstraint('highest_maincam_res > 0', name='ck_highest_maincam_res_pos'),
        CheckConstraint('highest_selfiecam_res > 0', name='ck_highest_selfiecam_res_pos'),
    )
    id = Column(Integer, primary_key=True,autoincrement=True)
    main_cameras_num = Column(Integer, nullable=False)
    selfie_cameras_num = Column(Integer, nullable=False)
    highest_maincam_res = Column(Float)
    highest_selfiecam_res = Column(Float)
    
    
#MAIN
class Display(Base):
    __tablename__ = 'Display'
    __table_args__ = (
        UniqueConstraint('display_size_inch', 'resolution_pixels', 'resolution_ratio', 'ppi_density', name='uq_display_profile'),
        CheckConstraint('display_size_inch > 0', name='ck_display_size_inch_pos'),
        CheckConstraint('display_size_cm > 0', name='ck_display_size_cm_pos'),
        CheckConstraint('ppi_density > 0', name='ck_ppi_density_pos'),
        CheckConstraint('screen_to_body_ratio >= 0', name='ck_screen_to_body_ratio_range'),
    )
    id = Column(Integer, primary_key=True,autoincrement=True)
    display_size_inch = Column(Float, nullable=False)
    display_size_cm = Column(Float)
    screen_to_body_ratio = Column(Float)
    resolution_pixels = Column(Integer, nullable=False)
    resolution_ratio = Column(String(32))
    ppi_density = Column(Float)
    
#MAIN
class Os(Base):
    __tablename__ = 'OS'
    __table_args__ = (UniqueConstraint('os_name', 'os_version', name='uq_os_pair'),)
    id = Column(Integer, primary_key=True,autoincrement=True)
    os_name = Column(String(255), nullable=False)
    os_version = Column(String(255))

#MAIN
class Platform(Base):
    __tablename__ = 'Platform'
    __table_args__ = (
        UniqueConstraint('chipset_manufacturer', 'cpu_core_count', 'internal_storage_gb', 'ram_gb', name='uq_platform_profile'),
        CheckConstraint('ram_gb > 0', name='ck_ram_gb_pos'),
        CheckConstraint('internal_storage_gb > 0', name='ck_internal_storage_gb_pos'),
        CheckConstraint('cpu_core_count > 0', name='ck_cpu_core_count_pos'),
    )
    id = Column(Integer, primary_key=True,autoincrement=True)
    chipset_manufacturer = Column(String(255), nullable=False)
    cpu_core_count = Column(Integer, nullable=False)
    internal_storage_gb = Column(Integer, nullable=False)
    ram_gb = Column(Integer, nullable=False)
    
    
class Device(Base):
    __tablename__ = 'Device'
    __table_args__ = (
        UniqueConstraint('device_key', name='uq_device_key'),
        CheckConstraint('price_eur >= 0', name='ck_price_eur_min'),
        CheckConstraint('year BETWEEN 1995 AND 2030', name='ck_year_range'),
        CheckConstraint('battery_capacity_mah > 0', name='ck_battery_capacity_pos'),
        CheckConstraint('weight > 0', name='ck_weight_pos'),
        CheckConstraint('length > 0', name='ck_length_pos'),
        CheckConstraint('width > 0', name='ck_width_pos'),
        CheckConstraint('height > 0', name='ck_height_pos'),
        CheckConstraint('volume > 0', name='ck_volume_pos'),
        CheckConstraint("launch_status IN ('Available', 'Discontinued', 'Rumored', 'Canceled')", name='ck_launch_status_valid'),
        CheckConstraint("form_factor IN ('phone', 'watch', 'tablet', 'band', 'other')", name='ck_form_factor_valid'),
    )
    id = Column(Integer, primary_key=True,autoincrement=True)
    device_key = Column(String(64), nullable=False)
    device_name_id = Column(Integer, ForeignKey('Device_Name.id', onupdate='CASCADE', ondelete='RESTRICT'))
    network_technology_id = Column(Integer, ForeignKey('Network_Technology.id', onupdate='CASCADE', ondelete='RESTRICT'))
    year = Column(Integer, nullable=False)
    launch_status = Column(String(255))
    battery_capacity_mah = Column(Integer)
    camera_id = Column(Integer, ForeignKey('Camera.id', onupdate='CASCADE', ondelete='RESTRICT'))
    display_id = Column(Integer, ForeignKey('Display.id', onupdate='CASCADE', ondelete='RESTRICT'))
    weight = Column(Float)
    length = Column(Float)
    width = Column(Float)
    height = Column(Float)
    volume = Column(Float)
    os_id = Column(Integer, ForeignKey('OS.id', onupdate='CASCADE', ondelete='RESTRICT'))
    platform_id = Column(Integer, ForeignKey('Platform.id', onupdate='CASCADE', ondelete='RESTRICT'))
    sim_id = Column(Integer, ForeignKey('Sim.id', onupdate='CASCADE', ondelete='RESTRICT'))
    price_eur = Column(Float)
    form_factor = Column(String(16), nullable=False, server_default='phone')


class AddToTable:
    def __init__(self, database_name=None, username=None, password=None, host=None, port=None):
        database_name = database_name or require_env('DB_NAME')
        username = username or require_env('DB_USER')
        password = password or require_env('DB_PASSWORD')
        host = host or require_env('DB_HOST')
        port = int(port or require_env('DB_PORT'))
        self.engine = create_table(username, password, database_name, host=host, port=port)
        self.connection = self.engine
        self._source_dataframe = None

    def append_new_rows(self, table_name, dataframe, key_columns):
        dataframe = dataframe.copy()
        dataframe = dataframe.loc[~dataframe[key_columns].isna().all(axis=1)].copy().reset_index(drop=True)
        if dataframe.empty:
            return

        normalized_keys = normalize_lookup_frame(dataframe[key_columns], key_columns)
        dataframe = dataframe.loc[~normalized_keys.duplicated()].copy().reset_index(drop=True)
        normalized_keys = normalize_lookup_frame(dataframe[key_columns], key_columns)

        existing_query = f"SELECT {', '.join(f'`{column}`' for column in key_columns)} FROM `{table_name}`"
        existing = pd.read_sql(existing_query, con=self.connection)

        if not existing.empty:
            left_keys = normalized_keys
            right_keys = normalize_lookup_frame(existing[key_columns], key_columns).drop_duplicates()
            right_keys['_exists'] = True
            merged = left_keys.merge(right_keys, on=key_columns, how='left')
            dataframe = dataframe.loc[merged['_exists'].isna()].copy()

        if not dataframe.empty:
            dataframe.to_sql(table_name, con=self.connection, if_exists='append', index=False)

    def load_source_dataframe(self):
        if self._source_dataframe is not None:
            return self._source_dataframe.copy()

        dataframe = pd.read_csv(DATA_DIR / 'processed_data.csv').rename(columns={
            'Number of main cameras': 'main_cameras_num',
            'Number of selfie cameras': 'selfie_cameras_num',
            'Body_SIM': 'body_sim',
            'SIM_type': 'sim_type',
            'SIM_count': 'sim_count',
            'Network_Technology': 'network_technology',
            'Launch_Status': 'launch_status',
            'Battery_capacity': 'battery_capacity_mah',
            'Display_Size_Inch': 'display_size_inch',
            'Display_Size_Cm': 'display_size_cm',
            'Screen_To_Body_Ratio': 'screen_to_body_ratio',
            'Resolution_Pixels': 'resolution_pixels',
            'Resolution_Ratio': 'resolution_ratio',
            'PPI_Density': 'ppi_density',
            'base_os': 'os_name',
            'OS_Version': 'os_version',
            'Chipset_Manufacturer': 'chipset_manufacturer',
            'CPU_Core_Count': 'cpu_core_count',
            'Highest_maincam_res': 'highest_maincam_res',
            'Highest_selfiecam_res': 'highest_selfiecam_res',
            'Price_EUR': 'price_eur',
            'Sensors': 'sensor_payload',
        })

        required_columns = [
            'brand',
            'model',
            'body_sim',
            'sim_type',
            'sim_count',
            'network_technology',
            'launch_status',
            'main_cameras_num',
            'selfie_cameras_num',
            'highest_maincam_res',
            'highest_selfiecam_res',
            'weight',
            'length',
            'width',
            'height',
            'volume',
            'battery_capacity_mah',
            'display_size_inch',
            'display_size_cm',
            'screen_to_body_ratio',
            'resolution_pixels',
            'resolution_ratio',
            'ppi_density',
            'os_name',
            'os_version',
            'chipset_manufacturer',
            'cpu_core_count',
            'Storage',
            'RAM',
            'price_eur',
            'sensor_payload',
            '2G',
            '3G',
            '4G',
            '5G',
            'year',
        ]
        missing_columns = [column for column in required_columns if column not in dataframe.columns]
        if missing_columns:
            raise ValueError(f"processed_data.csv is missing required columns: {missing_columns}")

        for source_column, target_column in [('2G', 'supports_2g'), ('3G', 'supports_3g'), ('4G', 'supports_4g'), ('5G', 'supports_5g')]:
            dataframe[target_column] = dataframe[source_column].map(extract_integer_value).fillna(0).astype(int)

        for column in ['main_cameras_num', 'selfie_cameras_num', 'battery_capacity_mah', 'resolution_pixels', 'year', 'cpu_core_count']:
            dataframe[column] = dataframe[column].map(extract_integer_value)

        for column in ['highest_maincam_res', 'highest_selfiecam_res']:
            dataframe[column] = dataframe[column].map(extract_camera_resolution)

        for column in ['display_size_inch', 'display_size_cm', 'screen_to_body_ratio', 'ppi_density', 'weight', 'length', 'width', 'height', 'volume', 'price_eur']:
            dataframe[column] = dataframe[column].map(extract_numeric_value)

        dataframe['internal_storage_gb'] = dataframe['Storage'].map(extract_memory_gb)
        dataframe['ram_gb'] = dataframe['RAM'].map(extract_memory_gb)
        dataframe['sensor_names'] = dataframe['sensor_payload'].map(parse_sensor_list)
        dataframe['resolution_ratio'] = dataframe['resolution_ratio'].map(clean_text_value)

        string_columns = [
            'brand',
            'model',
            'body_sim',
            'network_technology',
            'launch_status',
            'os_name',
            'os_version',
            'chipset_manufacturer',
            'cpu_core_count',
        ]
        for column in string_columns:
            dataframe[column] = dataframe[column].map(clean_text_value)

        for column in ['sim_type', 'sim_count']:
            dataframe[column] = dataframe[column].map(lambda value: clean_text_value(value, lowercase=True))

        dataframe['form_factor'] = dataframe['model'].map(derive_form_factor)

        self._source_dataframe = dataframe.copy()
        return dataframe

    def addDeviceName(self):
        device_name_df = self.load_source_dataframe()[['brand', 'model']].drop_duplicates().reset_index(drop=True)
        self.append_new_rows('Device_Name', device_name_df, ['brand', 'model'])

    def addNetworkTechnology(self):
        tech_df = self.load_source_dataframe()[['network_technology']].rename(columns={'network_technology': 'technology'})
        tech_df = tech_df.drop_duplicates().reset_index(drop=True)
        self.append_new_rows('Network_Technology', tech_df, ['technology'])

    def addSim(self):
        unique_keys = ['sim_count', 'sim_type']
        sim_df = self.load_source_dataframe()[unique_keys].dropna(subset=unique_keys).drop_duplicates(subset=unique_keys).reset_index(drop=True)
        self.append_new_rows('Sim', sim_df, unique_keys)

    def addcamera(self):
        camera_df = self.load_source_dataframe()[['main_cameras_num', 'selfie_cameras_num', 'highest_maincam_res', 'highest_selfiecam_res']].drop_duplicates().reset_index(drop=True)
        for column in ['main_cameras_num', 'selfie_cameras_num']:
            camera_df[column] = camera_df[column].astype('Int64')
        self.append_new_rows('Camera', camera_df, ['main_cameras_num', 'selfie_cameras_num', 'highest_maincam_res', 'highest_selfiecam_res'])
    
    def addDisplay(self):
        unique_keys = ['display_size_inch', 'resolution_pixels', 'resolution_ratio', 'ppi_density']
        display_df = self.load_source_dataframe()[['display_size_inch', 'display_size_cm', 'screen_to_body_ratio', 'resolution_pixels', 'resolution_ratio', 'ppi_density']].drop_duplicates(subset=unique_keys).reset_index(drop=True)
        display_df['resolution_pixels'] = display_df['resolution_pixels'].astype('Int64')
        self.append_new_rows('Display', display_df, unique_keys)
    
    def addOs(self):
        os_df = self.load_source_dataframe()[['os_name', 'os_version']].drop_duplicates().reset_index(drop=True)
        self.append_new_rows('OS', os_df, ['os_name', 'os_version'])
    
    def addPlatform(self):
        unique_keys = ['chipset_manufacturer', 'cpu_core_count', 'internal_storage_gb', 'ram_gb']
        platform_df = self.load_source_dataframe()[unique_keys].dropna(subset=unique_keys).drop_duplicates(subset=unique_keys).reset_index(drop=True)
        for column in ['cpu_core_count', 'internal_storage_gb', 'ram_gb']:
            platform_df[column] = pd.to_numeric(platform_df[column], errors='coerce').astype('Int64')
        self.append_new_rows('Platform', platform_df, unique_keys)

    def report_unresolved_device_lookups(self, device_df):
        required_columns = ['device_name_id', 'network_technology_id', 'camera_id', 'display_id', 'os_id', 'platform_id', 'sim_id']
        missing_required = {column: int(device_df[column].isna().sum()) for column in required_columns if device_df[column].isna().any()}
        if missing_required:
            raise ValueError(f"Required device lookups failed to resolve: {missing_required}")

    def build_device_records(self):
        data = self.load_source_dataframe()
        dedupe_columns = [column for column in data.columns if column != 'sensor_names']
        data = data.drop_duplicates(subset=dedupe_columns).reset_index(drop=True)

        camera_mapping = pd.read_sql('SELECT * FROM Camera', con=self.connection).rename(columns={'id': 'camera_id'})
        name_mapping = pd.read_sql('SELECT * FROM Device_Name', con=self.connection).rename(columns={'id': 'device_name_id'})
        os_mapping = pd.read_sql('SELECT id AS os_id, os_name, os_version FROM OS', con=self.connection)
        platform_mapping = pd.read_sql('SELECT id AS platform_id, chipset_manufacturer, cpu_core_count, internal_storage_gb, ram_gb FROM Platform', con=self.connection)
        network_technology_mapping = pd.read_sql('SELECT id AS network_technology_id, technology AS network_technology FROM Network_Technology', con=self.connection)
        sim_mapping = pd.read_sql('SELECT id AS sim_id, sim_count, sim_type FROM Sim', con=self.connection)
        display_mapping = pd.read_sql('SELECT id AS display_id, display_size_inch, display_size_cm, screen_to_body_ratio, resolution_pixels, resolution_ratio, ppi_density FROM Display', con=self.connection)

        data = attach_lookup_id(data, sim_mapping, ['sim_count', 'sim_type'], 'sim_id')
        data = attach_lookup_id(data, network_technology_mapping, ['network_technology'], 'network_technology_id')
        data = attach_lookup_id(data, name_mapping, ['brand', 'model'], 'device_name_id')
        data = attach_lookup_id(data, platform_mapping, ['chipset_manufacturer', 'cpu_core_count', 'internal_storage_gb', 'ram_gb'], 'platform_id')
        data = attach_lookup_id(data, os_mapping, ['os_name', 'os_version'], 'os_id')
        data = attach_lookup_id(
            data,
            camera_mapping,
            ['main_cameras_num', 'selfie_cameras_num', 'highest_maincam_res', 'highest_selfiecam_res'],
            'camera_id',
        )
        data = attach_lookup_id(
            data,
            display_mapping,
            ['display_size_inch', 'resolution_pixels', 'resolution_ratio', 'ppi_density'],
            'display_id',
        )

        device_columns = ['device_name_id', 'network_technology_id', 'year', 'launch_status', 'battery_capacity_mah', 'camera_id', 'display_id', 'weight', 'length', 'width', 'height', 'volume', 'os_id', 'platform_id', 'sim_id', 'price_eur', 'form_factor']
        device_df = data[device_columns].copy()
        device_df['device_key'] = build_lookup_signature(device_df, device_columns)

        id_columns = ['device_name_id', 'network_technology_id', 'camera_id', 'display_id', 'os_id', 'platform_id', 'sim_id']
        for column in id_columns:
            device_df[column] = device_df[column].astype('Int64')

        for column in ['year', 'battery_capacity_mah']:
            device_df[column] = device_df[column].astype('Int64')

        return device_df

    def addDevice(self):
        device_df = self.build_device_records()
        nullable_fks = ['device_name_id', 'network_technology_id', 'camera_id', 'display_id', 'os_id', 'platform_id', 'sim_id']
        unresolved_per_fk = {fk: int(device_df[fk].isna().sum()) for fk in nullable_fks if device_df[fk].isna().any()}
        if unresolved_per_fk:
            total_with_gaps = int(device_df[nullable_fks].isna().any(axis=1).sum())
            print(f"Loading {total_with_gaps} device rows with at least one NULL dim FK (per-column NaN counts: {unresolved_per_fk})")
        device_columns = ['device_name_id', 'network_technology_id', 'year', 'launch_status', 'battery_capacity_mah', 'camera_id', 'display_id', 'weight', 'length', 'width', 'height', 'volume', 'os_id', 'platform_id', 'sim_id', 'price_eur', 'form_factor']
        self.append_new_rows('Device', device_df[['device_key'] + device_columns], ['device_key'])

    def addAll(self):
        with self.engine.begin() as conn:
            self.connection = conn
            try:
                self.addDeviceName()
                self.addNetworkTechnology()
                self.addSim()
                self.addcamera()
                self.addDisplay()
                self.addOs()
                self.addPlatform()
                self.addDevice()
            finally:
                self.connection = self.engine



if __name__ == '__main__':
    db_name = require_env('DB_NAME')
    db_user = require_env('DB_USER')
    db_password = require_env('DB_PASSWORD')
    db_host = require_env('DB_HOST')
    db_port = int(require_env('DB_PORT'))
    recreate_database = os.getenv('RECREATE_DATABASE', 'true').lower() == 'true'
    reset_tables = os.getenv('RESET_TABLES', 'true').lower() == 'true'

    creator = CreateTable(
        db_name,
        db_user,
        db_password,
        host=db_host,
        port=db_port,
        recreate_database=recreate_database,
        reset_tables=reset_tables,
    )
    add = AddToTable(
        database_name=db_name,
        username=db_user,
        password=db_password,
        host=db_host,
        port=db_port,
    )
    add.addAll()

