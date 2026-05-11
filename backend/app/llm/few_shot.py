"""Few-shot examples for NL → SQL.

Each example is (user_question, assistant_sql). They are injected as
alternating chat messages before the real user question, so the model sees
the expected output format and joins/idioms specific to this schema.

Pick examples that cover patterns the model commonly gets wrong:
1. Plain filter + standard JOIN block
2. 5G detection via LIKE on Network_Technology
3. GROUP BY + HAVING aggregate
4. Year-over-year trend
5. Top-N per group (window function)
6. "All" / "every" — user asked for the complete list, override LIMIT
"""

EXAMPLES: list[tuple[str, str]] = [
    (
        "Find me the best phone.",
        """```sql
-- "Best" is ambiguous; interpret as a recent flagship: high RAM, large
-- battery, recent year, with a strong main camera. form_factor='phone'
-- filters out watches/tablets/bands that share this schema.
SELECT
    dn.brand, dn.model, d.year, d.price_eur,
    p.ram_gb, p.internal_storage_gb AS storage_gb,
    d.battery_capacity_mah, c.highest_maincam_res
FROM Device d
JOIN Device_Name dn ON dn.id = d.device_name_id
JOIN Platform    p  ON p.id  = d.platform_id
JOIN Camera      c  ON c.id  = d.camera_id
WHERE d.form_factor = 'phone'
  AND d.price_eur IS NOT NULL
  AND d.year >= 2023
ORDER BY p.ram_gb DESC, d.battery_capacity_mah DESC, c.highest_maincam_res DESC
LIMIT 10;
```""",
    ),
    (
        "Show me iPhones priced under 800 euros launched in 2022 or later.",
        """```sql
SELECT
    dn.brand, dn.model, d.year, d.price_eur,
    p.ram_gb, p.internal_storage_gb AS storage_gb
FROM Device d
JOIN Device_Name dn ON dn.id = d.device_name_id
JOIN Platform p    ON p.id  = d.platform_id
WHERE dn.brand = 'Apple'
  AND d.form_factor = 'phone'
  AND d.price_eur < 800
  AND d.year >= 2022
ORDER BY d.price_eur ASC
LIMIT 100;
```""",
    ),
    (
        "List 5G phones with at least 12 GB of RAM, cheapest first.",
        """```sql
SELECT
    dn.brand, dn.model, d.year,
    p.ram_gb, d.price_eur, nt.technology
FROM Device d
JOIN Device_Name dn        ON dn.id = d.device_name_id
JOIN Platform p            ON p.id  = d.platform_id
JOIN Network_Technology nt ON nt.id = d.network_technology_id
WHERE nt.technology LIKE '%5G%'
  AND p.ram_gb >= 12
  AND d.price_eur IS NOT NULL
ORDER BY d.price_eur ASC
LIMIT 100;
```""",
    ),
    (
        "What is the average phone price per brand? Only include brands with at least 5 phones.",
        """```sql
SELECT
    dn.brand,
    COUNT(*)                       AS device_count,
    ROUND(AVG(d.price_eur), 2)     AS avg_price_eur
FROM Device d
JOIN Device_Name dn ON dn.id = d.device_name_id
WHERE d.price_eur IS NOT NULL
GROUP BY dn.brand
HAVING COUNT(*) >= 5
ORDER BY avg_price_eur DESC
LIMIT 100;
```""",
    ),
    (
        "How has average battery capacity changed year over year since 2015?",
        """```sql
SELECT
    d.year,
    COUNT(*)                                  AS device_count,
    ROUND(AVG(d.battery_capacity_mah))        AS avg_battery_mah
FROM Device d
WHERE d.year >= 2015
  AND d.battery_capacity_mah IS NOT NULL
GROUP BY d.year
ORDER BY d.year ASC
LIMIT 100;
```""",
    ),
    (
        "For each year, which chipset manufacturer launched the most phones?",
        """```sql
WITH per_year AS (
    SELECT
        d.year,
        p.chipset_manufacturer,
        COUNT(*) AS launches,
        ROW_NUMBER() OVER (
            PARTITION BY d.year
            ORDER BY COUNT(*) DESC
        ) AS rn
    FROM Device d
    JOIN Platform p ON p.id = d.platform_id
    WHERE p.chipset_manufacturer IS NOT NULL
    GROUP BY d.year, p.chipset_manufacturer
)
SELECT year, chipset_manufacturer, launches
FROM per_year
WHERE rn = 1
ORDER BY year ASC
LIMIT 100;
```""",
    ),
    (
        "List all phones from Nokia.",
        """```sql
-- "all" → use the server-side cap (LIMIT 5000), not the default LIMIT 100.
SELECT
    dn.brand, dn.model, d.year, d.price_eur
FROM Device d
JOIN Device_Name dn ON dn.id = d.device_name_id
WHERE dn.brand = 'Nokia'
  AND d.form_factor = 'phone'
ORDER BY d.year DESC, dn.model ASC
LIMIT 5000;
```""",
    ),
]
