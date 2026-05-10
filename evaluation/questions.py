"""Hand-curated NL→SQL benchmark question set.

Each entry is (question, reference_sql, tags). The reference SQL is what a
human author would write against the project schema; the runner runs both
the LLM-emitted SQL and this reference SQL against the live DB and compares
the two result sets via `scorer.results_equivalent`.

Coverage targets:
  - Simple filters / orderings (Q1-Q4)
  - Aggregations + GROUP BY + HAVING (Q5-Q8)
  - Joins across multiple dims (Q9-Q12)
  - 5G LIKE detection (Q13-Q14)
  - NULL handling (Q15-Q16)
  - Window functions / top-N-per-group (Q17-Q19)
  - Year trends (Q20-Q22)
  - Form-factor scoping (Q23-Q25)

When the LLM gets a question repeatedly wrong, the right fix is to add an
example to backend/app/llm/few_shot.py — not to soften the reference SQL.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BenchmarkQuestion:
    id: str
    question: str
    reference_sql: str
    # 'set' = row order doesn't matter; 'ordered' = row order is part of the answer
    comparison: str = "set"
    tags: tuple[str, ...] = ()


QUESTIONS: list[BenchmarkQuestion] = [
    # --- Simple filters / orderings ----------------------------------------
    BenchmarkQuestion(
        id="Q1",
        question="List the 5 cheapest Apple phones from 2023, cheapest first.",
        reference_sql="""
            SELECT dn.brand, dn.model, d.year, d.price_eur
            FROM Device d
            JOIN Device_Name dn ON dn.id = d.device_name_id
            WHERE dn.brand = 'Apple' AND d.form_factor = 'phone'
              AND d.year = 2023 AND d.price_eur IS NOT NULL
            ORDER BY d.price_eur ASC
            LIMIT 5
        """,
        comparison="ordered",
        tags=("filter", "order"),
    ),
    BenchmarkQuestion(
        id="Q2",
        question="Show 10 phones with at least 12 GB of RAM, most RAM first.",
        reference_sql="""
            SELECT dn.brand, dn.model, p.ram_gb, d.price_eur
            FROM Device d
            JOIN Device_Name dn ON dn.id = d.device_name_id
            JOIN Platform p ON p.id = d.platform_id
            WHERE d.form_factor = 'phone' AND p.ram_gb >= 12
            ORDER BY p.ram_gb DESC
            LIMIT 10
        """,
        comparison="ordered",
        tags=("filter", "join"),
    ),
    BenchmarkQuestion(
        id="Q3",
        question="How many phones cost less than 200 euros?",
        reference_sql="""
            SELECT COUNT(*) AS n
            FROM Device d
            WHERE d.form_factor = 'phone' AND d.price_eur < 200
        """,
        tags=("count",),
    ),
    BenchmarkQuestion(
        id="Q4",
        question="What is the most expensive phone in the database?",
        reference_sql="""
            SELECT dn.brand, dn.model, d.price_eur
            FROM Device d
            JOIN Device_Name dn ON dn.id = d.device_name_id
            WHERE d.form_factor = 'phone' AND d.price_eur IS NOT NULL
            ORDER BY d.price_eur DESC
            LIMIT 1
        """,
        comparison="ordered",
        tags=("max",),
    ),
    # --- Aggregations / GROUP BY / HAVING ----------------------------------
    BenchmarkQuestion(
        id="Q5",
        question="Average phone price per brand, brands with at least 10 phones only.",
        reference_sql="""
            SELECT dn.brand,
                   COUNT(*) AS device_count,
                   ROUND(AVG(d.price_eur), 2) AS avg_price_eur
            FROM Device d
            JOIN Device_Name dn ON dn.id = d.device_name_id
            WHERE d.form_factor = 'phone' AND d.price_eur IS NOT NULL
            GROUP BY dn.brand
            HAVING COUNT(*) >= 10
        """,
        tags=("group", "having"),
    ),
    BenchmarkQuestion(
        id="Q6",
        question="Which 5 brands have the highest average phone price?",
        reference_sql="""
            SELECT dn.brand, ROUND(AVG(d.price_eur), 2) AS avg_price_eur
            FROM Device d
            JOIN Device_Name dn ON dn.id = d.device_name_id
            WHERE d.form_factor = 'phone' AND d.price_eur IS NOT NULL
            GROUP BY dn.brand
            ORDER BY avg_price_eur DESC
            LIMIT 5
        """,
        comparison="ordered",
        tags=("group", "top-n"),
    ),
    BenchmarkQuestion(
        id="Q7",
        question="How many phones does each brand have? Top 10 brands.",
        reference_sql="""
            SELECT dn.brand, COUNT(*) AS device_count
            FROM Device d
            JOIN Device_Name dn ON dn.id = d.device_name_id
            WHERE d.form_factor = 'phone'
            GROUP BY dn.brand
            ORDER BY device_count DESC
            LIMIT 10
        """,
        comparison="ordered",
        tags=("group", "top-n"),
    ),
    BenchmarkQuestion(
        id="Q8",
        question="Average battery capacity by chipset manufacturer.",
        reference_sql="""
            SELECT p.chipset_manufacturer,
                   ROUND(AVG(d.battery_capacity_mah)) AS avg_battery_mah
            FROM Device d
            JOIN Platform p ON p.id = d.platform_id
            WHERE d.form_factor = 'phone'
              AND d.battery_capacity_mah IS NOT NULL
              AND p.chipset_manufacturer IS NOT NULL
            GROUP BY p.chipset_manufacturer
        """,
        tags=("group", "join"),
    ),
    # --- 5G detection -------------------------------------------------------
    BenchmarkQuestion(
        id="Q9",
        question="How many phones support 5G?",
        reference_sql="""
            SELECT COUNT(*) AS n
            FROM Device d
            JOIN Network_Technology nt ON nt.id = d.network_technology_id
            WHERE d.form_factor = 'phone' AND nt.technology LIKE '%5G%'
        """,
        tags=("5g", "count"),
    ),
    BenchmarkQuestion(
        id="Q10",
        question="List 5 cheapest 5G phones with at least 8 GB RAM.",
        reference_sql="""
            SELECT dn.brand, dn.model, p.ram_gb, d.price_eur
            FROM Device d
            JOIN Device_Name dn ON dn.id = d.device_name_id
            JOIN Platform p ON p.id = d.platform_id
            JOIN Network_Technology nt ON nt.id = d.network_technology_id
            WHERE d.form_factor = 'phone' AND nt.technology LIKE '%5G%'
              AND p.ram_gb >= 8 AND d.price_eur IS NOT NULL
            ORDER BY d.price_eur ASC
            LIMIT 5
        """,
        comparison="ordered",
        tags=("5g", "filter", "order"),
    ),
    # --- Year trends --------------------------------------------------------
    BenchmarkQuestion(
        id="Q11",
        question="How many phones were launched each year from 2020 to 2024?",
        reference_sql="""
            SELECT d.year, COUNT(*) AS launches
            FROM Device d
            WHERE d.form_factor = 'phone' AND d.year BETWEEN 2020 AND 2024
            GROUP BY d.year
            ORDER BY d.year ASC
        """,
        comparison="ordered",
        tags=("year", "trend"),
    ),
    BenchmarkQuestion(
        id="Q12",
        question="Average RAM in phones by year since 2018.",
        reference_sql="""
            SELECT d.year, ROUND(AVG(p.ram_gb), 2) AS avg_ram_gb
            FROM Device d
            JOIN Platform p ON p.id = d.platform_id
            WHERE d.form_factor = 'phone' AND d.year >= 2018
              AND p.ram_gb IS NOT NULL
            GROUP BY d.year
            ORDER BY d.year ASC
        """,
        comparison="ordered",
        tags=("year", "trend"),
    ),
    # --- NULL handling ------------------------------------------------------
    BenchmarkQuestion(
        id="Q13",
        question="How many phones have no recorded price?",
        reference_sql="""
            SELECT COUNT(*) AS n
            FROM Device d
            WHERE d.form_factor = 'phone' AND d.price_eur IS NULL
        """,
        tags=("null",),
    ),
    BenchmarkQuestion(
        id="Q14",
        question="How many phones have no chipset information at all?",
        reference_sql="""
            SELECT COUNT(*) AS n
            FROM Device d
            WHERE d.form_factor = 'phone' AND d.platform_id IS NULL
        """,
        tags=("null", "left-join"),
    ),
    # --- Window functions / top-N per group ---------------------------------
    BenchmarkQuestion(
        id="Q15",
        question="What is the most expensive phone per brand among the top 5 brands by phone count?",
        reference_sql="""
            WITH top_brands AS (
                SELECT dn.brand
                FROM Device d
                JOIN Device_Name dn ON dn.id = d.device_name_id
                WHERE d.form_factor = 'phone'
                GROUP BY dn.brand
                ORDER BY COUNT(*) DESC
                LIMIT 5
            ),
            ranked AS (
                SELECT dn.brand, dn.model, d.price_eur,
                       ROW_NUMBER() OVER (PARTITION BY dn.brand ORDER BY d.price_eur DESC) AS rn
                FROM Device d
                JOIN Device_Name dn ON dn.id = d.device_name_id
                WHERE d.form_factor = 'phone' AND d.price_eur IS NOT NULL
                  AND dn.brand IN (SELECT brand FROM top_brands)
            )
            SELECT brand, model, price_eur FROM ranked WHERE rn = 1
        """,
        tags=("window", "top-per-group"),
    ),
    # --- Joins across multiple dims -----------------------------------------
    BenchmarkQuestion(
        id="Q16",
        question="Show 10 Samsung phones with their chipset, RAM, and main camera megapixels.",
        reference_sql="""
            SELECT dn.brand, dn.model, p.chipset_manufacturer, p.ram_gb,
                   c.highest_maincam_res
            FROM Device d
            JOIN Device_Name dn ON dn.id = d.device_name_id
            JOIN Platform p ON p.id = d.platform_id
            JOIN Camera c ON c.id = d.camera_id
            WHERE dn.brand = 'Samsung' AND d.form_factor = 'phone'
            LIMIT 10
        """,
        tags=("join", "multi-dim"),
    ),
    # --- Form-factor scoping ------------------------------------------------
    BenchmarkQuestion(
        id="Q17",
        question="How many smartwatches are in the database?",
        reference_sql="""
            SELECT COUNT(*) AS n
            FROM Device d
            WHERE d.form_factor = 'watch'
        """,
        tags=("form-factor",),
    ),
    BenchmarkQuestion(
        id="Q18",
        question="How many tablets are in the database?",
        reference_sql="""
            SELECT COUNT(*) AS n
            FROM Device d
            WHERE d.form_factor = 'tablet'
        """,
        tags=("form-factor",),
    ),
    # --- OS / chipset breakdown ---------------------------------------------
    BenchmarkQuestion(
        id="Q19",
        question="Top 5 operating systems by phone count.",
        reference_sql="""
            SELECT o.os_name, COUNT(*) AS device_count
            FROM Device d
            JOIN OS o ON o.id = d.os_id
            WHERE d.form_factor = 'phone'
            GROUP BY o.os_name
            ORDER BY device_count DESC
            LIMIT 5
        """,
        comparison="ordered",
        tags=("group", "top-n"),
    ),
    BenchmarkQuestion(
        id="Q20",
        question="Top 5 chipset manufacturers by phone count.",
        reference_sql="""
            SELECT p.chipset_manufacturer, COUNT(*) AS device_count
            FROM Device d
            JOIN Platform p ON p.id = d.platform_id
            WHERE d.form_factor = 'phone'
              AND p.chipset_manufacturer IS NOT NULL
            GROUP BY p.chipset_manufacturer
            ORDER BY device_count DESC
            LIMIT 5
        """,
        comparison="ordered",
        tags=("group", "top-n"),
    ),
    # --- Mixed --------------------------------------------------------------
    BenchmarkQuestion(
        id="Q21",
        question="Average display size in inches for phones launched in 2024.",
        reference_sql="""
            SELECT ROUND(AVG(disp.display_size_inch), 2) AS avg_inch
            FROM Device d
            JOIN Display disp ON disp.id = d.display_id
            WHERE d.form_factor = 'phone' AND d.year = 2024
              AND disp.display_size_inch IS NOT NULL
        """,
        tags=("avg",),
    ),
    BenchmarkQuestion(
        id="Q22",
        question="How many dual-SIM phones are there?",
        reference_sql="""
            SELECT COUNT(*) AS n
            FROM Device d
            JOIN Sim s ON s.id = d.sim_id
            WHERE d.form_factor = 'phone' AND s.sim_count = 'dual'
        """,
        tags=("count", "join"),
    ),
    BenchmarkQuestion(
        id="Q23",
        question="What is the cheapest phone with at least 256 GB of storage?",
        reference_sql="""
            SELECT dn.brand, dn.model, p.internal_storage_gb, d.price_eur
            FROM Device d
            JOIN Device_Name dn ON dn.id = d.device_name_id
            JOIN Platform p ON p.id = d.platform_id
            WHERE d.form_factor = 'phone' AND p.internal_storage_gb >= 256
              AND d.price_eur IS NOT NULL
            ORDER BY d.price_eur ASC
            LIMIT 1
        """,
        comparison="ordered",
        tags=("min", "filter"),
    ),
    BenchmarkQuestion(
        id="Q24",
        question="Apple phones with at least 8 GB of RAM, sorted by year descending.",
        reference_sql="""
            SELECT dn.brand, dn.model, d.year, p.ram_gb
            FROM Device d
            JOIN Device_Name dn ON dn.id = d.device_name_id
            JOIN Platform p ON p.id = d.platform_id
            WHERE dn.brand = 'Apple' AND d.form_factor = 'phone' AND p.ram_gb >= 8
            ORDER BY d.year DESC
            LIMIT 100
        """,
        comparison="ordered",
        tags=("filter", "order"),
    ),
    BenchmarkQuestion(
        id="Q25",
        question="How has average phone price changed year over year since 2015?",
        reference_sql="""
            SELECT d.year, ROUND(AVG(d.price_eur), 2) AS avg_price_eur
            FROM Device d
            WHERE d.form_factor = 'phone' AND d.year >= 2015
              AND d.price_eur IS NOT NULL
            GROUP BY d.year
            ORDER BY d.year ASC
        """,
        comparison="ordered",
        tags=("year", "trend"),
    ),
]
