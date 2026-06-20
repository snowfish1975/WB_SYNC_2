import httpx
import asyncio
import logging
from typing import Any

RETURNS_BASE = "https://returns-api.wildberries.ru"
logger = logging.getLogger(__name__)


async def fetch_claims(
    token: str,
    is_archive: bool = False,
    nm_id: int | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """
    Заявки покупателей на возврат.
    GET /api/v1/claims (returns-api)
    Лимит: 20 req/min, 3s interval, 10 burst.
    """
    headers = {"Authorization": token}
    results = []
    offset = 0
    max_attempts = 5

    async with httpx.AsyncClient(timeout=60) as client:
        while True:
            params = {
                "is_archive": str(is_archive).lower(),
                "limit": limit,
                "offset": offset,
            }
            if nm_id:
                params["nm_id"] = nm_id

            for attempt in range(1, max_attempts + 1):
                try:
                    resp = await client.get(
                        f"{RETURNS_BASE}/api/v1/claims",
                        headers=headers,
                        params=params,
                    )
                    resp.raise_for_status()
                    body = resp.json()
                    break
                except Exception as e:
                    logger.warning(f"Claims попытка {attempt}/{max_attempts}: {type(e).__name__}: {e}")
                    if hasattr(e, 'response') and e.response is not None:
                        logger.warning(f"HTTP {e.response.status_code}: {e.response.text[:500]}")
                    if attempt == max_attempts:
                        logger.error(f"Claims: все попытки исчерпаны")
                        return results
                    await asyncio.sleep(3)

            claims = body.get("claims", [])
            if not claims:
                break

            results.extend(claims)
            logger.info(f"Claims: загружено {len(results)} (offset={offset})")

            total = body.get("total", 0)
            offset += limit
            if offset >= total:
                break

            await asyncio.sleep(3)  # rate limit 3s

    return results
