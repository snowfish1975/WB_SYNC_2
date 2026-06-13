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
from app.wb_analytics_client import fetch_sales_funnel, fetch_stock_by_offices, fetch_item_rating
from app.crud import (
    upsert_characteristic, upsert_stock, log_sync, upsert_price,
    upsert_sales_report_row, upsert_orders_bulk, upsert_sales_bulk,
    clear_characteristics, clear_stocks, clear_old_orders, clear_old_sales,
    clear_sales_report, get_tokens_from_db, get_token_mapping_from_db, load_token_mapping,
    clear_shelf_metrics, upsert_shelf_metric,
    clear_funnel_metrics, upsert_funnel_metric,
    clear_stock_by_offices, upsert_stock_by_office,
    clear_item_ratings, upsert_item_rating,
)
from app.database import SessionLocal

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

        # --- Воронка продаж (sales-funnel v3, 30 дней) ---
        try:
            now_ms = datetime.now(MOSCOW_TZ)
            date_from = (now_ms - timedelta(days=30)).strftime("%Y-%m-%d")
            date_to = now_ms.strftime("%Y-%m-%d")
            period_start = datetime.strptime(date_from, "%Y-%m-%d")
            period_end = datetime.strptime(date_to, "%Y-%m-%d")

            logger.info(f"[{name}] очистка метрик витрины...")
            clear_shelf_metrics(db, tid)
            logger.info(f"[{name}] загрузка воронки продаж ({date_from} — {date_to})...")
            funnel_data = await fetch_sales_funnel(token, date_from=date_from, date_to=date_to)
            shelf_count = 0
            funnel_count = 0
            for item in funnel_data:
                upsert_shelf_metric(db, tid, item, period_start, period_end)
                shelf_count += 1
                upsert_funnel_metric(db, tid, item, period_start, period_end)
                funnel_count += 1
            db.commit()
            result["shelf_count"] = shelf_count
            result["funnel_count"] = funnel_count
            del funnel_data
            gc.collect()
            logger.info(f"[{name}] Воронка продаж сохранена: {shelf_count} товаров")

            # --- Остатки по складам ---
            logger.info(f"[{name}] загрузка остатков по складам...")
            offices_data = await fetch_stock_by_offices(token, date_from=date_from, date_to=date_to)
            offices_count = 0
            for region in offices_data:
                for office in region.get("offices", []):
                    upsert_stock_by_office(db, tid, region, office, period_start, period_end)
                    offices_count += 1
            db.commit()
            result["offices_count"] = offices_count
            del offices_data
            gc.collect()
            logger.info(f"[{name}] Остатки по складам: {offices_count} записей")

            # --- Оценки товаров (end date не может быть сегодня) ---
            yesterday = (now_ms - timedelta(days=1)).strftime("%Y-%m-%d")
            logger.info(f"[{name}] загрузка оценок товаров...")
            ratings_data, seller_rating = await fetch_item_rating(token, date_from=date_from, date_to=yesterday)
            ratings_count = 0
            for card in ratings_data:
                upsert_item_rating(db, tid, card, seller_rating, period_start, period_end)
                ratings_count += 1
            db.commit()
            result["ratings_count"] = ratings_count
            del ratings_data
            gc.collect()
            logger.info(f"[{name}] Оценки товаров: {ratings_count} товаров, рейтинг продавца: {seller_rating}")

        except Exception as e:
            db.rollback()
            logger.error(f"[{name}] ошибка аналитики: {e}")
            result["analytics_error"] = str(e)[:200]

        log_sync(db, tid, "ok", records=chars_count + stocks_count + orders_count + prices_count + sales_count + result.get("shelf_count", 0) + result.get("funnel_count", 0) + result.get("offices_count", 0) + result.get("ratings_count", 0))
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

        # --- Отчёт реализации (полная перезапись — только вчера) ---
        logger.info(f"[{name}] очистка отчёта реализации...")
        clear_sales_report(db, tid)
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