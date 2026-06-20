import os
import asyncio
import hashlib
import logging
import httpx
import json
import gc
from datetime import datetime, timedelta, timezone

from app.wb_client import (
    fetch_product_characteristics,
    fetch_stocks,
    fetch_orders_last_40_days_stream,
    fetch_prices,
    fetch_sales_report,
    fetch_sales_stream,
)
from app.wb_analytics_client import fetch_sales_funnel, fetch_stock_by_offices, fetch_item_rating, fetch_ad_campaigns, fetch_ad_campaign_details, fetch_ad_stats, fetch_ad_expenses, fetch_ad_search_clusters
from app.returns_client import fetch_claims
from app.logistics_client import fetch_warehouses, fetch_tariffs_box, fetch_tariffs_pallet, fetch_tariffs_acceptance, fetch_tariffs_return
from app.crud import (
    upsert_characteristic, upsert_stock, log_sync, upsert_price,
    upsert_sales_report_row, upsert_orders_bulk, upsert_sales_bulk,
    clear_characteristics, clear_stocks, clear_old_orders, clear_old_sales,
    clear_sales_report, get_tokens_from_db, get_token_mapping_from_db, load_token_mapping,
    clear_shelf_metrics, upsert_shelf_metric, clean_old_shelf_metrics,
    clear_funnel_metrics, upsert_funnel_metric,
    clear_stock_by_offices, upsert_stock_by_office,
    clear_item_ratings, upsert_item_rating,
    clear_ad_campaigns, upsert_ad_campaign, upsert_ad_campaign_detail,
    clear_ad_stats, upsert_ad_stats,
    clear_ad_expenses, upsert_ad_expense,
    clear_ad_search_clusters, upsert_ad_search_cluster,
    upsert_claim,
    upsert_warehouse, clear_warehouses,
    upsert_tariff_box, clear_tariff_boxes,
    upsert_tariff_pallet, clear_tariff_pallets,
    upsert_tariff_acceptance, clear_tariff_acceptances,
    upsert_tariff_return, clear_tariff_returns,
)
from app.database import SessionLocal
from app.models import ShelfMetric, Warehouse

logger = logging.getLogger(__name__)

MOSCOW_TZ = timezone(timedelta(hours=3))

# --- Telegram ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "356741753")


def load_tokens_from_json() -> list[dict]:
    """Загрузка токенов из БД с fallback на env var."""
    db_tokens = get_tokens_from_db()
    if db_tokens:
        valid = [t for t in db_tokens if t.get("token")]
        if len(valid) < len(db_tokens):
            logger.warning(f"Пропущено {len(db_tokens) - len(valid)} кабинетов без сохранённого токена")
        logger.info(f"Загружено {len(valid)} кабинетов из БД")
        return valid
    
    raw = os.getenv("WB_TOKENS_JSON", "{}")
    try:
        data = json.loads(raw)
        if not data:
            logger.warning("WB_TOKENS_JSON пуст или не задан")
            return []
        tokens_list = []
        for name, token in data.items():
            if token and name:
                tokens_list.append({
                    "name": name,
                    "token": token,
                    "cabinet_id": token_id(token)
                })
        logger.info(f"Загружено {len(tokens_list)} кабинетов из WB_TOKENS_JSON")
        return tokens_list
    except json.JSONDecodeError as e:
        logger.error(f"Ошибка парсинга WB_TOKENS_JSON: {e}")
        return []


def get_tokens() -> list[str]:
    tokens_data = load_tokens_from_json()
    if tokens_data:
        return [item["token"] for item in tokens_data]
    raw = os.getenv("WB_TOKENS", "")
    return [t.strip() for t in raw.split(",") if t.strip()]


def get_token_mapping() -> dict[str, str]:
    """Получение маппинга cabinet_id → seller_name из БД или env var."""
    return load_token_mapping()


def get_cabinets_list() -> list[dict]:
    return load_tokens_from_json()


def token_id(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:32]


async def send_telegram_message(message: str):
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN не задан, сообщение не отправлено")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            response = await client.post(
                url,
                json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": message,
                    "parse_mode": "HTML",
                },
            )
            if response.status_code == 200:
                logger.info("Сообщение отправлено в Telegram")
            else:
                logger.error(f"Ошибка Telegram: {response.text}")
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение: {e}")


# --- SYNC ONE (основная цепь без отчёта реализации) ---
async def sync_one_cabinet(token: str, name: str) -> dict:
    tid = token_id(token)
    db = SessionLocal()

    result = {
        "tid": tid,
        "name": name,
        "chars_count": 0,
        "stocks_count": 0,
        "orders_count": 0,
        "prices_count": 0,
        "sales_count": 0,
        "shelf_count": 0,
        "funnel_count": 0,
        "offices_count": 0,
        "ratings_count": 0,
        "ad_campaigns": 0,
        "ad_stats_camps": 0,
        "ad_expenses": 0,
        "orders_error": None,
        "error": None,
    }

    try:
        # --- Характеристики (полная перезапись) ---
        logger.info(f"[{name}] очистка характеристик...")
        clear_characteristics(db, tid)
        logger.info(f"[{name}] синхронизация характеристик...")
        cards = await fetch_product_characteristics(token, nm_ids=[])
        chars_count = 0
        for card in cards:
            nm_id = card.get("nmID")
            if nm_id:
                upsert_characteristic(db, tid, nm_id, card)
                chars_count += 1
        db.commit()
        result["chars_count"] = chars_count
        del cards
        gc.collect()
        logger.info(f"[{name}] характеристики сохранены ({chars_count})")

        # --- Остатки (полная перезапись) ---
        logger.info(f"[{name}] очистка остатков...")
        clear_stocks(db, tid)
        logger.info(f"[{name}] синхронизация остатков...")
        stocks = await fetch_stocks(token)
        stocks_count = 0
        for item in stocks:
            upsert_stock(db, tid, item)
            stocks_count += 1
        db.commit()
        result["stocks_count"] = stocks_count
        del stocks
        gc.collect()
        logger.info(f"[{name}] остатки сохранены ({stocks_count})")

        # --- Заказы (скользящее окно 40 дней) ---
        logger.info(f"[{name}] синхронизация заказов...")
        orders_count = 0
        try:
            async for orders_chunk in fetch_orders_last_40_days_stream(token):
                upsert_orders_bulk(db, tid, orders_chunk)
                orders_count += len(orders_chunk)
                del orders_chunk
                gc.collect()
            result["orders_count"] = orders_count
            logger.info(f"[{name}] заказы сохранены ({orders_count})")
        except Exception as e:
            db.rollback()
            logger.error(f"[{name}] ошибка при синхронизации заказов: {e}")
            result["orders_error"] = str(e)[:200]

        # --- Цены (upsert, без очистки — перезаписываются по ключу) ---
        logger.info(f"[{name}] синхронизация цен...")
        prices = await fetch_prices(token)
        prices_count = 0
        for item in prices:
            for size in item.get("sizes", []):
                try:
                    upsert_price(db, tid, item, size)
                    prices_count += 1
                except Exception as e:
                    logger.warning(f"[{name}] ошибка price: {e}")
        db.commit()
        result["prices_count"] = prices_count
        del prices
        gc.collect()
        logger.info(f"[{name}] цены сохранены ({prices_count})")

        # --- Продажи (скользящее окно 40 дней) ---
        logger.info(f"[{name}] синхронизация продаж...")
        sales_count = 0
        try:
            async for sales_chunk in fetch_sales_stream(token):
                upsert_sales_bulk(db, tid, sales_chunk)
                sales_count += len(sales_chunk)
                del sales_chunk
                gc.collect()
            result["sales_count"] = sales_count
            logger.info(f"[{name}] продажи сохранены ({sales_count})")
        except Exception as e:
            db.rollback()
            logger.error(f"[{name}] ошибка при синхронизации продаж: {e}")
            result["sales_error"] = str(e)[:200]

        # --- Очистка старых заказов и продаж (старше 40 дней) ---
        logger.info(f"[{name}] очистка старых заказов и продаж...")
        clear_old_orders(db, tid, days=40)
        clear_old_sales(db, tid, days=40)

        # --- Воронка продаж (sales-funnel v3) ---
        # FunnelMetric: агрегат за 30 дней (для вкладки Воронка)
        # ShelfMetric: подневные данные (для РНП сводки), каждый день — 1 запрос
        try:
            now_ms = datetime.now(MOSCOW_TZ)
            date_from_30 = (now_ms - timedelta(days=30)).strftime("%Y-%m-%d")
            date_to = now_ms.strftime("%Y-%m-%d")
            period_start_30 = datetime.strptime(date_from_30, "%Y-%m-%d")
            period_end = datetime.strptime(date_to, "%Y-%m-%d")

            logger.info(f"[{name}] загрузка агрегата воронки (FunnelMetric, 30 дней)...")
            funnel_data = await fetch_sales_funnel(token, date_from=date_from_30, date_to=date_to)
            funnel_count = 0
            for item in funnel_data:
                upsert_funnel_metric(db, tid, item, period_start_30, period_end)
                funnel_count += 1
            db.commit()
            result["funnel_count"] = funnel_count
            logger.info(f"[{name}] FunnelMetric сохранена: {funnel_count} товаров")
            del funnel_data
            gc.collect()

            date_from_1 = (now_ms - timedelta(days=1)).strftime("%Y-%m-%d")

            from sqlalchemy import func as sa_func
            existing_days = db.query(sa_func.count(sa_func.distinct(ShelfMetric.period_end))).filter(
                ShelfMetric.cabinet_id == tid
            ).scalar() or 0

            days_to_load = []
            if existing_days < 40:
                target_days = 40
                for i in range(target_days, 0, -1):
                    d = (now_ms - timedelta(days=i)).strftime("%Y-%m-%d")
                    exists = db.query(sa_func.count()).filter(
                        ShelfMetric.cabinet_id == tid,
                        ShelfMetric.period_end == datetime.strptime(d, "%Y-%m-%d"),
                    ).scalar() or 0
                    if exists == 0:
                        days_to_load.append(d)
                logger.info(f"[{name}] Backfill: нужно загрузить {len(days_to_load)} дней (есть {existing_days} из 40)")
            else:
                days_to_load.append(date_from_1)

            shelf_total = 0
            for day_str in days_to_load:
                logger.info(f"[{name}] загрузка воронки за {day_str}...")
                shelf_data = await fetch_sales_funnel(token, date_from=day_str, date_to=day_str)
                shelf_day = datetime.strptime(day_str, "%Y-%m-%d")
                shelf_count = 0
                for item in shelf_data:
                    upsert_shelf_metric(db, tid, item, shelf_day, shelf_day)
                    shelf_count += 1
                db.commit()
                shelf_total += shelf_count
                del shelf_data
                gc.collect()
                await asyncio.sleep(20)

            result["shelf_count"] = shelf_total
            logger.info(f"[{name}] ShelfMetric подневная: {shelf_total} записей за {len(days_to_load)} дней")

            clean_old_shelf_metrics(db, tid, days=40)
            logger.info(f"[{name}] Очистка ShelfMetric старше 40 дней завершена")

            # --- Остатки по складам ---
            logger.info(f"[{name}] загрузка остатков по складам...")
            offices_data = await fetch_stock_by_offices(token, date_from=date_from_30, date_to=date_to)
            offices_count = 0
            for region in offices_data:
                for office in region.get("offices", []):
                    upsert_stock_by_office(db, tid, region, office, period_start_30, period_end)
                    offices_count += 1
            db.commit()
            result["offices_count"] = offices_count
            del offices_data
            gc.collect()
            logger.info(f"[{name}] Остатки по складам: {offices_count} записей")

            # --- Оценки товаров (end date не может быть сегодня) ---
            yesterday = (now_ms - timedelta(days=1)).strftime("%Y-%m-%d")
            logger.info(f"[{name}] загрузка оценок товаров...")
            clear_item_ratings(db, tid)
            ratings_data, seller_rating = await fetch_item_rating(token, date_from=date_from_30, date_to=yesterday)
            ratings_count = 0
            for card in ratings_data:
                upsert_item_rating(db, tid, card, seller_rating, period_start_30, period_end)
                ratings_count += 1
            db.commit()
            result["ratings_count"] = ratings_count
            del ratings_data
            gc.collect()
            logger.info(f"[{name}] Оценки товаров: {ratings_count} товаров, рейтинг продавца: {seller_rating}")

            # --- Рекламные кампании ---
            logger.info(f"[{name}] загрузка рекламных кампаний...")
            try:
                ad_campaigns = await fetch_ad_campaigns(token)
                clear_ad_campaigns(db, tid)
                for camp in ad_campaigns:
                    upsert_ad_campaign(db, tid, camp["advertId"], camp["type"], camp["status"], camp.get("changeTime"))
                db.commit()
                logger.info(f"[{name}] Рекламные кампании: {len(ad_campaigns)}")

                # Статистика по активным кампаниям (max 50 за раз)
                active_ids = [c["advertId"] for c in ad_campaigns if c["status"] in (9, 7, 11)][:50]
                all_details = []
                if active_ids:
                    # Загружаем детали кампаний (названия и т.д.)
                    for i in range(0, len(active_ids), 50):
                        batch = active_ids[i:i+50]
                        details = await fetch_ad_campaign_details(token, batch) or []
                        all_details.extend(details)
                        for advert in details:
                            if advert:
                                upsert_ad_campaign_detail(db, tid, advert)
                    db.commit()

                    all_stats = []
                    for i in range(0, len(active_ids), 50):
                        batch = active_ids[i:i+50]
                        stats_data = await fetch_ad_stats(token, batch, date_from_30, date_to) or []
                        all_stats.extend(stats_data)
                        if i + 50 < len(active_ids):
                            await asyncio.sleep(65)
                    if all_stats:
                        clear_ad_stats(db, tid)
                        for camp_stats in all_stats:
                            if not camp_stats:
                                continue
                            aid = camp_stats.get("advertId", 0)
                            upsert_ad_stats(db, tid, aid, period_start_30, {
                                "views": camp_stats.get("views", 0),
                                "clicks": camp_stats.get("clicks", 0),
                                "ctr": camp_stats.get("ctr", 0),
                                "cpc": camp_stats.get("cpc", 0),
                                "cr": camp_stats.get("cr", 0),
                                "atbs": camp_stats.get("atbs", 0),
                                "orders": camp_stats.get("orders", 0),
                                "shks": camp_stats.get("shks", 0),
                                "canceled": camp_stats.get("canceled", 0),
                                "sum": camp_stats.get("sum", 0),
                                "sum_price": camp_stats.get("sum_price", 0),
                            }, camp_stats)
                        db.commit()
                    logger.info(f"[{name}] Статистика рекламы: {len(all_stats)} кампаний")

                # Затраты (отдельный try — не зависит от статистики)
                try:
                    expenses = await fetch_ad_expenses(token, date_from_30, date_to)
                    clear_ad_expenses(db, tid)
                    for exp in expenses:
                        upsert_ad_expense(db, tid, exp)
                    db.commit()
                    result["ad_expenses"] = len(expenses)
                    logger.info(f"[{name}] Затраты на рекламу: {len(expenses)}")
                except Exception as e:
                    logger.error(f"[{name}] ошибка загрузки затрат: {e}")

                result["ad_campaigns"] = len(ad_campaigns)
                result["ad_stats_camps"] = len(active_ids) if active_ids else 0
                
                # Поисковые кластеры: извлекаем advert_id + nm_id из деталей кампаний
                clusters_count = 0
                try:
                    cluster_items = []
                    for advert in all_details:
                        if not advert:
                            continue
                        aid = advert.get("id", 0)
                        nm_settings = advert.get("nm_settings", []) or []
                        for ns in nm_settings:
                            nm_id = ns.get("nm_id")
                            if nm_id:
                                cluster_items.append({"advert_id": aid, "nm_id": nm_id})
                    
                    if cluster_items:
                        clusters_data = await fetch_ad_search_clusters(token, cluster_items, date_from_30, date_to)
                        seen_aids = set()
                        for camp_data in clusters_data:
                            aid = camp_data.get("advert_id", 0)
                            nm = camp_data.get("nm_id", 0)
                            if aid not in seen_aids:
                                clear_ad_search_clusters(db, tid, aid)
                                seen_aids.add(aid)
                            for kw in camp_data.get("stats", []):
                                kw["nm_id"] = nm
                                upsert_ad_search_cluster(db, tid, aid, kw)
                                clusters_count += 1
                        db.commit()
                except Exception as e:
                    logger.warning(f"[{name}] Ошибка загрузки поисковых кластеров: {e}")
                result["ad_clusters"] = clusters_count
                
                del ad_campaigns
                gc.collect()
                logger.info(f"[{name}] Реклама: кампании={result.get('ad_campaigns', 0)}, статистика={result.get('ad_stats_camps', 0)}, затраты={result.get('ad_expenses', 0)}")
            except Exception as e:
                logger.error(f"[{name}] ошибка рекламы: {e}")

        except Exception as e:
            db.rollback()
            logger.error(f"[{name}] ошибка аналитики: {e}")
            result["analytics_error"] = str(e)[:200]

        # --- Возвраты / Претензии покупателей ---
        try:
            logger.info(f"[{name}] загрузка claims (возвраты)...")
            claims_data = await fetch_claims(token, is_archive=False)
            claims_count = 0
            for claim in claims_data:
                upsert_claim(db, tid, claim)
                claims_count += 1
            db.commit()
            result["claims_count"] = claims_count
            logger.info(f"[{name}] Claims (возвраты): {claims_count}")
        except Exception as e:
            logger.error(f"[{name}] ошибка claims: {e}")

        # --- Логистика: склады и тарифы (один раз, не per-cabinet) ---
        # Загружаем только если ещё не загружены сегодня
        try:
            from sqlalchemy import func as sa_func
            wh_count = db.query(sa_func.count(Warehouse.id)).scalar() or 0
            if wh_count == 0:
                logger.info("Загрузка складов и тарифов (первый запуск)...")
                warehouses = await fetch_warehouses(token)
                clear_warehouses(db)
                for wh in warehouses:
                    upsert_warehouse(db, wh)
                db.commit()
                logger.info(f"Склады WB: {len(warehouses)}")

                from datetime import date
                today = date.today().strftime("%Y-%m-%d")

                tariffs_box = await fetch_tariffs_box(token, today)
                clear_tariff_boxes(db)
                for wh in (tariffs_box.get("warehouseList") or []):
                    upsert_tariff_box(db, wh, today)
                db.commit()
                logger.info(f"Тарифы короба: {len(tariffs_box.get('warehouseList') or [])}")

                tariffs_pallet = await fetch_tariffs_pallet(token, today)
                clear_tariff_pallets(db)
                for wh in (tariffs_pallet.get("warehouseList") or []):
                    upsert_tariff_pallet(db, wh, today)
                db.commit()
                logger.info(f"Тарифы паллеты: {len(tariffs_pallet.get('warehouseList') or [])}")

                acceptances = await fetch_tariffs_acceptance(token)
                clear_tariff_acceptances(db)
                for item in acceptances:
                    upsert_tariff_acceptance(db, item)
                db.commit()
                logger.info(f"Тарифы приёмки: {len(acceptances)}")

                tariffs_return = await fetch_tariffs_return(token, today)
                clear_tariff_returns(db)
                for wh in (tariffs_return.get("warehouseList") or []):
                    upsert_tariff_return(db, wh, today)
                db.commit()
                logger.info(f"Тарифы возврата: {len(tariffs_return.get('warehouseList') or [])}")
        except Exception as e:
            logger.error(f"Ошибка загрузки логистики: {e}")

        log_sync(db, tid, "ok", records=chars_count + stocks_count + orders_count + prices_count + sales_count + result.get("shelf_count", 0) + result.get("funnel_count", 0) + result.get("offices_count", 0) + result.get("ratings_count", 0) + result.get("ad_expenses", 0) + result.get("claims_count", 0))
        db.commit()

    except Exception as e:
        logger.error(f"[{name}] ошибка: {e}")
        db.rollback()
        result["error"] = str(e)[:200]
        try:
            log_sync(db, tid, "error", message=str(e)[:490])
            db.commit()
        except Exception as log_err:
            logger.error(f"[{name}] не удалось записать лог: {log_err}")
    finally:
        db.close()

    return result


# --- SYNC SALES REPORT (отдельная цепь) ---
async def sync_sales_report_one_cabinet(token: str, name: str) -> dict:
    """Синхронизация отчёта реализации только за вчерашний день."""
    tid = token_id(token)
    db = SessionLocal()
    result = {
        "name": name,
        "sales_report_count": 0,
        "error": None,
    }
    try:
        now = datetime.now(MOSCOW_TZ)
        yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")

        # --- Отчёт реализации (накопление — загружаем только вчера, не очищаем старое) ---
        logger.info(f"[{name}] отчёт реализации за {yesterday}...")
        rows = await fetch_sales_report(token, date_from=yesterday, date_to=yesterday)

        count = 0
        for row in rows:
            upsert_sales_report_row(db, tid, row)
            count += 1

        db.commit()
        result["sales_report_count"] = count
        logger.info(f"[{name}] отчёт реализации сохранён ({count} строк)")

        log_sync(db, tid, "ok_sales_report", records=count)
        db.commit()

    except Exception as e:
        db.rollback()
        logger.error(f"[{name}] ошибка отчёта реализации: {e}")
        result["error"] = str(e)[:200]
        try:
            log_sync(db, tid, "error_sales_report", message=str(e)[:490])
            db.commit()
        except Exception as log_err:
            logger.error(f"[{name}] не удалось записать лог: {log_err}")
    finally:
        db.close()

    return result


# --- BACKFILL SALES REPORT (набор исторических данных) ---
def run_sales_report_backfill(days: int = 40):
    """Загрузка отчёта реализации за последние N дней для всех кабинетов.
    Определяет какие даты уже есть в БД и загружает только недостающие.
    """
    from app.models import SalesReport
    cabinets = get_cabinets_list()
    if not cabinets:
        logger.warning("Нет кабинетов для backfill отчёта реализации")
        return

    logger.info(f"Запуск backfill отчёта реализации за {days} дней для {len(cabinets)} кабинетов")

    async def _run():
        start_time = datetime.now()
        now = datetime.now(MOSCOW_TZ)
        total_rows = 0
        errors = []

        for cabinet in cabinets:
            token = cabinet["token"]
            name = cabinet["name"]
            tid = token_id(token)

            try:
                # Определяем какие даты уже есть в БД
                db = SessionLocal()
                try:
                    from sqlalchemy import func as sa_func
                    existing_dates = set()
                    rows = db.query(
                        sa_func.date(SalesReport.sale_dt).label("day")
                    ).filter(
                        SalesReport.cabinet_id == tid
                    ).group_by(sa_func.date(SalesReport.sale_dt)).all()
                    for r in rows:
                        existing_dates.add(str(r.day))
                finally:
                    db.close()

                # Определяем недостающие даты
                missing_dates = []
                for d in range(1, days + 1):
                    date_str = (now - timedelta(days=d)).strftime("%Y-%m-%d")
                    if date_str not in existing_dates:
                        missing_dates.append(date_str)

                if not missing_dates:
                    logger.info(f"[{name}] все даты за {days} дней уже загружены")
                    continue

                missing_dates.sort()  # От старых к новым
                logger.info(f"[{name}] недостающие даты: {len(missing_dates)} ({missing_dates[0]}...{missing_dates[-1]})")

                # Загружаем по 7 дней за раз (лимит API)
                cabinet_rows = 0
                for i in range(0, len(missing_dates), 7):
                    chunk = missing_dates[i:i+7]
                    date_from = chunk[0]
                    date_to = chunk[-1]

                    rows = await fetch_sales_report(token, date_from=date_from, date_to=date_to)

                    db = SessionLocal()
                    try:
                        for row in rows:
                            upsert_sales_report_row(db, tid, row)
                        db.commit()
                        cabinet_rows += len(rows)
                        logger.info(f"[{name}] {date_from}..{date_to}: {len(rows)} строк")
                    finally:
                        db.close()

                    await asyncio.sleep(65)  # Лимит: 1 запрос в минуту

                total_rows += cabinet_rows
                logger.info(f"[{name}] backfill завершён: {cabinet_rows} строк")

            except Exception as e:
                errors.append(f"{name}: {str(e)[:100]}")
                logger.warning(f"[{name}] ошибка backfill: {e}")

        duration = (datetime.now() - start_time).total_seconds()
        minutes = int(duration // 60)
        seconds = int(duration % 60)

        message = f"📊 <b>Backfill отчёта реализации</b>\n"
        message += f"⏱ Время: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        message += f"⌛️ Длительность: {minutes:02d}:{seconds:02d}\n"
        message += f"📊 Загружено: {total_rows} строк\n"
        if errors:
            message += f"❌ Ошибки: {len(errors)}\n"
            for e in errors[:5]:
                message += f"  • {e}\n"
        else:
            message += "✅ Все кабинеты обработаны"

        await send_telegram_message(message)
        logger.info(message)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_run())
    finally:
        loop.close()


# --- RUN ALL (основная цепь) ---
def run_sync_all():
    cabinets = get_cabinets_list()
    if not cabinets:
        logger.warning("Нет кабинетов для синхронизации. Проверьте WB_TOKENS_JSON")
        return

    logger.info(f"Запущена синхронизация для {len(cabinets)} кабинетов")

    async def _run():
        start_time = datetime.now()
        semaphore = asyncio.Semaphore(1)

        async def sync_with_limit(cabinet):
            async with semaphore:
                return await sync_one_cabinet(cabinet["token"], cabinet["name"])

        tasks = [sync_with_limit(cabinet) for cabinet in cabinets]
        results = await asyncio.gather(*tasks)

        duration = (datetime.now() - start_time).total_seconds()
        hours = int(duration // 3600)
        minutes = int((duration % 3600) // 60)

        message = f"🔄 <b>Выгрузка данных WB</b>\n"
        message += f"⏱ Время: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        message += f"⌛️ Длительность: {hours:02d}:{minutes:02d}\n\n"
        success_count = 0
        error_count = 0

        for r in results:
            if r["error"]:
                error_count += 1
                message += f"❌ <b>{r['name']}</b>\n"
                message += f"   Ошибка: {r['error'][:100]}\n\n"
            else:
                success_count += 1
                message += f"✅ <b>{r['name']}</b>\n"
                message += f"   • Характеристики: {r['chars_count']}\n"
                message += f"   • Остатки: {r['stocks_count']}\n"
                if r.get('orders_count', 0) > 0 or r.get('orders_error'):
                    message += f"   • Заказы: {r.get('orders_count', 0)}\n"
                if r.get('orders_error'):
                    message += f"   ⚠️ Ошибка заказов: {r['orders_error'][:80]}\n"
                message += f"   • Цены: {r['prices_count']}\n"
                message += f"   • Продажи: {r.get('sales_count', 0)}\n"
                if r.get('sales_error'):
                    message += f"   ⚠️ Ошибка продаж: {r['sales_error'][:80]}\n"
                if r.get('shelf_count', 0) > 0 or r.get('funnel_count', 0) > 0:
                    message += f"   • Витрина: {r.get('shelf_count', 0)} | Воронка: {r.get('funnel_count', 0)}\n"
                if r.get('analytics_error'):
                    message += f"   ⚠️ Ошибка аналитики: {r['analytics_error'][:80]}\n"
                message += "\n"

        message += f"📊 <b>Итог:</b> успешно: {success_count}, ошибок: {error_count}"

        await send_telegram_message(message)
        logger.info(f"\n{message}")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_run())
    finally:
        loop.close()


# --- SYNC SEARCH CLUSTERS (отдельная цепь) ---
def run_search_clusters_sync():
    """Отдельный запуск синхронизации поисковых кластеров."""
    cabinets = get_cabinets_list()
    if not cabinets:
        logger.warning("Нет кабинетов для синхронизации поисковых кластеров")
        return

    logger.info(f"Запуск синхронизации поисковых кластеров для {len(cabinets)} кабинетов")

    async def _run():
        start_time = datetime.now()
        total_clusters = 0
        errors = []

        for cabinet in cabinets:
            token = cabinet["token"]
            name = cabinet["name"]
            tid = token_id(token)
            try:
                now = datetime.now(MOSCOW_TZ)
                date_to = now.strftime("%Y-%m-%d")
                date_from = (now - timedelta(days=9)).strftime("%Y-%m-%d")

                campaigns = await fetch_ad_campaigns(token)
                if not campaigns:
                    continue

                advert_ids = [c["advertId"] for c in campaigns]
                details = await fetch_ad_campaign_details(token, advert_ids)

                cluster_items = []
                for advert in details:
                    if not advert:
                        continue
                    aid = advert.get("id", 0)
                    for ns in (advert.get("nm_settings") or []):
                        nm_id = ns.get("nm_id")
                        if nm_id:
                            cluster_items.append({"advert_id": aid, "nm_id": nm_id})

                if not cluster_items:
                    continue

                clusters_data = await fetch_ad_search_clusters(token, cluster_items, date_from, date_to)
                db = SessionLocal()
                try:
                    seen_aids = set()
                    count = 0
                    for camp_data in clusters_data:
                        aid = camp_data.get("advert_id", 0)
                        nm = camp_data.get("nm_id", 0)
                        if aid not in seen_aids:
                            clear_ad_search_clusters(db, tid, aid)
                            seen_aids.add(aid)
                        for kw in camp_data.get("stats", []):
                            kw["nm_id"] = nm
                            upsert_ad_search_cluster(db, tid, aid, kw)
                            count += 1
                    db.commit()
                    total_clusters += count
                    logger.info(f"[{name}] Поисковые кластеры: {count} записей")
                finally:
                    db.close()

                await asyncio.sleep(2)
            except Exception as e:
                errors.append(f"{name}: {str(e)[:100]}")
                logger.warning(f"[{name}] Ошибка поисковых кластеров: {e}")

        duration = (datetime.now() - start_time).total_seconds()
        minutes = int(duration // 60)
        seconds = int(duration % 60)

        message = f"🔍 <b>Поисковые кластеры WB</b>\n"
        message += f"⏱ Время: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        message += f"⌛️ Длительность: {minutes:02d}:{seconds:02d}\n"
        message += f"📊 Записей: {total_clusters}\n"
        if errors:
            message += f"❌ Ошибки: {len(errors)}\n"
            for e in errors[:5]:
                message += f"  • {e}\n"
        else:
            message += "✅ Все кабинеты обработаны"

        await send_telegram_message(message)
        logger.info(message)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_run())
    finally:
        loop.close()


# --- RUN SALES REPORT (отдельная цепь) ---
def run_sales_report_sync():
    """Отдельный запуск синхронизации отчёта реализации за вчера."""
    cabinets = get_cabinets_list()
    if not cabinets:
        logger.warning("Нет кабинетов для синхронизации отчёта реализации")
        return

    logger.info(f"Запуск синхронизации отчёта реализации для {len(cabinets)} кабинетов")

    async def _run():
        start_time = datetime.now()
        results = []
        for cabinet in cabinets:
            result = await sync_sales_report_one_cabinet(cabinet["token"], cabinet["name"])
            results.append(result)

        duration = (datetime.now() - start_time).total_seconds()
        hours = int(duration // 3600)
        minutes = int((duration % 3600) // 60)

        message = f"📊 <b>Отчёт реализации WB (за вчера)</b>\n"
        message += f"⏱ Время: {start_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        message += f"⌛️ Длительность: {hours:02d}:{minutes:02d}\n\n"

        for r in results:
            if r["error"]:
                message += f"❌ <b>{r['name']}</b>: {r['error'][:100]}\n"
            else:
                message += f"✅ <b>{r['name']}</b>: {r['sales_report_count']} строк\n"

        await send_telegram_message(message)
        logger.info(message)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_run())
    finally:
        loop.close()