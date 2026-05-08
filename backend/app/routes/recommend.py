"""Phone recommendation: typed filters → ranked results.

No LLM here — this is a deterministic, validated SQL query. The frontend
form binds 1:1 to the `RecommendRequest` schema.
"""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.db import ro_engine

router = APIRouter()


class RecommendRequest(BaseModel):
    max_price_eur: float | None = Field(None, ge=0)
    brands: list[str] | None = None
    os_name: str | None = None
    min_ram_gb: int | None = Field(None, ge=0)
    min_storage_gb: int | None = Field(None, ge=0)
    min_battery_mah: int | None = Field(None, ge=0)
    min_display_inch: float | None = Field(None, ge=0)
    max_display_inch: float | None = Field(None, ge=0)
    require_5g: bool = False
    sort_by: Literal["price", "battery", "ram", "year"] = "price"
    sort_order: Literal["asc", "desc"] = "asc"
    limit: int = Field(50, ge=1, le=200)


class PhoneCard(BaseModel):
    device_id: int
    brand: str
    model: str
    year: int
    price_eur: float | None
    ram_gb: int | None
    storage_gb: int | None
    battery_mah: int | None
    display_inch: float | None
    os: str | None
    chipset: str | None
    network: str | None


@router.post("", response_model=list[PhoneCard])
def recommend(req: RecommendRequest) -> list[PhoneCard]:
    where: list[str] = []
    params: dict = {}

    if req.max_price_eur is not None:
        where.append("d.price_eur <= :max_price")
        params["max_price"] = req.max_price_eur
    if req.brands:
        where.append("dn.brand IN :brands")
        params["brands"] = tuple(req.brands)
    if req.os_name:
        where.append("o.os_name = :os_name")
        params["os_name"] = req.os_name
    if req.min_ram_gb is not None:
        where.append("p.ram_gb >= :min_ram")
        params["min_ram"] = req.min_ram_gb
    if req.min_storage_gb is not None:
        where.append("p.internal_storage_gb >= :min_storage")
        params["min_storage"] = req.min_storage_gb
    if req.min_battery_mah is not None:
        where.append("d.battery_capacity_mah >= :min_batt")
        params["min_batt"] = req.min_battery_mah
    if req.min_display_inch is not None:
        where.append("disp.display_size_inch >= :min_disp")
        params["min_disp"] = req.min_display_inch
    if req.max_display_inch is not None:
        where.append("disp.display_size_inch <= :max_disp")
        params["max_disp"] = req.max_display_inch
    if req.require_5g:
        where.append("nt.technology LIKE '%5G%'")

    sort_col = {
        "price": "d.price_eur",
        "battery": "d.battery_capacity_mah",
        "ram": "p.ram_gb",
        "year": "d.year",
    }[req.sort_by]

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    sql = text(
        f"""
        SELECT
            d.id AS device_id,
            dn.brand, dn.model,
            d.year, d.price_eur,
            p.ram_gb, p.internal_storage_gb AS storage_gb,
            d.battery_capacity_mah AS battery_mah,
            disp.display_size_inch AS display_inch,
            o.os_name AS os,
            p.chipset_manufacturer AS chipset,
            nt.technology AS network
        FROM Device d
        JOIN Device_Name dn ON dn.id = d.device_name_id
        JOIN Platform p ON p.id = d.platform_id
        JOIN Display disp ON disp.id = d.display_id
        JOIN OS o ON o.id = d.os_id
        JOIN Network_Technology nt ON nt.id = d.network_technology_id
        {where_sql}
        ORDER BY {sort_col} {req.sort_order.upper()}
        LIMIT :lim
        """
    )
    params["lim"] = req.limit

    with ro_engine().connect() as conn:
        rows = conn.execute(sql, params).mappings().all()
    return [PhoneCard(**dict(r)) for r in rows]


@router.get("/brands", response_model=list[str])
def list_brands() -> list[str]:
    with ro_engine().connect() as conn:
        rows = conn.execute(text("SELECT DISTINCT brand FROM Device_Name ORDER BY brand")).all()
    return [r[0] for r in rows]


@router.get("/os", response_model=list[str])
def list_os() -> list[str]:
    with ro_engine().connect() as conn:
        rows = conn.execute(text("SELECT DISTINCT os_name FROM OS WHERE os_name IS NOT NULL ORDER BY os_name")).all()
    return [r[0] for r in rows]
