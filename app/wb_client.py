import httpx
import asyncio
import logging
from typing import Any
from datetime import datetime, timedelta, timezone

WB_BASE = "https://content-api.wildberries.ru"
WB_ANALYTICS_BASE = "https://seller-analytics-api.wildberries.ru"
WB_STATS_BASE = "https://statistics-api.wildberries.ru"
WB_PRICES_BASE = "https://discounts-prices-api.wildberries.ru"
logger = logging.getLogger(__name__)

# Московский часовой пояс (UTC+3)
MOSCOW_TZ = timezone(timedelta(hours=3))


async def fetch_product_characteristics(token: str, nm_ids: list[int]) -> list[dict[str, Any]]:
    headers = {"Authorization": token}
    payload = {
        "settings": {
            "filter": {"withPhoto": -1},
            "cursor": {"limit": 100},
        }
    }

    results = []
    max_attempts = 10
    retry_delay = 5
    page = 1

    while True:
        logger.info(f"Запрос страницы {page}, payload cursor: {payload['settings']['cursor']}")

        for attempt in range(1, max_attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=60) as client:
                    resp = await client.post(
                        f"{WB_BASE}/content/v2/get/cards/list",
                        headers=headers,
                        json=payload,
                    )
                    resp.raise_for_status()
                    body = resp.json()
                    logger.info(f"Характеристики, попытка {attempt} успешна: HTTP 200")
                    break
            except Exception as e:
                logger.warning(f"Характеристики, попытка {attempt}/{max_attempts} неудачна: {type(e).__name__}: {e}")
                if hasattr(e, 'response') and e.response is not None:
                    logger.warning(f"HTTP статус: {e.response.status_code}, тело: {e.response.text[:500]}")
                if attempt == max_attempts:
                    raise RuntimeError(f"Не удалось выполнить запрос после {max_attempts} попыток: {e}")
                await asyncio.sleep(retry_delay)

        cards = body.get("cards", [])
        cursor = body.get("cursor", {})

        logger.info(f"Страница {page}: получено {len(cards)} карточек, cursor в ответе: {cursor}")
        logger.info(f"Итого накоплено: {len(results) + len(cards)}")

        results.extend(cards)

        if len(cards) < 100:
            logger.info(f"Последняя страница (получено {len(cards)} < 100), завершаем.")
            break

        if not cursor.get("updatedAt") or not cursor.get("nmID"):
            logger.warning(f"Курсор пустой или неполный, завершаем: {cursor}")
            break

        payload["settings"]["cursor"]["updatedAt"] = cursor["updatedAt"]
        payload["settings"]["cursor"]["nmID"] = cursor["nmID"]
        page += 1

    logger.info(f"Характеристики: всего получено {len(results)} карточек за {page} страниц")
    return results


async def fetch_stocks(token: str) -> list[dict[str, Any]]:
    """
    Остатки на складах WB.
    Лимит: 3 запроса в минуту, интервал 20 сек.
    Пагинация через offset.
    """
    headers = {"Authorization": token}
    limit = 250000
    offset = 0
    results = []

    async with httpx.AsyncClient(timeout=60) as client:
        while True:
            payload = {
                "nmIds": [],
                "limit": limit,
                "offset": offset,
            }

            for attempt in range(1, 11):
                try:
                    resp = await client.post(
                        f"{WB_ANALYTICS_BASE}/api/analytics/v1/stocks-report/wb-warehouses",
                        headers=headers,
                        json=payload,
                    )
                    resp.raise_for_status()
                    body = resp.json()
                    break
                except Exception as e:
                    logger.warning(f"Остатки, попытка {attempt}/10: {type(e).__name__}: {e}")
                    if hasattr(e, 'response') and e.response is not None:
                        logger.warning(f"HTTP статус: {e.response.status_code}, тело: {e.response.text[:500]}")
                    if attempt == 10:
                        raise RuntimeError(f"Не удалось получить остатки: {e}")
                    await asyncio.sleep(20)

            items = body.get("data", {}).get("items", [])
            logger.info(f"Остатки: получено {len(items)} строк, offset={offset}")
            results.extend(items)

            if len(items) < limit:
                break

            offset += limit

    logger.info(f"Остатки: всего получено {len(results)} строк")
    return results


async def fetch_prices(token: str) -> list[dict]:
    headers = {"Authorization": token}
    limit = 1000
    offset = 0
    results = []

    max_attempts = 5
    retry_delay = 2

    async with httpx.AsyncClient(timeout=60) as client:
        while True:
            params = {
                "limit": limit,
                "offset": offset,
            }

            for attempt in range(1, max_attempts + 1):
                try:
                    resp = await client.get(
                        f"{WB_PRICES_BASE}/api/v2/list/goods/filter",
                        headers=headers,
                        params=params,
                    )
                    resp.raise_for_status()
                    body = resp.json()
                    break

                except Exception as e:
                    logger.warning(f"Цены, попытка {attempt}/{max_attempts}: {e}")

                    if attempt == max_attempts:
                        raise RuntimeError(f"Не удалось получить цены: {e}")

                    await asyncio.sleep(retry_delay * attempt)

            items = body.get("data", {}).get("listGoods", [])

            logger.info(f"Цены: получено {len(items)} товаров, offset={offset}")

            results.extend(items)

            if not items:
                break

            offset += limit

            # соблюдаем rate limit WB
            await asyncio.sleep(0.7)

    logger.info(f"Цены: всего получено {len(results)} товаров")
    return results


async def fetch_sales_report(token: str, date_from: str, date_to: str) -> list[dict[str, Any]]:
    """
    Отчёт о продажах по реализации.
    Лимит: 1 запрос в минуту.
    Пагинация через rrdid из последней строки ответа.
    date_from, date_to — строки в формате YYYY-MM-DD.
    """
    headers = {"Authorization": token}
    results = []
    rrdid = 0
    limit = 100000
    max_attempts = 5

    while True:
        params = {
            "dateFrom": date_from,
            "dateTo": date_to,
            "limit": limit,
            "rrdid": rrdid,
            "period": "daily",
        }

        logger.info(f"Отчёт реализации: запрос rrdid={rrdid}, dateFrom={date_from}, dateTo={date_to}")

        for attempt in range(1, max_attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=120) as client:
                    resp = await client.get(
                        f"{WB_STATS_BASE}/api/v5/supplier/reportDetailByPeriod",
                        headers=headers,
                        params=params,
                    )
                    # 204 — данных больше нет, это штатное завершение
                    if resp.status_code == 204:
                        logger.info("Отчёт реализации: получен 204, данных больше нет")
                        return results

                    resp.raise_for_status()
                    rows = resp.json()
                    logger.info(f"Отчёт реализации, попытка {attempt} успешна: получено {len(rows)} строк")
                    break

            except Exception as e:
                logger.warning(f"Отчёт реализации, попытка {attempt}/{max_attempts}: {type(e).__name__}: {e}")
                if hasattr(e, 'response') and e.response is not None:
                    logger.warning(f"HTTP статус: {e.response.status_code}, тело: {e.response.text[:500]}")
                if attempt == max_attempts:
                    raise RuntimeError(f"Не удалось получить отчёт реализации: {e}")
                # Лимит 1 запрос в минуту — ждём перед повтором
                await asyncio.sleep(65)

        if not rows:
            logger.info("Отчёт реализации: пустой ответ, завершаем")
            break

        results.extend(rows)
        logger.info(f"Отчёт реализации: накоплено {len(results)} строк")

        if len(rows) < limit:
            logger.info(f"Отчёт реализации: получено {len(rows)} < {limit}, последняя страница")
            break

        # Берём rrd_id последней строки для следующей страницы
        last_rrdid = rows[-1].get("rrd_id")
        if not last_rrdid:
            logger.warning("Отчёт реализации: нет rrd_id в последней строке, завершаем")
            break

        rrdid = last_rrdid
        # Соблюдаем лимит 1 запрос в минуту
        logger.info(f"Отчёт реализации: следующая страница с rrdid={rrdid}, ждём 65 сек...")
        await asyncio.sleep(65)

    logger.info(f"Отчёт реализации: всего получено {len(results)} строк")
    return results


async def fetch_orders_stream(
    token: str,
    date_from: datetime | None = None,
    flag: int = 0,
):
    """
    Потоковая выгрузка заказов.
    Возвращает страницы данных через yield вместо накопления в памяти.
    """

    headers = {"Authorization": token}

    if date_from is None:
        now_moscow = datetime.now(MOSCOW_TZ)
        date_from = now_moscow - timedelta(days=40)

    current_date_from = date_from.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    max_attempts = 5
    retry_delay = 30

    async with httpx.AsyncClient(timeout=60) as client:

        while True:

            logger.info(
                f"Заказы: запрос dateFrom={current_date_from}, flag={flag}"
            )

            for attempt in range(1, max_attempts + 1):
                try:
                    response = await client.get(
                        f"{WB_STATS_BASE}/api/v1/supplier/orders",
                        headers=headers,
                        params={
                            "dateFrom": current_date_from,
                            "flag": flag,
                        },
                    )

                    response.raise_for_status()

                    orders = response.json()

                    logger.info(
                        f"Заказы: получено {len(orders)} записей"
                    )

                    break

                except Exception as e:
                    logger.warning(
                        f"Заказы попытка {attempt}/{max_attempts}: {e}"
                    )

                    if attempt == max_attempts:
                        raise RuntimeError(
                            f"Не удалось получить заказы: {e}"
                        )

                    await asyncio.sleep(retry_delay)

            if not orders:
                break

            yield orders

            if len(orders) < 80000:
                break

            last_order = orders[-1]

            current_date_from = last_order.get("lastChangeDate")

            if not current_date_from:
                logger.warning(
                    "Заказы: отсутствует lastChangeDate"
                )
                break

            del orders


async def fetch_orders_last_40_days_stream(token: str):
    """
    Потоковая выгрузка заказов за последние 40 дней.
    Возвращает уже отфильтрованные страницы.
    """

    now_moscow = datetime.now(MOSCOW_TZ)

    today_start = now_moscow.replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )

    threshold_date = today_start - timedelta(days=40)

    logger.info(
        f"Порог заказов: {threshold_date.strftime('%Y-%m-%d')}"
    )

    async for orders in fetch_orders_stream(token, flag=0):

        filtered = []

        for order in orders:

            order_date_str = order.get("date")

            if not order_date_str:
                continue

            try:

                order_date = datetime.fromisoformat(
                    order_date_str.replace("Z", "+00:00")
                )

                order_date_moscow = order_date.astimezone(
                    MOSCOW_TZ
                )

                order_date_only = order_date_moscow.date()

                if (
                    threshold_date.date()
                    <= order_date_only
                    < today_start.date()
                ):
                    filtered.append(order)

            except Exception:
                continue

        logger.info(
            f"Заказы после фильтрации: {len(filtered)}"
        )

        if filtered:
            yield filtered

        del orders
        del filtered


async def fetch_sales_stream(
    token: str,
    date_from: datetime | None = None,
):
    """
    Потоковая выгрузка продаж.
    Возвращает страницы через yield.
    """

    headers = {"Authorization": token}

    if date_from is None:
        now_moscow = datetime.now(MOSCOW_TZ)
        date_from = now_moscow - timedelta(days=40)

    current_date_from = date_from.strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )

    max_attempts = 5
    retry_delay = 65

    async with httpx.AsyncClient(timeout=60) as client:

        while True:

            logger.info(
                f"Продажи: запрос dateFrom={current_date_from}"
            )

            for attempt in range(1, max_attempts + 1):

                try:

                    resp = await client.get(
                        f"{WB_STATS_BASE}/api/v1/supplier/sales",
                        headers=headers,
                        params={
                            "dateFrom": current_date_from,
                            "flag": 0,
                        },
                    )

                    resp.raise_for_status()

                    sales = resp.json()

                    logger.info(
                        f"Продажи: получено {len(sales)} записей"
                    )

                    break

                except Exception as e:

                    logger.warning(
                        f"Продажи попытка {attempt}/{max_attempts}: {e}"
                    )

                    if attempt == max_attempts:
                        raise RuntimeError(
                            f"Не удалось получить продажи: {e}"
                        )

                    await asyncio.sleep(retry_delay)

            if not sales:
                break

            yield sales

            if len(sales) < 80000:
                break

            last_date = sales[-1].get(
                "lastChangeDate"
            )

            if not last_date:
                logger.warning(
                    "Продажи: отсутствует lastChangeDate"
                )
                break

            current_date_from = last_date

            del sales

            await asyncio.sleep(retry_delay)