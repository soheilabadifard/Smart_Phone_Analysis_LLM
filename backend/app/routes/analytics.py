"""Pre-built market analytics. Mirrors R1-R5 in Deliverables/queries.sql.

Each endpoint returns a JSON array; the frontend renders them via Plotly.
"""

from datetime import datetime

from fastapi import APIRouter
from sqlalchemy import text

from app.db import ro_engine

router = APIRouter()


def _rows(sql: str) -> list[dict]:
    with ro_engine().connect() as conn:
        return [dict(r) for r in conn.execute(text(sql)).mappings().all()]


@router.get("/brand-summary")
def brand_summary() -> list[dict]:
    """R1 — Brand catalogue summary: model count, avg price, year span."""
    return _rows(
        """
        SELECT
            dn.brand,
            COUNT(*) AS device_count,
            ROUND(AVG(d.price_eur), 2) AS avg_price_eur,
            MIN(d.year) AS first_year,
            MAX(d.year) AS last_year
        FROM Device d
        JOIN Device_Name dn ON dn.id = d.device_name_id
        WHERE d.price_eur IS NOT NULL
        GROUP BY dn.brand
        HAVING COUNT(*) >= 3
        ORDER BY device_count DESC
        """
    )


@router.get("/annual-launches")
def annual_launches() -> list[dict]:
    """R2 — Year-over-year launches and avg specs."""
    current_year = datetime.now().year
    return _rows(
        f"""
        SELECT
            d.year,
            COUNT(*) AS launches,
            ROUND(AVG(d.price_eur), 2) AS avg_price_eur,
            ROUND(AVG(d.battery_capacity_mah)) AS avg_battery_mah,
            ROUND(AVG(p.ram_gb), 2) AS avg_ram_gb,
            ROUND(AVG(p.internal_storage_gb), 2) AS avg_storage_gb
        FROM Device d
        JOIN Platform p ON p.id = d.platform_id
        WHERE d.year BETWEEN 2010 AND {current_year}
        GROUP BY d.year
        ORDER BY d.year
        """
    )


@router.get("/chipset-popularity")
def chipset_popularity() -> list[dict]:
    """Q10 variant — chipset manufacturer share."""
    return _rows(
        """
        SELECT
            p.chipset_manufacturer,
            COUNT(*) AS device_count
        FROM Device d
        JOIN Platform p ON p.id = d.platform_id
        WHERE p.chipset_manufacturer IS NOT NULL
        GROUP BY p.chipset_manufacturer
        ORDER BY device_count DESC
        LIMIT 15
        """
    )


@router.get("/price-vs-battery")
def price_vs_battery() -> list[dict]:
    """Scatter: price vs battery capacity (one point per device)."""
    return _rows(
        """
        SELECT
            dn.brand,
            d.price_eur,
            d.battery_capacity_mah AS battery_mah,
            p.ram_gb,
            d.year
        FROM Device d
        JOIN Device_Name dn ON dn.id = d.device_name_id
        JOIN Platform p ON p.id = d.platform_id
        WHERE d.price_eur IS NOT NULL
          AND d.battery_capacity_mah IS NOT NULL
        """
    )


@router.get("/ram-distribution")
def ram_distribution() -> list[dict]:
    """RAM bucket distribution."""
    return _rows(
        """
        SELECT
            p.ram_gb,
            COUNT(*) AS device_count
        FROM Device d
        JOIN Platform p ON p.id = d.platform_id
        WHERE p.ram_gb IS NOT NULL
        GROUP BY p.ram_gb
        ORDER BY p.ram_gb
        """
    )
