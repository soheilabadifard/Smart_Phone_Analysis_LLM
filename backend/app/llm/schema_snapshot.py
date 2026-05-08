"""Static schema description injected into the LLM system prompt.

Hand-curated rather than dumped from `table.sql` so the model sees a clean,
column-purpose summary instead of DDL boilerplate. Update when the schema
changes.
"""

SCHEMA_DESCRIPTION = """\
You are querying a MariaDB 10.11 smartphone database. The schema is a star:
the central fact table `Device` references seven dimension tables.

TABLES (columns and notes):

Device(id, device_key, device_name_id, network_technology_id, camera_id,
       display_id, os_id, platform_id, sim_id,
       year, launch_status, battery_capacity_mah, weight, length, width,
       height, volume, price_eur, form_factor)
  - launch_status IN ('Available','Discontinued','Rumored','Canceled')
  - form_factor IN ('phone','watch','tablet','band','other')
    The dataset contains some smartwatches, tablets, and fitness bands that
    share this schema. When a question is about phones (or doesn't specify),
    add `WHERE d.form_factor = 'phone'` to filter them out.
  - year BETWEEN 1995 AND 2030
  - price_eur is in EUR; may be NULL for un-priced devices
  - weight (g), length/width/height (mm), volume (cc), battery_capacity_mah (mAh)

Device_Name(id, brand, model)
  - UNIQUE(brand, model)

Network_Technology(id, technology)
  - technology is a comma-joined list, e.g. 'GSM / HSPA / LTE / 5G'
  - Use technology LIKE '%5G%' to detect 5G support.

Camera(id, main_cameras_num, selfie_cameras_num,
       highest_maincam_res, highest_selfiecam_res)
  - highest_*_res is in megapixels (float)

Display(id, display_size_inch, display_size_cm, screen_to_body_ratio,
        resolution_pixels, resolution_ratio, ppi_density)
  - resolution_pixels is total pixel count (int); resolution_ratio is a string like '1080x2400'
  - screen_to_body_ratio may exceed 100% on wraparound displays

OS(id, os_name, os_version)
  - os_name examples: 'Android', 'iOS', 'HarmonyOS'

Platform(id, chipset_manufacturer, cpu_core_count, internal_storage_gb, ram_gb)
  - cpu_core_count is an integer (typical values: 2, 4, 6, 8, 10).
    Compare with numbers, not strings: WHERE p.cpu_core_count >= 8.

Sim(id, sim_count, sim_type)
  - sim_count IN ('single','dual','triple','none')

JOIN PATTERN (use this template — every device-level question needs it):
  FROM Device d
  JOIN Device_Name dn        ON dn.id = d.device_name_id
  JOIN Platform p            ON p.id  = d.platform_id
  JOIN Display disp          ON disp.id = d.display_id
  JOIN OS o                  ON o.id  = d.os_id
  JOIN Camera cam            ON cam.id = d.camera_id
  JOIN Sim s                 ON s.id  = d.sim_id
  JOIN Network_Technology nt ON nt.id = d.network_technology_id
"""
