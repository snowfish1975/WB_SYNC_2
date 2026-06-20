import httpx
import asyncio
import logging
from typing import Any

MARKETPLACE_BASE = "https://marketplace-api.wildberries.ru"
COMMON_BASE = "https://common-api.wildberries.ru"
logger = logging.getLogger(__name__)


async def fetch_warehouses(token: str) -> list[dict[str, Any]]:
    """Список складов WB. GET /api/v3/offices. Лимит: 300/min."""
    headers = {"Authorization": token}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{MARKETPLACE_BASE}/api/v3/offices", headers=headers)
        resp.raise_for_status()
        return resp.json()


async def fetch_seller_warehouses(token: str) -> list[dict[str, Any]]:
    """Склады продавца. GET /api/v3/warehouses. Лимит: 300/min."""
    headers = {"Authorization": token}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{MARKETPLACE_BASE}/api/v3/warehouses", headers=headers)
        resp.raise_for_status()
        return resp.json()


async def fetch_tariffs_box(token: str, date: str) -> dict[str, Any]:
    """Тарифы для коробов. GET /api/v1/tariffs/box. Лимит: 60/min."""
    headers = {"Authorization": token}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{COMMON_BASE}/api/v1/tariffs/box",
                              headers=headers, params={"date": date})
        resp.raise_for_status()
        return resp.json().get("response", {}).get("data", {})


async def fetch_tariffs_pallet(token: str, date: str) -> dict[str, Any]:
    """Тарифы для монопаллет. GET /api/v1/tariffs/pallet. Лимит: 60/min."""
    headers = {"Authorization": token}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{COMMON_BASE}/api/v1/tariffs/pallet",
                              headers=headers, params={"date": date})
        resp.raise_for_status()
        return resp.json().get("response", {}).get("data", {})


async def fetch_tariffs_acceptance(token: str, warehouse_ids: str = "") -> list[dict[str, Any]]:
    """Тарифы на приёмку. GET /api/tariffs/v1/acceptance/coefficients. Лимит: 6/min."""
    headers = {"Authorization": token}
    params = {}
    if warehouse_ids:
        params["warehouseIDs"] = warehouse_ids
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{COMMON_BASE}/api/tariffs/v1/acceptance/coefficients",
                              headers=headers, params=params)
        resp.raise_for_status()
        return resp.json()


async def fetch_tariffs_return(token: str, date: str) -> dict[str, Any]:
    """Тарифы на возврат. GET /api/v1/tariffs/return. Лимит: 60/min."""
    headers = {"Authorization": token}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{COMMON_BASE}/api/v1/tariffs/return",
                              headers=headers, params={"date": date})
        resp.raise_for_status()
        return resp.json().get("response", {}).get("data", {})
