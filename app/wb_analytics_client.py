import httpx
import asyncio
import logging
from datetime import datetime
from typing import Any

WB_ANALYTICS_BASE = "https://seller-analytics-api.wildberries.ru"
logger = logging.getLogger(__name__)


def parse_analytics_date(val: str | None) -> datetime | None:
    if not val or val == "0001-01-01T00:00:00":
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(val[:19], fmt[:len(val[:19])])
        except Exception:
            continue
    return None


async def fetch_sales_funnel(
    token: str,
    date_from: str,
    date_to: str,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """
    Воронка продаж: просмотры, конверсия, добавления в корзину, заказы, выкупы.
    POST /api/analytics/v3/sales-funnel/products
    Лимит: 3 запроса в минуту, интервал 20 сек.
    """
    headers = {"Authorization": token}
    offset = 0
    results = []
    max_attempts = 5

    async with httpx.AsyncClient(timeout=120) as client:
        while True:
            payload = {
                "selectedPeriod": {"start": date_from, "end": date_to},
                "nmIds": [],
                "brandNames": [],
                "subjectIds": [],
                "tagIds": [],
                "skipDeletedNm": True,
                "orderBy": {"field": "orderSum", "mode": "desc"},
                "limit": limit,
                "offset": offset,
            }

            for attempt in range(1, max_attempts + 1):
                try:
                    resp = await client.post(
                        f"{WB_ANALYTICS_BASE}/api/analytics/v3/sales-funnel/products",
                        headers=headers,
                        json=payload,
                    )
                    resp.raise_for_status()
                    body = resp.json()
                    break
                except Exception as e:
                    logger.warning(
                        f"Sales funnel, попытка {attempt}/{max_attempts}: "
                        f"{type(e).__name__}: {e}"
                    )
                    if hasattr(e, "response") and e.response is not None:
                        logger.warning(
                            f"HTTP статус: {e.response.status_code}, "
                            f"тело: {e.response.text[:500]}"
                        )
                    if attempt == max_attempts:
                        logger.error(
                            f"Не удалось получить воронку продаж после {max_attempts} попыток"
                        )
                        return results
                    await asyncio.sleep(20)

            data = body.get("data", {})
            products = data.get("products", [])

            for p in products:
                results.append(p)

            logger.info(
                f"Sales funnel: received {len(products)} products, offset={offset}"
            )

            if len(products) < limit:
                break

            offset += limit
            await asyncio.sleep(20)

    logger.info(f"Sales funnel: всего получено {len(results)} товаров")
    return results


async def fetch_stock_by_offices(token: str, date_from: str, date_to: str) -> list[dict]:
    """POST /api/v2/stocks-report/offices"""
    headers = {"Authorization": token}
    max_attempts = 5
    payload = {"currentPeriod": {"start": date_from, "end": date_to}, "stockType": "", "skipDeletedNm": True}
    async with httpx.AsyncClient(timeout=120) as client:
        for attempt in range(1, max_attempts + 1):
            try:
                resp = await client.post(f"{WB_ANALYTICS_BASE}/api/v2/stocks-report/offices", headers=headers, json=payload)
                resp.raise_for_status()
                body = resp.json()
                break
            except Exception as e:
                logger.warning(f"Stock offices, attempt {attempt}/{max_attempts}: {e}")
                if attempt == max_attempts: return []
                await asyncio.sleep(20)
        regions = body.get("data", {}).get("regions", [])
        logger.info(f"Stock offices: {len(regions)} regions")
        return regions


async def fetch_item_rating(token: str, date_from: str, date_to: str, limit: int = 1000) -> tuple[list[dict], float]:
    """POST /api/analytics/v1/item-rating. Note: end date CANNOT be today."""
    headers = {"Authorization": token}
    offset = 0
    results = []
    seller_rating = 0
    max_attempts = 5
    async with httpx.AsyncClient(timeout=120) as client:
        while True:
            payload = {"currentPeriod": {"start": date_from, "end": date_to}, "isNotIncludeNMsWithoutSales": True, "orderBy": {"field": "feedbackCount", "mode": "desc"}, "limit": limit, "offset": offset}
            for attempt in range(1, max_attempts + 1):
                try:
                    resp = await client.post(f"{WB_ANALYTICS_BASE}/api/analytics/v1/item-rating", headers=headers, json=payload)
                    resp.raise_for_status()
                    body = resp.json()
                    break
                except Exception as e:
                    logger.warning(f"Item rating, attempt {attempt}/{max_attempts}: {e}")
                    if attempt == max_attempts: return results, seller_rating
                    await asyncio.sleep(20)
            data = body.get("data", {})
            if not seller_rating:
                seller_rating = data.get("sellerRating", {}).get("current", 0)
            cards = data.get("cards", [])
            results.extend(cards)
            logger.info(f"Item rating: {len(cards)} cards, offset={offset}")
            if len(cards) < limit: break
            offset += limit
            await asyncio.sleep(20)
    logger.info(f"Item rating: total {len(results)} products, seller_rating={seller_rating}")
    return results, seller_rating


ADVERT_API_BASE = "https://advert-api.wildberries.ru"


async def fetch_ad_campaigns(token: str) -> list[dict]:
    """GET /adv/v1/promotion/count — list all campaign IDs with type+status"""
    headers = {"Authorization": token}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{ADVERT_API_BASE}/adv/v1/promotion/count", headers=headers)
        resp.raise_for_status()
        data = resp.json()
        campaigns = []
        for group in (data.get("adverts") or []):
            for ad in group.get("advert_list", []):
                campaigns.append({
                    "advertId": ad["advertId"],
                    "type": group["type"],
                    "status": group["status"],
                    "changeTime": ad.get("changeTime"),
                })
        logger.info(f"Ad campaigns: {len(campaigns)} total")
        return campaigns


async def fetch_ad_campaign_details(token: str, advert_ids: list[int]) -> list[dict]:
    """GET /api/advert/v2/adverts — detailed info for up to 50 campaigns"""
    headers = {"Authorization": token}
    ids_str = ",".join(str(i) for i in advert_ids[:50])
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{ADVERT_API_BASE}/api/advert/v2/adverts",
            headers=headers, params={"ids": ids_str},
        )
        resp.raise_for_status()
        data = resp.json()
        adverts = data.get("adverts", [])
        logger.info(f"Ad campaign details: {len(adverts)} campaigns")
        return adverts


async def fetch_ad_stats(token: str, advert_ids: list[int], date_from: str, date_to: str) -> list[dict]:
    """GET /adv/v3/fullstats — stats for campaigns (max 50 IDs, max 31 days)"""
    headers = {"Authorization": token}
    ids_str = ",".join(str(i) for i in advert_ids[:50])
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(
            f"{ADVERT_API_BASE}/adv/v3/fullstats",
            headers=headers,
            params={"ids": ids_str, "beginDate": date_from, "endDate": date_to},
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"Ad stats: {len(data)} campaigns")
        return data


async def fetch_ad_expenses(token: str, date_from: str, date_to: str) -> list[dict]:
    """GET /adv/v1/upd — expense history for period (max 31 days)"""
    headers = {"Authorization": token}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{ADVERT_API_BASE}/adv/v1/upd",
            headers=headers, params={"from": date_from, "to": date_to},
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"Ad expenses: {len(data)} records")
        return data


async def fetch_ad_balance(token: str) -> dict:
    """GET /adv/v1/balance"""
    headers = {"Authorization": token}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{ADVERT_API_BASE}/adv/v1/balance", headers=headers)
        resp.raise_for_status()
        return resp.json()


async def fetch_ad_search_clusters(token: str, items: list[dict], date_from: str, date_to: str) -> list[dict]:
    """POST /adv/v0/normquery/stats — search cluster statistics.
    
    items: [{"advert_id": int, "nm_id": int}, ...] (max 100)
    Returns list of {advert_id, nm_id, stats: [{norm_query, views, clicks, ...}]}
    """
    headers = {"Authorization": token, "Content-Type": "application/json"}
    results = []
    for i in range(0, len(items), 100):
        batch = items[i:i+100]
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{ADVERT_API_BASE}/adv/v0/normquery/stats",
                headers=headers,
                json={"from": date_from, "to": date_to, "items": batch},
            )
            if resp.status_code == 429:
                logger.warning("Search clusters: rate limited, waiting 6s")
                await asyncio.sleep(6)
                resp = await client.post(
                    f"{ADVERT_API_BASE}/adv/v0/normquery/stats",
                    headers=headers,
                    json={"from": date_from, "to": date_to, "items": batch},
                )
            if resp.status_code != 200:
                logger.warning(f"Search clusters HTTP {resp.status_code}: {resp.text[:300]}")
                continue
            data = resp.json()
            results.extend(data.get("stats", []))
    return results
