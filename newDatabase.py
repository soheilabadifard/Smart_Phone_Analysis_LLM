import ast
import hashlib
import re

from sqlalchemy import Column, Integer, String, ForeignKey, text, Float, UniqueConstraint, MetaData
from sqlalchemy.orm import declarative_base, relationship
from database_eng import *
import pandas as pd
import os as os_module
from dotenv import load_dotenv

load_dotenv()

Base = declarative_base()
def require_env(name):
    value = os_module.getenv(name)
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
class device_name(Base):
    __tablename__ = 'Device_Name'
    __table_args__ = (UniqueConstraint('brand', 'model', name='uq_device_name_brand_model'),)
    id = Column(Integer, primary_key=True,autoincrement=True)
    brand = Column(String(255))
    model = Column(String(255))
    
class network_band(Base):
    __tablename__ = 'Network_Band'
    __table_args__ = (UniqueConstraint('supports_2g', 'supports_3g', 'supports_4g', 'supports_5g', name='uq_network_band_flags'),)
    id = Column(Integer, primary_key=True,autoincrement=True)
    supports_2g = Column(Integer)
    supports_3g = Column(Integer)
    supports_4g = Column(Integer)
    supports_5g = Column(Integer)
    
class technology(Base):
    __tablename__ = 'Technology'
    __table_args__ = (UniqueConstraint('technology', name='uq_technology_name'),)
    id = Column(Integer, primary_key=True,autoincrement=True)
    technology = Column(String(255))
    
#MAIN
class Network_Technology(Base):
    __tablename__ = 'Network_Technology'
    __table_args__ = (UniqueConstraint('technology_id', 'network_band_id', name='uq_network_technology_pair'),)
    id = Column(Integer, primary_key=True,autoincrement=True)
    technology_id = Column(Integer, ForeignKey('Technology.id'))
    network_band_id = Column(Integer, ForeignKey('Network_Band.id'))
    
class Launch_Announced(Base):
    __tablename__ = 'Launch_Announced'
    __table_args__ = (UniqueConstraint('launch_announced', name='uq_launch_announced_value'),)
    id = Column(Integer, primary_key=True,autoincrement=True)
    launch_announced = Column(String(255))
    
class Launch_Status(Base):
    __tablename__ = 'Launch_Status'
    __table_args__ = (UniqueConstraint('launch_status', name='uq_launch_status_value'),)
    id = Column(Integer, primary_key=True,autoincrement=True)
    launch_status = Column(String(255))
    
#MAIN
class launch(Base):
    __tablename__ = 'Launch'
    __table_args__ = (UniqueConstraint('announced_id', 'status_id', name='uq_launch_pair'),)
    id = Column(Integer, primary_key=True,autoincrement=True)
    announced_id = Column(Integer, ForeignKey('Launch_Announced.id'))
    status_id = Column(Integer, ForeignKey('Launch_Status.id'))

class year(Base):
    __tablename__ = 'Year'
    __table_args__ = (UniqueConstraint('year', name='uq_year_value'),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    year = Column(Integer)
      
#MAIN
class sim(Base):
    __tablename__ = 'Sim'
    __table_args__ = (UniqueConstraint('body_sim', 'sim_count', 'sim_type', name='uq_sim_triplet'),)
    id = Column(Integer, primary_key=True,autoincrement=True)
    body_sim = Column(String(255))
    sim_count = Column(String(32))
    sim_type = Column(String(32))

#MAIN
class camera(Base):
    __tablename__ = 'Camera'
    __table_args__ = (UniqueConstraint('main_cameras_num', 'selfie_cameras_num', 'highest_maincam_res', 'highest_selfiecam_res', name='uq_camera_profile'),)
    id = Column(Integer, primary_key=True,autoincrement=True)
    main_cameras_num = Column(Integer)
    selfie_cameras_num = Column(Integer)
    highest_maincam_res = Column(Float)
    highest_selfiecam_res = Column(Float)
    
    
#MAIN   
class battery(Base):
    __tablename__ = 'Battery'
    __table_args__ = (UniqueConstraint('battery_capacity_mah', name='uq_battery_capacity'),)
    id = Column(Integer, primary_key=True,autoincrement=True)
    battery_capacity_mah = Column(Integer)

class sensor(Base):
    __tablename__ = 'Sensor'
    __table_args__ = (UniqueConstraint('sensor_name', name='uq_sensor_name'),)
    id = Column(Integer, primary_key=True,autoincrement=True)
    sensor_name = Column(String(255))  

#MAIN   
class display(Base):
    __tablename__ = 'Display'
    __table_args__ = (UniqueConstraint('display_size_inch', 'display_size_cm', 'screen_to_body_ratio', 'resolution_pixels', 'resolution_ratio', 'ppi_density', name='uq_display_profile'),)
    id = Column(Integer, primary_key=True,autoincrement=True)
    display_size_inch = Column(Float)
    display_size_cm = Column(Float)
    screen_to_body_ratio = Column(Float)
    resolution_pixels = Column(Integer)
    resolution_ratio = Column(String(32))
    ppi_density = Column(Float)
    
class version(Base):
    __tablename__ = 'Version'
    __table_args__ = (UniqueConstraint('os_version', name='uq_version_value'),)
    id = Column(Integer, primary_key=True,autoincrement=True)
    os_version = Column(String(255)) 
    
class os_name(Base):
    __tablename__ = 'OS_Name'
    __table_args__ = (UniqueConstraint('os_name', name='uq_os_name_value'),)
    id = Column(Integer, primary_key=True,autoincrement=True)
    os_name = Column(String(255))  

#MAIN  
class os(Base):
    __tablename__ = 'OS'
    __table_args__ = (UniqueConstraint('name_id', 'version_id', name='uq_os_pair'),)
    id = Column(Integer, primary_key=True,autoincrement=True)
    name_id = Column(Integer, ForeignKey('OS_Name.id'))
    version_id = Column(Integer, ForeignKey('Version.id'))
    
class chipset(Base):
    __tablename__ = 'Chipset'
    __table_args__ = (UniqueConstraint('chipset_manufacturer', name='uq_chipset_manufacturer'),)
    id = Column(Integer, primary_key=True,autoincrement=True)
    chipset_manufacturer = Column(String(255))  
    
class cpu(Base):
    __tablename__ = 'Cpu'
    __table_args__ = (UniqueConstraint('cpu_core_count', name='uq_cpu_core_count'),)
    id = Column(Integer, primary_key=True,autoincrement=True)
    cpu_core_count = Column(String(255))  
    
class memory_profile(Base):
    __tablename__ = 'Memory_Profile'
    __table_args__ = (UniqueConstraint('internal_storage_gb', 'ram_gb', name='uq_memory_profile'),)
    id = Column(Integer, primary_key=True,autoincrement=True)
    internal_storage_gb = Column(Integer)
    ram_gb = Column(Integer)
    
#MAIN  
class platform(Base):
    __tablename__ = 'Platform'
    __table_args__ = (UniqueConstraint('chipset_id', 'cpu_id', 'memory_profile_id', name='uq_platform_triplet'),)
    id = Column(Integer, primary_key=True,autoincrement=True)
    chipset_id = Column(Integer, ForeignKey('Chipset.id'))
    cpu_id = Column(Integer, ForeignKey('Cpu.id'))
    memory_profile_id = Column(Integer, ForeignKey('Memory_Profile.id'))
    
    
class Device(Base):
    __tablename__ = 'Device'
    __table_args__ = (UniqueConstraint('device_key', name='uq_device_key'),)
    id = Column(Integer, primary_key=True,autoincrement=True)
    device_key = Column(String(64), nullable=False)
    device_name_id = Column(Integer, ForeignKey('Device_Name.id'))
    network_technology_id = Column(Integer, ForeignKey('Network_Technology.id'), nullable=True)
    launch_id = Column(Integer, ForeignKey('Launch.id'))
    year_id = Column(Integer, ForeignKey('Year.id'))
    camera_id = Column(Integer, ForeignKey('Camera.id'))
    battery_id = Column(Integer, ForeignKey('Battery.id'), nullable=True)
    display_id = Column(Integer, ForeignKey('Display.id'), nullable=True)
    weight = Column(Float)
    length = Column(Float)
    width = Column(Float)
    height = Column(Float)
    volume = Column(Float)
    os_id = Column(Integer, ForeignKey('OS.id'), nullable=True)
    platform_id = Column(Integer, ForeignKey('Platform.id'), nullable=True)
    sim_id = Column(Integer, ForeignKey('Sim.id'), nullable=True)
    price_eur = Column(Float)


class device_sensor(Base):
    __tablename__ = 'Device_Sensor'
    __table_args__ = (UniqueConstraint('device_id', 'sensor_id', name='uq_device_sensor_pair'),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey('Device.id'))
    sensor_id = Column(Integer, ForeignKey('Sensor.id'))


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
        self._device_records = None

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

        dataframe = pd.read_csv('./processed_data.csv').rename(columns={
            'Number of main cameras': 'main_cameras_num',
            'Number of selfie cameras': 'selfie_cameras_num',
            'Body_SIM': 'body_sim',
            'SIM_type': 'sim_type',
            'SIM_count': 'sim_count',
            'Network_Technology': 'network_technology',
            'Launch_Announced': 'launch_announced',
            'Launch_Status': 'launch_status',
            'Battery_capactiy': 'battery_capacity_mah',
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
            'launch_announced',
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

        for column in ['main_cameras_num', 'selfie_cameras_num', 'battery_capacity_mah', 'resolution_pixels', 'year']:
            dataframe[column] = dataframe[column].map(extract_integer_value)

        for column in ['highest_maincam_res', 'highest_selfiecam_res']:
            dataframe[column] = dataframe[column].map(extract_camera_resolution)

        for column in ['display_size_inch', 'display_size_cm', 'screen_to_body_ratio', 'ppi_density', 'weight', 'length', 'width', 'height', 'volume', 'price_eur']:
            dataframe[column] = dataframe[column].map(extract_numeric_value)

        dataframe['internal_storage_gb'] = dataframe['Storage'].map(extract_integer_value)
        dataframe['ram_gb'] = dataframe['RAM'].map(extract_integer_value)
        dataframe['sensor_names'] = dataframe['sensor_payload'].map(parse_sensor_list)
        dataframe['resolution_ratio'] = dataframe['resolution_ratio'].map(clean_text_value)

        string_columns = [
            'brand',
            'model',
            'body_sim',
            'network_technology',
            'launch_announced',
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

        self._source_dataframe = dataframe.copy()
        return dataframe

    def addDeviceName(self):
        device_name = self.load_source_dataframe()[['brand', 'model']].drop_duplicates().reset_index(drop=True)
        self.append_new_rows('Device_Name', device_name, ['brand', 'model'])

    def addNetworkBand(self):
        bands = self.load_source_dataframe()[['supports_2g', 'supports_3g', 'supports_4g', 'supports_5g']].drop_duplicates().reset_index(drop=True)
        self.append_new_rows('Network_Band', bands, ['supports_2g', 'supports_3g', 'supports_4g', 'supports_5g'])

    def addTechnology(self):
        technology_df = self.load_source_dataframe()[['network_technology']].rename(columns={'network_technology': 'technology'})
        technology_df = technology_df.drop_duplicates().reset_index(drop=True)
        self.append_new_rows('Technology', technology_df, ['technology'])

    def addNetworkTechnology(self):
        result_df = self.load_source_dataframe()[['network_technology', 'supports_2g', 'supports_3g', 'supports_4g', 'supports_5g']].drop_duplicates().reset_index(drop=True)

        band_mapping = pd.read_sql('SELECT * FROM Network_Band', con=self.connection).rename(columns={'id': 'network_band_id'})
        technology_mapping = pd.read_sql('SELECT * FROM Technology', con=self.connection).rename(columns={'id': 'technology_id'})

        result_df = attach_lookup_id(result_df, band_mapping, ['supports_2g', 'supports_3g', 'supports_4g', 'supports_5g'], 'network_band_id')
        result_df = attach_lookup_id(result_df, technology_mapping.rename(columns={'technology': 'network_technology'}), ['network_technology'], 'technology_id')
        result_df = result_df[['technology_id', 'network_band_id']].drop_duplicates().reset_index(drop=True)

        for column in ['technology_id', 'network_band_id']:
            result_df[column] = result_df[column].astype('Int64')

        self.append_new_rows('Network_Technology', result_df, ['technology_id', 'network_band_id'])

    def addLaunch_Announced(self):
        launch_announced = self.load_source_dataframe()[['launch_announced']]
        launch_announced = launch_announced.drop_duplicates().reset_index(drop=True)
        self.append_new_rows('Launch_Announced', launch_announced, ['launch_announced'])

    def addLaunch_Status(self):
        launch_status = self.load_source_dataframe()[['launch_status']]
        launch_status = launch_status.drop_duplicates().reset_index(drop=True)
        self.append_new_rows('Launch_Status', launch_status, ['launch_status'])

    def addLaunch(self):
        launch_df = self.load_source_dataframe()[['launch_announced', 'launch_status']].drop_duplicates().reset_index(drop=True)
        announced_mapping = pd.read_sql('SELECT id AS announced_id, launch_announced FROM Launch_Announced', con=self.connection)
        status_mapping = pd.read_sql('SELECT id AS status_id, launch_status FROM Launch_Status', con=self.connection)

        launch_df = attach_lookup_id(launch_df, announced_mapping, ['launch_announced'], 'announced_id')
        launch_df = attach_lookup_id(launch_df, status_mapping, ['launch_status'], 'status_id')
        launch_df = launch_df[['announced_id', 'status_id']].drop_duplicates().reset_index(drop=True)

        for column in ['announced_id', 'status_id']:
            launch_df[column] = launch_df[column].astype('Int64')

        self.append_new_rows('Launch', launch_df, ['announced_id', 'status_id'])

    def addSim(self):
        sim_df = self.load_source_dataframe()[['body_sim', 'sim_count', 'sim_type']].drop_duplicates().reset_index(drop=True)
        self.append_new_rows('Sim', sim_df, ['body_sim', 'sim_count', 'sim_type'])

    def addYear(self):
        year_df = self.load_source_dataframe()[['year']].dropna().drop_duplicates().reset_index(drop=True)
        year_df['year'] = year_df['year'].astype('Int64')
        self.append_new_rows('Year', year_df, ['year'])

    def addSensor(self):
        source = self.load_source_dataframe()
        sensor_values = sorted({sensor_name for sensor_list in source['sensor_names'] for sensor_name in sensor_list})
        sensor_df = pd.DataFrame({'sensor_name': sensor_values})
        self.append_new_rows('Sensor', sensor_df, ['sensor_name'])

    def addVersion(self):
        version_df = self.load_source_dataframe()[['os_version']].drop_duplicates().reset_index(drop=True)
        self.append_new_rows('Version', version_df, ['os_version'])

    def addos_name(self):
        os_name_df = self.load_source_dataframe()[['os_name']].drop_duplicates().reset_index(drop=True)
        self.append_new_rows('OS_Name', os_name_df, ['os_name'])

    def addChipset(self):
        chipset_df = self.load_source_dataframe()[['chipset_manufacturer']].drop_duplicates().reset_index(drop=True)
        self.append_new_rows('Chipset', chipset_df, ['chipset_manufacturer'])

    def addCpu(self):
        cpu_df = self.load_source_dataframe()[['cpu_core_count']].drop_duplicates().reset_index(drop=True)
        self.append_new_rows('Cpu', cpu_df, ['cpu_core_count'])

    def addMemoryProfile(self):
        memory_df = self.load_source_dataframe()[['internal_storage_gb', 'ram_gb']].drop_duplicates().reset_index(drop=True)
        for column in ['internal_storage_gb', 'ram_gb']:
            memory_df[column] = memory_df[column].astype('Int64')
        self.append_new_rows('Memory_Profile', memory_df, ['internal_storage_gb', 'ram_gb'])

    def addBattery(self):
        battery_df = self.load_source_dataframe()[['battery_capacity_mah']].drop_duplicates().reset_index(drop=True)
        battery_df['battery_capacity_mah'] = battery_df['battery_capacity_mah'].astype('Int64')
        self.append_new_rows('Battery', battery_df, ['battery_capacity_mah'])
    
    def addcamera(self):
        camera_df = self.load_source_dataframe()[['main_cameras_num', 'selfie_cameras_num', 'highest_maincam_res', 'highest_selfiecam_res']].drop_duplicates().reset_index(drop=True)
        for column in ['main_cameras_num', 'selfie_cameras_num']:
            camera_df[column] = camera_df[column].astype('Int64')
        self.append_new_rows('Camera', camera_df, ['main_cameras_num', 'selfie_cameras_num', 'highest_maincam_res', 'highest_selfiecam_res'])
    
    def addDisplay(self):
        display_df = self.load_source_dataframe()[['display_size_inch', 'display_size_cm', 'screen_to_body_ratio', 'resolution_pixels', 'resolution_ratio', 'ppi_density']].drop_duplicates().reset_index(drop=True)
        display_df['resolution_pixels'] = display_df['resolution_pixels'].astype('Int64')
        self.append_new_rows('Display', display_df, ['display_size_inch', 'display_size_cm', 'screen_to_body_ratio', 'resolution_pixels', 'resolution_ratio', 'ppi_density'])
    
    def addOs(self):
        os_df = self.load_source_dataframe()[['os_name', 'os_version']].drop_duplicates().reset_index(drop=True)
        name_mapping = pd.read_sql('SELECT * FROM OS_Name', con=self.connection).rename(columns={'id': 'name_id'})
        version_mapping = pd.read_sql('SELECT * FROM Version', con=self.connection).rename(columns={'id': 'version_id'})

        os_df = attach_lookup_id(os_df, name_mapping, ['os_name'], 'name_id')
        os_df = attach_lookup_id(os_df, version_mapping, ['os_version'], 'version_id')
        os_df = os_df[['name_id', 'version_id']].drop_duplicates().reset_index(drop=True)

        for column in ['name_id', 'version_id']:
            os_df[column] = os_df[column].astype('Int64')

        self.append_new_rows('OS', os_df, ['name_id', 'version_id'])
    
    def addPlatform(self):
        platform_df = self.load_source_dataframe()[['chipset_manufacturer', 'cpu_core_count', 'internal_storage_gb', 'ram_gb']].drop_duplicates().reset_index(drop=True)

        chip_mapping = pd.read_sql('SELECT * FROM Chipset', con=self.connection).rename(columns={'id': 'chipset_id'})
        cpu_mapping = pd.read_sql('SELECT * FROM Cpu', con=self.connection).rename(columns={'id': 'cpu_id'})
        memory_profile_mapping = pd.read_sql('SELECT * FROM Memory_Profile', con=self.connection).rename(columns={'id': 'memory_profile_id'})

        platform_df = attach_lookup_id(platform_df, chip_mapping, ['chipset_manufacturer'], 'chipset_id')
        platform_df = attach_lookup_id(platform_df, cpu_mapping, ['cpu_core_count'], 'cpu_id')
        platform_df = attach_lookup_id(platform_df, memory_profile_mapping, ['internal_storage_gb', 'ram_gb'], 'memory_profile_id')
        platform_df = platform_df[['chipset_id', 'cpu_id', 'memory_profile_id']].drop_duplicates().reset_index(drop=True)

        for column in ['chipset_id', 'cpu_id', 'memory_profile_id']:
            platform_df[column] = platform_df[column].astype('Int64')

        self.append_new_rows('Platform', platform_df, ['chipset_id', 'cpu_id', 'memory_profile_id'])

    def report_unresolved_device_lookups(self, device_df):
        required_columns = ['device_name_id', 'launch_id', 'year_id', 'network_technology_id', 'display_id']
        missing_required = {column: int(device_df[column].isna().sum()) for column in required_columns if device_df[column].isna().any()}
        if missing_required:
            raise ValueError(f"Required device lookups failed to resolve: {missing_required}")

        optional_columns = ['camera_id', 'battery_id', 'os_id', 'platform_id', 'sim_id']
        missing_optional = {column: int(device_df[column].isna().sum()) for column in optional_columns if device_df[column].isna().any()}
        if missing_optional:
            print(f"Optional device lookups unresolved: {missing_optional}")

    def build_device_records(self):
        data = self.load_source_dataframe()
        dedupe_columns = [column for column in data.columns if column != 'sensor_names']
        data = data.drop_duplicates(subset=dedupe_columns).reset_index(drop=True)

        camera_mapping = pd.read_sql('SELECT * FROM Camera', con=self.connection).rename(columns={'id': 'camera_id'})
        name_mapping = pd.read_sql('SELECT * FROM Device_Name', con=self.connection).rename(columns={'id': 'device_name_id'})
        os_mapping = pd.read_sql(
            'SELECT OS.id AS os_id, OS_Name.os_name, Version.os_version '
            'FROM OS '
            'JOIN OS_Name ON OS.name_id = OS_Name.id '
            'JOIN Version ON OS.version_id = Version.id',
            con=self.connection,
        )
        platform_mapping = pd.read_sql(
            'SELECT Platform.id AS platform_id, Chipset.chipset_manufacturer, Cpu.cpu_core_count, Memory_Profile.internal_storage_gb, Memory_Profile.ram_gb '
            'FROM Platform '
            'JOIN Chipset ON Chipset.id = Platform.chipset_id '
            'JOIN Cpu ON Cpu.id = Platform.cpu_id '
            'JOIN Memory_Profile ON Memory_Profile.id = Platform.memory_profile_id',
            con=self.connection,
        )
        network_technology_mapping = pd.read_sql(
            'SELECT Network_Technology.id AS network_technology_id, Technology.technology AS network_technology, '
            'Network_Band.supports_2g, Network_Band.supports_3g, Network_Band.supports_4g, Network_Band.supports_5g '
            'FROM Network_Technology '
            'JOIN Technology ON Technology.id = Network_Technology.technology_id '
            'JOIN Network_Band ON Network_Band.id = Network_Technology.network_band_id',
            con=self.connection,
        )
        launch_mapping = pd.read_sql(
            'SELECT Launch.id AS launch_id, Launch_Announced.launch_announced, Launch_Status.launch_status '
            'FROM Launch '
            'JOIN Launch_Announced ON Launch_Announced.id = Launch.announced_id '
            'JOIN Launch_Status ON Launch_Status.id = Launch.status_id',
            con=self.connection,
        )
        year_mapping = pd.read_sql('SELECT id AS year_id, year FROM Year', con=self.connection)
        sim_mapping = pd.read_sql('SELECT id AS sim_id, body_sim, sim_count, sim_type FROM Sim', con=self.connection)
        battery_mapping = pd.read_sql('SELECT id AS battery_id, battery_capacity_mah FROM Battery', con=self.connection)
        display_mapping = pd.read_sql('SELECT id AS display_id, display_size_inch, display_size_cm, screen_to_body_ratio, resolution_pixels, resolution_ratio, ppi_density FROM Display', con=self.connection)

        data = attach_lookup_id(data, sim_mapping, ['body_sim', 'sim_count', 'sim_type'], 'sim_id')
        data = attach_lookup_id(data, launch_mapping, ['launch_announced', 'launch_status'], 'launch_id')
        data = attach_lookup_id(data, year_mapping, ['year'], 'year_id')
        data = attach_lookup_id(data, network_technology_mapping, ['network_technology', 'supports_2g', 'supports_3g', 'supports_4g', 'supports_5g'], 'network_technology_id')
        data = attach_lookup_id(data, name_mapping, ['brand', 'model'], 'device_name_id')
        data = attach_lookup_id(data, platform_mapping, ['chipset_manufacturer', 'cpu_core_count', 'internal_storage_gb', 'ram_gb'], 'platform_id')
        data = attach_lookup_id(data, os_mapping, ['os_name', 'os_version'], 'os_id')
        data = attach_lookup_id(
            data,
            camera_mapping,
            ['main_cameras_num', 'selfie_cameras_num', 'highest_maincam_res', 'highest_selfiecam_res'],
            'camera_id',
        )
        data = attach_lookup_id(data, battery_mapping, ['battery_capacity_mah'], 'battery_id')
        data = attach_lookup_id(
            data,
            display_mapping,
            ['display_size_inch', 'display_size_cm', 'screen_to_body_ratio', 'resolution_pixels', 'resolution_ratio', 'ppi_density'],
            'display_id',
        )

        device_columns = ['device_name_id', 'network_technology_id', 'launch_id', 'year_id', 'camera_id', 'battery_id', 'display_id', 'weight', 'length', 'width', 'height', 'volume', 'os_id', 'platform_id', 'sim_id', 'price_eur']
        device_df = data[device_columns + ['sensor_names']].copy()
        device_df['device_key'] = build_lookup_signature(device_df, device_columns)

        id_columns = ['device_name_id', 'network_technology_id', 'launch_id', 'year_id', 'camera_id', 'battery_id', 'display_id', 'os_id', 'platform_id', 'sim_id']
        for column in id_columns:
            device_df[column] = device_df[column].astype('Int64')

        return device_df

    def addDevice(self):
        device_df = self.build_device_records()
        self.report_unresolved_device_lookups(device_df)
        device_columns = ['device_name_id', 'network_technology_id', 'launch_id', 'year_id', 'camera_id', 'battery_id', 'display_id', 'weight', 'length', 'width', 'height', 'volume', 'os_id', 'platform_id', 'sim_id', 'price_eur']
        self.append_new_rows('Device', device_df[['device_key'] + device_columns], ['device_key'])

        device_mapping = pd.read_sql('SELECT id AS device_id, device_key FROM Device', con=self.connection)
        device_df = attach_lookup_id(device_df, device_mapping, ['device_key'], 'device_id')
        if device_df['device_id'].isna().any():
            raise ValueError(f"Inserted devices could not be remapped by device_key: {int(device_df['device_id'].isna().sum())}")

        device_df['device_id'] = device_df['device_id'].astype('Int64')
        self._device_records = device_df

    def addDeviceSensor(self):
        if self._device_records is None:
            device_df = self.build_device_records()
            device_mapping = pd.read_sql('SELECT id AS device_id, device_key FROM Device', con=self.connection)
            device_df = attach_lookup_id(device_df, device_mapping, ['device_key'], 'device_id')
        else:
            device_df = self._device_records.copy()

        if device_df['device_id'].isna().any():
            raise ValueError(f"Device_Sensor build has unmapped devices: {int(device_df['device_id'].isna().sum())}")

        sensor_mapping = pd.read_sql('SELECT id AS sensor_id, sensor_name FROM Sensor', con=self.connection)

        device_df = device_df[['device_id', 'sensor_names']].explode('sensor_names').dropna(subset=['device_id', 'sensor_names']).reset_index(drop=True)
        device_df = device_df.rename(columns={'sensor_names': 'sensor_name'})
        device_df = attach_lookup_id(device_df, sensor_mapping, ['sensor_name'], 'sensor_id')
        device_df = device_df[['device_id', 'sensor_id']].dropna(subset=['device_id', 'sensor_id']).drop_duplicates().reset_index(drop=True)

        for column in ['device_id', 'sensor_id']:
            device_df[column] = device_df[column].astype('Int64')

        self.append_new_rows('Device_Sensor', device_df, ['device_id', 'sensor_id'])

    def addAll(self):
        self._device_records = None
        with self.engine.begin() as conn:
            self.connection = conn
            try:
                self.addDeviceName()
                self.addNetworkBand()
                self.addTechnology()
                self.addNetworkTechnology()
                self.addLaunch_Announced()
                self.addLaunch_Status()
                self.addLaunch()
                self.addYear()
                self.addSim()
                self.addcamera()
                self.addSensor()
                self.addDisplay()
                self.addVersion()
                self.addos_name()
                self.addOs()
                self.addChipset()
                self.addCpu()
                self.addMemoryProfile()
                self.addBattery()
                self.addPlatform()
                self.addDevice()
                self.addDeviceSensor()
            finally:
                self.connection = self.engine



if __name__ == '__main__':
    db_name = require_env('DB_NAME')
    db_user = require_env('DB_USER')
    db_password = require_env('DB_PASSWORD')
    db_host = require_env('DB_HOST')
    db_port = int(require_env('DB_PORT'))
    recreate_database = os_module.getenv('RECREATE_DATABASE', 'true').lower() == 'true'
    reset_tables = os_module.getenv('RESET_TABLES', 'true').lower() == 'true'

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

