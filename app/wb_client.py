import os
import httpx
import asyncio
import logging
from typing import Any
from datetime import datetime, timedelta, timezone

WB_BASE = "https://content-api.wildberries.ru"
WB_ANALYTICS_BASE = "https://seller-analytics-api.wildberries.ru"
WB_STATS_BASE = "https://statistics-api.wildberries.ru"
WB_PRICES_BASE = "https://discounts-prices-api.wildberries.ru"
# Финансовые отчёты вынесены WB в отдельный домен (категория токена «Финансы»)
WB_FINANCE_BASE = os.getenv("WB_FINANCE_BASE", "https://finance-api.wildberries.ru")
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


# ---------------------------------------------------------------------------
# ОТЧЁТ О РЕАЛИЗАЦИИ: новый метод finance-api
# ---------------------------------------------------------------------------
# Старый метод GET statistics-api /api/v5/supplier/reportDetailByPeriod WB вывел из
# эксплуатации (deprecated, удалён из документации 15.07.2026) и оставил на нём
# остаточную квоту ~1 запрос в 24–36 часов на аккаунт — ежедневная загрузка падала с 429.
#
# Новый метод: POST https://finance-api.wildberries.ru/api/finance/v1/sales-reports/detailed
#   • требует токен с категорией «Финансы» (иначе 403 «scope is not allowed»);
#   • лимит 1 запрос в минуту на аккаунт;
#   • пагинация через rrdId, конец данных — ответ 204;
#   • поля переименованы, а денежные суммы приходят строками, а не числами.
#
# Карта ниже составлена по официальной схеме SalesReportsDetailedRes (спека WB «Финансы»,
# сентябрь 2026) и сверена со схемой старого ответа DetailReportItem (спека от 09.07.2026).
# Слева — поля нового API, справа — колонки SalesReport. Колонки оставлены прежними,
# чтобы не переписывать API-эндпоинты, дашборд, РНП и юнит-экономику.
SALES_REPORT_PATH = "/api/finance/v1/sales-reports/detailed"
SALES_REPORT_PAGE_LIMIT = int(os.getenv("SALES_REPORT_LIMIT", "100000"))
SALES_REPORT_MAX_RETRY_WAIT = int(os.getenv("SALES_REPORT_MAX_RETRY_WAIT", "300"))

SALES_REPORT_FIELD_MAP: dict[str, str] = {
    # Идентификаторы
    "reportId": "realizationreport_id",     # было realizationreport_id
    "rrdId": "rrd_id",
    "giId": "gi_id",
    "orderId": "assembly_id",              # было assembly_id «Номер сборочного задания»
    "nmId": "nm_id",
    "shkId": "shk_id",
    "sku": "barcode",                      # было barcode
    "srid": "srid",
    "orderUid": "order_uid",
    "trbxId": "trbx_id",
    "stickerId": "sticker_id",
    # Период отчёта
    "dateFrom": "date_from",
    "dateTo": "date_to",
    "createDate": "create_dt",
    "rrDate": "rr_dt",
    "orderDt": "order_dt",
    "saleDt": "sale_dt",
    "fixTariffDateFrom": "fix_tariff_date_from",
    "fixTariffDateTo": "fix_tariff_date_to",
    # Товар
    "subjectName": "subject_name",
    "brandName": "brand_name",
    "vendorCode": "sa_name",               # было sa_name «Артикул продавца»
    "techSize": "ts_name",                 # было ts_name
    # title — новое поле (Название товара), колонки нет → остаётся в raw_data
    # Операция
    "docTypeName": "doc_type_name",
    "sellerOperName": "supplier_oper_name", # было supplier_oper_name «Обоснование для оплаты»
    "officeName": "office_name",
    "quantity": "quantity",
    "currency": "currency_name",
    "deliveryMethod": "delivery_method",
    "giBoxTypeName": "gi_box_type_name",
    "reportType": "report_type",
    "srvDbs": "srv_dbs",
    "isB2b": "is_legal_entity",            # было is_legal_entity «Признак B2B-продажи»
    # Цены и скидки
    "retailPrice": "retail_price",
    "retailAmount": "retail_amount",
    "retailPriceWithDisc": "retail_price_withdisc_rub",   # было retail_price_withdisc_rub
    "salePercent": "sale_percent",
    "commissionPercent": "commission_percent",
    "productDiscountForReport": "product_discount_for_report",
    "sellerPromo": "supplier_promo",       # было supplier_promo «Промокод, %»
    "spp": "ppvz_spp_prc",                # было ppvz_spp_prc «СПП, %» → «Платформенные скидки, %»
    # Комиссии WB
    "kvwBase": "ppvz_kvw_prc_base",        # было ppvz_kvw_prc_base
    "kvw": "ppvz_kvw_prc",                 # было ppvz_kvw_prc
    "supRatingUp": "sup_rating_prc_up",
    "isKgvpV2": "is_kgvp_v2",
    "ppvzSalesCommission": "ppvz_sales_commission",
    "forPay": "ppvz_for_pay",              # было ppvz_for_pay
    "ppvzReward": "ppvz_reward",
    "vw": "ppvz_vw",                       # было ppvz_vw
    "vwNds": "ppvz_vw_nds",                # было ppvz_vw_nds
    "dlvPrc": "dlv_prc",
    # Эквайринг
    "acquiringFee": "acquiring_fee",
    "acquiringPercent": "acquiring_percent",
    "acquiringBank": "acquiring_bank",
    "paymentProcessing": "payment_processing",
    # Логистика и удержания
    "deliveryAmount": "delivery_amount",
    "returnAmount": "return_amount",
    "deliveryService": "delivery_rub",     # было delivery_rub «Услуги по доставке»
    "rebillLogisticCost": "rebill_logistic_cost",
    "rebillLogisticOrg": "rebill_logistic_org",
    "paidStorage": "storage_fee",          # было storage_fee «Хранение»
    "paidAcceptance": "acceptance",        # было acceptance «Операции на приёмке»
    "deduction": "deduction",
    "penalty": "penalty",
    "additionalPayment": "additional_payment",
    # Прочее
    "country": "site_country",             # было site_country «Страна продажи»
    "ppvzOfficeName": "ppvz_office_name",
    "ppvzOfficeId": "ppvz_office_id",
    "ppvzSupplierName": "ppvz_supplier_name",
    "ppvzSupplierInn": "ppvz_inn",         # было ppvz_inn «ИНН партнёра»
    "declarationNumber": "declaration_number",
    "bonusTypeName": "bonus_type_name",
    "kiz": "kiz",
    "installmentCofinancingAmount": "installment_cofinancing_amount",
    "wibesDiscountPercent": "wibes_wb_discount_percent",
    "cashbackAmount": "cashback_amount",
    "cashbackDiscount": "cashback_discount",
    "cashbackCommissionChange": "cashback_commission_change",
    "paymentSchedule": "payment_schedule",
    "sellerPromoId": "seller_promo_id",
    "sellerPromoDiscount": "seller_promo_discount",
    "loyaltyId": "loyalty_id",
    "loyaltyDiscount": "loyalty_discount",
    "uuidPromocode": "uuid_promocode",
    "salePricePromocodeDiscountPrc": "sale_price_promocode_discount_prc",
    "articleSubstitution": "article_substitution",
    "salePriceAffiliatedDiscountPrc": "sale_price_affiliated_discount_prc",
    "agencyVat": "agency_vat",
    "salePriceWholesaleDiscountPrc": "sale_price_wholesale_discount_prc",
    "b2bCustomerTin": "b2b_customer_tin",
    # warehouseLogisticsCoeff и paidWithSocialCertificate — новые поля, колонок нет → raw_data
}

# Поля, которые есть только в новом API (колонок в SalesReport нет — сохраняются в raw_data)
SALES_REPORT_NEW_FIELDS = ("title", "paidWithSocialCertificate", "warehouseLogisticsCoeff")

# Поля старого метода без аналога в новом: у будущих строк эти колонки останутся NULL
SALES_REPORT_REMOVED_FIELDS = {
    "suppliercontract_code": "Договор",
    "ppvz_supplier_id": "Номер партнёра",
}

# Новый API отдаёт суммы строками («376.99», «1.349», «-1», иногда «»)
SALES_REPORT_FLOAT_FIELDS = {
    "retail_price", "retail_amount", "retail_price_withdisc_rub", "commission_percent",
    "product_discount_for_report", "supplier_promo", "ppvz_spp_prc", "ppvz_kvw_prc_base",
    "ppvz_kvw_prc", "ppvz_sales_commission", "ppvz_for_pay", "ppvz_reward", "ppvz_vw",
    "ppvz_vw_nds", "sup_rating_prc_up", "is_kgvp_v2", "acquiring_fee", "acquiring_percent",
    "delivery_rub", "rebill_logistic_cost", "dlv_prc", "penalty", "additional_payment",
    "storage_fee", "deduction", "acceptance", "installment_cofinancing_amount",
    "wibes_wb_discount_percent", "cashback_amount", "cashback_discount",
    "cashback_commission_change", "payment_schedule", "seller_promo_discount",
    "loyalty_discount", "sale_price_promocode_discount_prc", "sale_price_affiliated_discount_prc",
    "sale_price_wholesale_discount_prc", "agency_vat",
}

SALES_REPORT_INT_FIELDS = {
    "realizationreport_id", "rrd_id", "gi_id", "assembly_id", "nm_id", "shk_id", "quantity",
    "sale_percent", "delivery_amount", "return_amount", "report_type", "ppvz_office_id",
    "seller_promo_id", "loyalty_id",
}

# order_dt/sale_dt — дата со временем в UTC (суффикс Z)
SALES_REPORT_DATETIME_FIELDS = {"order_dt", "sale_dt"}
# Даты отчёта — только дата в часовом поясе Москвы
SALES_REPORT_DATE_FIELDS = {
    "date_from", "date_to", "create_dt", "rr_dt", "fix_tariff_date_from", "fix_tariff_date_to",
}


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        logger.warning(f"Отчёт реализации: не удалось разобрать число {value!r}, поле пропущено")
        return None


def _to_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    s = str(value).strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        try:
            return int(float(s.replace(",", ".")))
        except ValueError:
            logger.warning(f"Отчёт реализации: не удалось разобрать целое {value!r}, поле пропущено")
            return None


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    s = str(value).strip() if value is not None else ""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        logger.warning(f"Отчёт реализации: не удалось разобрать дату {value!r}, поле пропущено")
        return None


def _norm_datetime_utc(value: Any) -> str | None:
    """order_dt/sale_dt приводим к тому же виду, что уже лежит в БД.

    История загружена старым методом, где время приходило в UTC с суффиксом Z
    и хранилось как naive-UTC ('2026-09-10T21:00:00'). Сохраняем эту же конвенцию,
    поэтому любую дату со смещением переводим в UTC и отбрасываем суффикс.
    """
    dt = _parse_dt(value)
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _norm_date_msk(value: Any) -> str | None:
    """Даты отчёта (date_from/date_to/create_dt/rr_dt, даты фиксации) — дата по Москве."""
    dt = _parse_dt(value)
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(MOSCOW_TZ)
    return dt.strftime("%Y-%m-%d")


def normalize_sales_report_row(row: dict) -> dict:
    """Строка нового API → словарь в терминах колонок SalesReport.

    Ключ ``_raw`` хранит исходную строку ответа (camelCase-нотация WB), ключ ``_api`` — маркер метода.
    """
    out: dict[str, Any] = {}
    for new_key, value in row.items():
        old_key = SALES_REPORT_FIELD_MAP.get(new_key)
        if old_key is None:
            continue  # новое/неизвестное поле остаётся в _raw
        if old_key in SALES_REPORT_FLOAT_FIELDS:
            value = _to_float(value)
        elif old_key in SALES_REPORT_INT_FIELDS:
            value = _to_int(value)
        elif old_key in SALES_REPORT_DATETIME_FIELDS:
            value = _norm_datetime_utc(value)
        elif old_key in SALES_REPORT_DATE_FIELDS:
            value = _norm_date_msk(value)
        out[old_key] = value
    out["_raw"] = row
    out["_api"] = "finance/v1/sales-reports/detailed"
    return out


def _ratelimit_headers(resp: httpx.Response) -> dict[str, str]:
    keys = ("X-Ratelimit-Limit", "X-Ratelimit-Remaining", "X-Ratelimit-Reset", "X-Ratelimit-Retry")
    return {k: resp.headers[k] for k in keys if resp.headers.get(k)}


def _retry_after_seconds(resp: httpx.Response, default: int = 65) -> int:
    for key in ("X-Ratelimit-Retry", "Retry-After", "X-Ratelimit-Reset"):
        raw = resp.headers.get(key)
        if raw and str(raw).strip().isdigit():
            return int(str(raw).strip())
    return default


async def _fetch_sales_report_page(token: str, payload: dict, page: int) -> list[dict] | None:
    """Одна страница отчёта реализации. ``None`` — данных больше нет (ответ 204)."""
    headers = {"Authorization": token}
    max_attempts = 5

    for attempt in range(1, max_attempts + 1):
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"{WB_FINANCE_BASE}{SALES_REPORT_PATH}",
                    headers=headers,
                    json=payload,
                )
        except Exception as e:
            logger.warning(f"Отчёт реализации (finance-api): страница {page}, попытка {attempt}/{max_attempts}: {type(e).__name__}: {e}")
            if attempt == max_attempts:
                raise RuntimeError(f"Отчёт реализации (finance-api): сеть/таймаут — {e}") from e
            await asyncio.sleep(10 * attempt)
            continue

        limits = _ratelimit_headers(resp)
        logger.info(
            f"Отчёт реализации (finance-api): страница {page}, rrdId={payload['rrdId']}, HTTP {resp.status_code}"
            + (f", лимиты {limits}" if limits else "")
        )

        if resp.status_code == 204:
            return None

        if resp.status_code == 403:
            try:
                detail = str(resp.json().get("detail") or resp.text)
            except Exception:
                detail = resp.text
            raise RuntimeError(
                "Отчёт реализации (finance-api): 403 " + detail[:60] +
                ". Нужен токен с категорией «Финансы» (Профиль → Интеграции по API), затем перезапуск."
            )

        if resp.status_code == 429:
            wait = _retry_after_seconds(resp)
            if wait > SALES_REPORT_MAX_RETRY_WAIT:
                raise RuntimeError(
                    f"Отчёт реализации (finance-api): лимит исчерпан, WB разрешает повтор через {wait} с "
                    f"(X-Ratelimit-Retry). Повтор не выполняем, чтобы не продлевать блокировку."
                )
            if attempt == max_attempts:
                raise RuntimeError(f"Отчёт реализации (finance-api): 429 после {max_attempts} попыток")
            logger.warning(f"Отчёт реализации: 429, повтор через {wait} с (попытка {attempt}/{max_attempts})")
            await asyncio.sleep(wait + 2)
            continue

        if resp.status_code >= 500:
            logger.warning(f"Отчёт реализации: HTTP {resp.status_code}, попытка {attempt}/{max_attempts}")
            if attempt == max_attempts:
                raise RuntimeError(f"Отчёт реализации (finance-api): сервер вернул {resp.status_code}")
            await asyncio.sleep(15 * attempt)
            continue

        if resp.status_code >= 400:
            body = resp.text[:300].replace("\n", " ")
            logger.error(f"Отчёт реализации (finance-api): HTTP {resp.status_code}, тело: {body}")
            raise RuntimeError(f"Отчёт реализации (finance-api): HTTP {resp.status_code}: {body}")

        try:
            rows = resp.json()
        except ValueError:
            body = resp.text[:300].replace("\n", " ")
            logger.error(f"Отчёт реализации (finance-api): ответ не JSON: {body}")
            raise RuntimeError(f"Отчёт реализации (finance-api): ответ не JSON: {body}")
        return rows if isinstance(rows, list) else []

    raise RuntimeError("Отчёт реализации (finance-api): не удалось получить страницу отчёта")


async def fetch_sales_report(token: str, date_from: str, date_to: str, period: str = "daily") -> list[dict[str, Any]]:
    """Детализация к отчётам реализации за период (finance-api).

    date_from/date_to — даты отчёта в формате YYYY-MM-DD (часовой пояс Москвы).
    Лимит метода: 1 запрос в минуту на аккаунт, поэтому между страницами ждём 65 секунд.
    Возвращает строки в терминах колонок SalesReport (карта — SALES_REPORT_FIELD_MAP).
    """
    logger.info(f"Отчёт реализации (finance-api): dateFrom={date_from}, dateTo={date_to}, period={period}")
    results: list[dict[str, Any]] = []
    rrd_id = 0
    limit = SALES_REPORT_PAGE_LIMIT
    page = 1

    while True:
        payload = {
            "dateFrom": date_from,
            "dateTo": date_to,
            "limit": limit,
            "rrdId": rrd_id,
            "period": period,
        }
        rows = await _fetch_sales_report_page(token, payload, page)

        if rows is None:
            logger.info(f"Отчёт реализации (finance-api): получен 204, данных больше нет (строк: {len(results)})")
            break
        if not rows:
            logger.info("Отчёт реализации (finance-api): пустой ответ, завершаем")
            break

        results.extend(normalize_sales_report_row(r) for r in rows)
        logger.info(f"Отчёт реализации (finance-api): страница {page} — {len(rows)} строк, всего {len(results)}")

        if len(rows) < limit:
            logger.info(f"Отчёт реализации (finance-api): получено {len(rows)} < {limit}, последняя страница")
            break

        # Курсор — максимальный rrdId в странице (WB не гарантирует порядок строк),
        # с защитой от нерастущего курсора, чтобы не зациклиться.
        new_rrd_id = max((r.get("rrdId") or 0) for r in rows)
        if new_rrd_id <= rrd_id:
            logger.warning(f"Отчёт реализации (finance-api): курсор не вырос ({rrd_id} → {new_rrd_id}), завершаем")
            break

        rrd_id = new_rrd_id
        page += 1
        logger.info(f"Отчёт реализации (finance-api): следующая страница с rrdId={rrd_id}, ждём 65 сек...")
        await asyncio.sleep(65)

    logger.info(f"Отчёт реализации (finance-api): всего получено {len(results)} строк")
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