import os
import asyncio
import hashlib
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Query
from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
import json
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import func, case
from datetime import datetime, timedelta

from app.database import engine, get_db
from app.schemas import (
    ProductCharacteristicOut, SyncLogOut, TokenRequest, StockOut, OrderOut, PriceOut, SalesReportRowOut, SaleOut,
    UserCreate, UserUpdate, UserOut, ApiKeyCreate, ApiKeyOut, WbTokenCreate, WbTokenUpdate, WbTokenOut,
)
from app.crud import (
    get_characteristics, get_sync_logs, get_stocks, get_orders,
    get_prices, get_sales_report, get_sales,
    create_user, get_user_by_id, get_user_by_username, list_users, update_user, delete_user,
    create_api_key, get_api_key_by_hash, list_api_keys, update_api_key_last_used, delete_api_key,
    create_wb_token, get_wb_token_by_hash, list_wb_tokens, update_wb_token, delete_wb_token,
    load_token_mapping,
    get_shelf_metrics, get_funnel_metrics, get_stock_by_offices, get_item_ratings,
    get_ad_campaigns, get_ad_stats, get_ad_expenses,
    get_stock_forecast, get_unit_economics,
    get_ad_search_clusters,
)
from app.models import User, ApiKey, WbToken
from app.models import ProductCharacteristic, Stock, Order, Price, SalesReport, Sale
from app.models import ShelfMetric, FunnelMetric, StockByOffice, ItemRating, AdCampaign, AdCampaignStats, AdExpense, AdSearchCluster
from app.scheduler import run_sync_all, run_sales_report_sync

from fastapi.responses import JSONResponse

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def token_id(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:32]


@asynccontextmanager
async def lifespan(app: FastAPI):
    for attempt in range(1, 11):
        try:
            with engine.connect() as conn:
                conn.execute(__import__("sqlalchemy").text("SELECT 1"))
            logger.info("Подключение к БД успешно")
            break
        except Exception as e:
            logger.warning(f"БД не готова, попытка {attempt}/10: {e}")
            if attempt == 10:
                raise RuntimeError("Не удалось подключиться к БД после 10 попыток")
            await asyncio.sleep(5)

    sync_hour = int(os.getenv("SYNC_HOUR", "3"))
    scheduler.add_job(run_sync_all, "cron", hour=sync_hour, minute=0, id="wb_sync")

    # Отчёт реализации — в 10:30 МСК = 07:30 UTC
    scheduler.add_job(
        run_sales_report_sync,
        "cron",
        hour=7,
        minute=30,
        id="wb_sales_report_sync",
        timezone="UTC",
    )

    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="WB Sync API", description="Синхронизация данных Wildberries", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/dashboard")
def dashboard():
    return FileResponse("static/dashboard.html")

@app.get("/")
def root():
    return {"status": "ok", "message": "WB Sync работает"}


@app.post("/api/products", response_model=list[ProductCharacteristicOut])
def list_products(body: TokenRequest, nm_id: int | None = Query(None), db: Session = Depends(get_db)):
    cid = token_id(body.token)
    mapping = load_token_mapping()
    data = get_characteristics(db, cabinet_id=cid, nm_id=nm_id)
    return [
        {
            **{k: v for k, v in item.__dict__.items() if not k.startswith("_")},
            "seller_name": mapping.get(item.cabinet_id, item.cabinet_id[:8]),
        }
        for item in data
    ]


@app.post("/api/stocks", response_model=list[StockOut])
def list_stocks(body: TokenRequest, nm_id: int | None = Query(None), db: Session = Depends(get_db)):
    cid = token_id(body.token)
    mapping = load_token_mapping()
    data = get_stocks(db, cabinet_id=cid, nm_id=nm_id)
    return [
        {
            **{k: v for k, v in item.__dict__.items() if not k.startswith("_")},
            "seller_name": mapping.get(item.cabinet_id, item.cabinet_id[:8]),
        }
        for item in data
    ]


@app.post("/api/orders", response_model=list[OrderOut])
def list_orders(
    body: TokenRequest,
    fields: str | None = Query(None, description="Поля через запятую: nm_id,date,total_price"),
    days_back: int = Query(40, description="За сколько дней вернуть заказы (макс 90)", ge=1, le=90),
    limit: int = Query(1000, description="Максимальное количество записей", le=500000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    cid = token_id(body.token)
    mapping = load_token_mapping()
    data = get_orders(db, cabinet_id=cid, days_back=days_back, limit=limit, offset=offset, fields=fields)

    requested_fields = [f.strip() for f in fields.split(",")] if fields else None

    result = []
    for item in data:
        row = {k: v for k, v in item.__dict__.items() if not k.startswith("_")}
        row["seller_name"] = mapping.get(item.cabinet_id, item.cabinet_id[:8])
        # datetime не сериализуется в JSON напрямую — конвертируем в строку
        for k, v in row.items():
            if hasattr(v, "isoformat"):
                row[k] = v.isoformat()
        if requested_fields:
            row = {k: v for k, v in row.items() if k in requested_fields}
        result.append(row)

    return JSONResponse(content=result)

@app.post("/api/sales")
def list_sales(
    body: TokenRequest,
    fields: str | None = Query(None, description="Поля через запятую: nm_id,date,total_price"),
    days_back: int = Query(40, description="За сколько дней (макс 90)", ge=1, le=90),
    limit: int = Query(1000, description="Максимальное количество записей", le=500000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Продажи и возвраты за последние N дней."""
    cid = token_id(body.token)
    mapping = load_token_mapping()
    data = get_sales(db, cabinet_id=cid, days_back=days_back, limit=limit, offset=offset, fields=fields)

    requested_fields = [f.strip() for f in fields.split(",")] if fields else None

    result = []
    for item in data:
        row = {k: v for k, v in item.__dict__.items() if not k.startswith("_")}
        row["seller_name"] = mapping.get(item.cabinet_id, item.cabinet_id[:8])
        for k, v in row.items():
            if hasattr(v, "isoformat"):
                row[k] = v.isoformat()
        if requested_fields:
            row = {k: v for k, v in row.items() if k in requested_fields}
        result.append(row)

    return JSONResponse(content=result)

@app.post("/api/prices", response_model=list[PriceOut])
def list_prices(
    body: TokenRequest,
    nm_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    cid = token_id(body.token)
    mapping = load_token_mapping()
    data = get_prices(db, cabinet_id=cid, nm_id=nm_id)
    return [
        {
            **{k: v for k, v in item.__dict__.items() if not k.startswith("_")},
            "seller_name": mapping.get(item.cabinet_id, item.cabinet_id[:8]),
        }
        for item in data
    ]


@app.post("/api/sales-report", response_model=list[SalesReportRowOut])
def list_sales_report(
    body: TokenRequest,
    nm_id: int | None = Query(None, description="Фильтр по артикулу WB"),
    date_from: str | None = Query(None, description="Дата начала YYYY-MM-DD"),
    date_to: str | None = Query(None, description="Дата конца YYYY-MM-DD"),
    limit: int = Query(1000, description="Максимальное количество строк", le=500000),
    db: Session = Depends(get_db),
):
    """Отчёт о продажах по реализации."""
    from datetime import datetime
    cid = token_id(body.token)
    mapping = load_token_mapping()
    dt_from = datetime.strptime(date_from, "%Y-%m-%d") if date_from else None
    dt_to = datetime.strptime(date_to, "%Y-%m-%d") if date_to else None
    data = get_sales_report(db, cabinet_id=cid, nm_id=nm_id, date_from=dt_from, date_to=dt_to, limit=limit)
    return [
        {
            **{k: v for k, v in item.__dict__.items() if not k.startswith("_")},
            "seller_name": mapping.get(item.cabinet_id, item.cabinet_id[:8]),
        }
        for item in data
    ]


@app.get("/api/logs", response_model=list[SyncLogOut])
def list_logs(db: Session = Depends(get_db)):
    mapping = load_token_mapping()
    data = get_sync_logs(db)
    return [
        {
            **{k: v for k, v in item.__dict__.items() if not k.startswith("_")},
            "seller_name": mapping.get(item.cabinet_id, item.cabinet_id[:8]),
        }
        for item in data
    ]


@app.post("/api/sync/trigger")
def trigger_sync():
    import threading
    threading.Thread(target=run_sync_all, daemon=True).start()
    return {"status": "started"}


@app.post("/api/sync/trigger-sales-report")
def trigger_sales_report_sync():
    """Принудительный запуск синхронизации отчёта реализации за вчера."""
    import threading
    threading.Thread(target=run_sales_report_sync, daemon=True).start()
    return {"status": "started"}


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/dashboard/cabinets")
def dashboard_cabinets():
    """Список всех активных кабинетов из БД."""
    mapping = load_token_mapping()
    return [{"cabinet_id": cid, "seller_name": name} for cid, name in mapping.items()]


@app.get("/api/dashboard/summary")
def dashboard_summary(days_back: int = Query(40, ge=1, le=90), db: Session = Depends(get_db)):
    """Сводные цифры: заказы, выручка, возвраты, отмены."""
    mapping = load_token_mapping()
    threshold = datetime.now() - timedelta(days=days_back)

    rows = (
        db.query(
            Order.cabinet_id,
            func.count(Order.id).label("total_orders"),
            func.sum(case((Order.is_cancel == False, Order.price_with_disc), else_=0)).label("revenue"),
            func.sum(case((Order.is_cancel == True, 1), else_=0)).label("cancels"),
        )
        .filter(Order.date >= threshold)
        .group_by(Order.cabinet_id)
        .all()
    )

    result = []
    for r in rows:
        result.append({
            "cabinet_id": r.cabinet_id,
            "seller_name": mapping.get(r.cabinet_id, r.cabinet_id[:8]),
            "total_orders": r.total_orders,
            "revenue": round(float(r.revenue or 0), 2),
            "cancels": r.cancels,
        })
    return result


@app.get("/api/dashboard/sales-chart")
def dashboard_sales_chart(days_back: int = Query(40, ge=1, le=90), db: Session = Depends(get_db)):
    """Продажи по дням для графика."""
    mapping = load_token_mapping()
    threshold = datetime.now() - timedelta(days=days_back)

    rows = (
        db.query(
            Order.cabinet_id,
            func.date(Order.date).label("day"),
            func.count(Order.id).label("orders_count"),
            func.sum(case((Order.is_cancel == False, Order.price_with_disc), else_=0)).label("revenue"),
        )
        .filter(Order.date >= threshold, Order.is_cancel == False)
        .group_by(Order.cabinet_id, func.date(Order.date))
        .order_by(func.date(Order.date))
        .all()
    )

    result = []
    for r in rows:
        result.append({
            "cabinet_id": r.cabinet_id,
            "seller_name": mapping.get(r.cabinet_id, r.cabinet_id[:8]),
            "day": str(r.day),
            "orders_count": r.orders_count,
            "revenue": round(float(r.revenue or 0), 2),
        })
    return result


@app.get("/api/dashboard/top-products")
def dashboard_top_products(days_back: int = Query(40, ge=1, le=90), limit: int = Query(20, le=100), db: Session = Depends(get_db)):
    """Топ товаров по выручке."""
    mapping = load_token_mapping()
    threshold = datetime.now() - timedelta(days=days_back)

    rows = (
        db.query(
            Order.cabinet_id,
            Order.nm_id,
            Order.supplier_article,
            Order.subject,
            Order.brand,
            func.count(Order.id).label("orders_count"),
            func.sum(Order.price_with_disc).label("revenue"),
        )
        .filter(Order.date >= threshold, Order.is_cancel == False, Order.nm_id.isnot(None))
        .group_by(Order.cabinet_id, Order.nm_id, Order.supplier_article, Order.subject, Order.brand)
        .order_by(func.sum(Order.price_with_disc).desc())
        # .limit(limit)
        .all()
    )

    result = []
    for r in rows:
        result.append({
            "cabinet_id": r.cabinet_id,
            "seller_name": mapping.get(r.cabinet_id, r.cabinet_id[:8]),
            "nm_id": r.nm_id,
            "supplier_article": r.supplier_article,
            "subject": r.subject,
            "brand": r.brand,
            "orders_count": r.orders_count,
            "revenue": round(float(r.revenue or 0), 2),
        })
    return result


@app.get("/api/dashboard/characteristics")
def dashboard_characteristics(
    days_back: int = Query(40, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """Все карточки товаров для дашборда (без токена)."""
    mapping = load_token_mapping()
    threshold = datetime.now() - timedelta(days=days_back)
    data = (
        db.query(ProductCharacteristic)
        .filter(ProductCharacteristic.synced_at >= threshold)
        .order_by(ProductCharacteristic.synced_at.desc())
        .limit(5000)
        .all()
    )
    return [
        {
            "id": item.id,
            "cabinet_id": item.cabinet_id,
            "nm_id": item.nm_id,
            "characteristics": item.characteristics,
            "synced_at": item.synced_at.isoformat() if item.synced_at else None,
            "seller_name": mapping.get(item.cabinet_id, item.cabinet_id[:8]),
        }
        for item in data
    ]


@app.get("/api/dashboard/stocks-summary")
def dashboard_stocks_summary(db: Session = Depends(get_db)):
    """Остатки сгруппированные по товару."""
    mapping = load_token_mapping()

    rows = (
        db.query(
            Stock.cabinet_id,
            Stock.nm_id,
            func.sum(Stock.quantity).label("quantity"),
            func.sum(Stock.in_way_to_client).label("in_way_to_client"),
            func.sum(Stock.in_way_from_client).label("in_way_from_client"),
        )
        .group_by(Stock.cabinet_id, Stock.nm_id)
        .order_by(func.sum(Stock.quantity).desc())
        .all()
    )

    result = []
    for r in rows:
        result.append({
            "cabinet_id": r.cabinet_id,
            "seller_name": mapping.get(r.cabinet_id, r.cabinet_id[:8]),
            "nm_id": r.nm_id,
            "quantity": r.quantity,
            "in_way_to_client": r.in_way_to_client,
            "in_way_from_client": r.in_way_from_client,
        })
    return result


@app.get("/api/dashboard/sales-report-summary")
def dashboard_sales_report_summary(db: Session = Depends(get_db)):
    """Сводка по отчёту реализации: комиссии WB, к перечислению."""
    mapping = load_token_mapping()

    rows = (
        db.query(
            SalesReport.cabinet_id,
            SalesReport.nm_id,
            SalesReport.sa_name,
            SalesReport.subject_name,
            func.sum(SalesReport.retail_amount).label("retail_amount"),
            func.sum(SalesReport.ppvz_for_pay).label("for_pay"),
            func.sum(SalesReport.ppvz_sales_commission).label("commission"),
            func.sum(SalesReport.delivery_rub).label("delivery"),
            func.sum(SalesReport.storage_fee).label("storage"),
            func.sum(SalesReport.penalty).label("penalty"),
            func.count(SalesReport.id).label("rows_count"),
        )
        .group_by(SalesReport.cabinet_id, SalesReport.nm_id, SalesReport.sa_name, SalesReport.subject_name)
        .order_by(func.sum(SalesReport.ppvz_for_pay).desc())
        .all()
    )

    result = []
    for r in rows:
        result.append({
            "cabinet_id": r.cabinet_id,
            "seller_name": mapping.get(r.cabinet_id, r.cabinet_id[:8]),
            "nm_id": r.nm_id,
            "sa_name": r.sa_name,
            "subject_name": r.subject_name,
            "retail_amount": round(float(r.retail_amount or 0), 2),
            "for_pay": round(float(r.for_pay or 0), 2),
            "commission": round(float(r.commission or 0), 2),
            "delivery": round(float(r.delivery or 0), 2),
            "storage": round(float(r.storage or 0), 2),
            "penalty": round(float(r.penalty or 0), 2),
        })
    return result

@app.get("/api/dashboard/orders-raw")
def dashboard_orders_raw(
    days_back: int = Query(40, ge=1, le=90),
    limit: int = Query(30000, le=30000),
    db: Session = Depends(get_db)
):
    """Сырые заказы для таблицы дашборда."""
    mapping = load_token_mapping()
    threshold = datetime.now() - timedelta(days=days_back)

    rows = (
        db.query(Order)
        .filter(Order.date >= threshold)
        .order_by(Order.date.desc())
        .limit(limit)
        .all()
    )

    result = []
    for item in rows:
        row = {k: v for k, v in item.__dict__.items() if not k.startswith("_")}
        row["seller_name"] = mapping.get(item.cabinet_id, item.cabinet_id[:8])
        for k, v in row.items():
            if hasattr(v, "isoformat"):
                row[k] = v.isoformat()
        result.append(row)

    return JSONResponse(content=result)


# =====================
# USER MANAGEMENT
# =====================

@app.post("/api/users", response_model=list[UserOut])
def api_create_user(body: UserCreate, db: Session = Depends(get_db)):
    """Создание нового пользователя."""
    existing = get_user_by_username(db, body.username)
    if existing:
        return JSONResponse(status_code=400, content={"error": "Username already exists"})
    
    import hashlib
    password_hash = hashlib.sha256(body.password.encode()).hexdigest() if body.password else None
    
    user = create_user(db, username=body.username, email=body.email, password_hash=password_hash)
    return [user]


@app.get("/api/users", response_model=list[UserOut])
def api_list_users(db: Session = Depends(get_db)):
    """Список всех пользователей."""
    return list_users(db)


@app.get("/api/users/{user_id}", response_model=list[UserOut])
def api_get_user(user_id: int, db: Session = Depends(get_db)):
    """Получение пользователя по ID."""
    user = get_user_by_id(db, user_id)
    if not user:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    return [user]


@app.put("/api/users/{user_id}", response_model=list[UserOut])
def api_update_user(user_id: int, body: UserUpdate, db: Session = Depends(get_db)):
    """Обновление пользователя."""
    update_data = body.model_dump(exclude_unset=True)
    user = update_user(db, user_id, **update_data)
    if not user:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    return [user]


@app.delete("/api/users/{user_id}")
def api_delete_user(user_id: int, db: Session = Depends(get_db)):
    """Удаление пользователя."""
    success = delete_user(db, user_id)
    if not success:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    return {"status": "deleted"}


# =====================
# API KEY MANAGEMENT
# =====================

@app.post("/api/users/{user_id}/api-keys")
def api_create_api_key(user_id: int, body: ApiKeyCreate, db: Session = Depends(get_db)):
    """Создание API-ключа для пользователя. Ключ отображается только один раз!"""
    import secrets
    import hashlib
    
    user = get_user_by_id(db, user_id)
    if not user:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    
    api_key = secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    
    db_key = create_api_key(db, user_id=user_id, key_hash=key_hash, name=body.name, expires_at=body.expires_at)
    
    return {
        "id": db_key.id,
        "name": db_key.name,
        "api_key": api_key,
        "expires_at": db_key.expires_at,
        "created_at": db_key.created_at,
    }


@app.get("/api/users/{user_id}/api-keys", response_model=list[ApiKeyOut])
def api_list_api_keys(user_id: int, db: Session = Depends(get_db)):
    """Список API-ключей пользователя."""
    return list_api_keys(db, user_id=user_id)


@app.delete("/api/api-keys/{key_id}")
def api_delete_api_key(key_id: int, db: Session = Depends(get_db)):
    """Удаление API-ключа."""
    success = delete_api_key(db, key_id)
    if not success:
        return JSONResponse(status_code=404, content={"error": "API key not found"})
    return {"status": "deleted"}


# =====================
# WB TOKEN MANAGEMENT
# =====================

@app.post("/api/users/{user_id}/wb-tokens", response_model=list[WbTokenOut])
def api_create_wb_token(user_id: int, body: WbTokenCreate, db: Session = Depends(get_db)):
    """Добавление токена Wildberries для пользователя."""
    user = get_user_by_id(db, user_id)
    if not user:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    
    # Проверяем уникальность токена
    import hashlib
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()[:32]
    existing = get_wb_token_by_hash(db, token_hash)
    if existing:
        return JSONResponse(status_code=400, content={"error": "Token already exists"})
    
    wb_token = create_wb_token(db, user_id=user_id, seller_name=body.seller_name, token=body.token)
    return [wb_token]


@app.get("/api/wb-tokens", response_model=list[WbTokenOut])
def api_list_wb_tokens(user_id: int | None = Query(None), active_only: bool = Query(False), db: Session = Depends(get_db)):
    """Список всех токенов Wildberries."""
    return list_wb_tokens(db, user_id=user_id, active_only=active_only)


@app.put("/api/wb-tokens/{token_id}", response_model=list[WbTokenOut])
def api_update_wb_token(token_id: int, body: WbTokenUpdate, db: Session = Depends(get_db)):
    """Обновление токена Wildberries."""
    update_data = body.model_dump(exclude_unset=True)
    wb_token = update_wb_token(db, token_id, **update_data)
    if not wb_token:
        return JSONResponse(status_code=404, content={"error": "Token not found"})
    return [wb_token]


@app.delete("/api/wb-tokens/{token_id}")
def api_delete_wb_token(token_id: int, db: Session = Depends(get_db)):
    """Удаление токена Wildberries."""
    success = delete_wb_token(db, token_id)
    if not success:
        return JSONResponse(status_code=404, content={"error": "Token not found"})
    return {"status": "deleted"}


@app.get("/api/dashboard/abc-xyz")
def dashboard_abc_xyz(
    cabinet_id: str | None = Query(None),
    days_back: int = Query(40, ge=7, le=90),
    db: Session = Depends(get_db),
):
    """ABC/XYZ анализ по товарам."""
    mapping = load_token_mapping()
    threshold = datetime.now() - timedelta(days=days_back)

    q = (
        db.query(
            Order.cabinet_id,
            Order.nm_id,
            Order.supplier_article,
            Order.subject,
            Order.brand,
            func.count(Order.id).label("orders_count"),
            func.sum(case((Order.is_cancel == False, Order.price_with_disc), else_=0)).label("revenue"),
        )
        .filter(Order.date >= threshold, Order.nm_id.isnot(None), Order.is_cancel == False)
        .group_by(Order.cabinet_id, Order.nm_id, Order.supplier_article, Order.subject, Order.brand)
    )
    if cabinet_id:
        q = q.filter(Order.cabinet_id == cabinet_id)

    rows = q.all()

    from sqlalchemy import cast, Date
    day_q = (
        db.query(
            Order.cabinet_id,
            Order.nm_id,
            cast(Order.date, Date).label("day"),
            func.count(Order.id).label("day_count"),
        )
        .filter(Order.date >= threshold, Order.nm_id.isnot(None), Order.is_cancel == False)
        .group_by(Order.cabinet_id, Order.nm_id, cast(Order.date, Date))
    )
    if cabinet_id:
        day_q = day_q.filter(Order.cabinet_id == cabinet_id)

    day_rows = day_q.all()

    daily = {}
    for dr in day_rows:
        key = (dr.cabinet_id, dr.nm_id)
        if key not in daily:
            daily[key] = []
        daily[key].append(dr.day_count)

    total_revenue = sum(float(r.revenue or 0) for r in rows)
    if total_revenue == 0:
        return {"items": [], "matrix": {}, "total_revenue": 0, "total_items": 0}

    items = []
    for r in rows:
        rev = float(r.revenue or 0)
        key = (r.cabinet_id, r.nm_id)
        day_counts = daily.get(key, [])
        avg_daily = sum(day_counts) / max(len(day_counts), 1)
        variance = sum((x - avg_daily) ** 2 for x in day_counts) / max(len(day_counts), 1) if day_counts else 0
        std_dev = variance ** 0.5
        cv = (std_dev / avg_daily * 100) if avg_daily > 0 else 999

        items.append({
            "cabinet_id": r.cabinet_id,
            "seller_name": mapping.get(r.cabinet_id, r.cabinet_id[:8]),
            "nm_id": r.nm_id,
            "supplier_article": r.supplier_article or "",
            "subject": r.subject or "",
            "brand": r.brand or "",
            "revenue": round(rev, 2),
            "orders_count": r.orders_count or 0,
            "days_with_orders": len(day_counts),
            "avg_daily": round(avg_daily, 2),
            "cv": round(cv, 1),
        })

    items.sort(key=lambda x: x["revenue"], reverse=True)
    cumulative = 0
    for item in items:
        cumulative += item["revenue"]
        pct = cumulative / total_revenue * 100
        if pct <= 80:
            item["abc"] = "A"
        elif pct <= 95:
            item["abc"] = "B"
        else:
            item["abc"] = "C"

    for item in items:
        cv = item["cv"]
        if cv <= 50:
            item["xyz"] = "X"
        elif cv <= 100:
            item["xyz"] = "Y"
        else:
            item["xyz"] = "Z"

    matrix = {}
    for abc in ["A", "B", "C"]:
        matrix[abc] = {"X": 0, "Y": 0, "Z": 0, "revenue": 0, "count": 0}
    for item in items:
        abc, xyz = item["abc"], item["xyz"]
        matrix[abc][xyz] += 1
        matrix[abc]["revenue"] += item["revenue"]
        matrix[abc]["count"] += 1

    return {
        "items": items,
        "matrix": matrix,
        "total_revenue": round(total_revenue, 2),
        "total_items": len(items),
    }


# =====================
# SHELF & FUNNEL ANALYTICS
# =====================

@app.get("/api/dashboard/shelf")
def dashboard_shelf(
    days_back: int = Query(30, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """Витрина продаж: просмотры, конверсия, добавления в корзину, заказы."""
    mapping = load_token_mapping()
    threshold = datetime.now() - timedelta(days=days_back)

    rows = (
        db.query(ShelfMetric)
        .filter(ShelfMetric.period_end >= threshold)
        .order_by(ShelfMetric.order_sum.desc())
        .limit(10000)
        .all()
    )

    result = []
    for r in rows:
        result.append({
            "cabinet_id": r.cabinet_id,
            "seller_name": mapping.get(r.cabinet_id, r.cabinet_id[:8]),
            "nm_id": r.nm_id,
            "vendor_code": r.vendor_code or "",
            "product_name": r.product_name or "",
            "subject_name": r.subject_name or "",
            "brand_name": r.brand_name or "",
            "product_rating": r.product_rating,
            "feedback_rating": r.feedback_rating,
            "open_count": r.open_count,
            "cart_count": r.cart_count,
            "order_count": r.order_count,
            "order_sum": r.order_sum,
            "buyout_count": r.buyout_count,
            "buyout_sum": r.buyout_sum,
            "cancel_count": r.cancel_count,
            "cancel_sum": r.cancel_sum,
            "avg_price": r.avg_price,
            "avg_orders_per_day": r.avg_orders_per_day,
            "conv_add_to_cart": r.conv_add_to_cart,
            "conv_cart_to_order": r.conv_cart_to_order,
            "conv_buyout": r.conv_buyout,
            "stocks_wb": r.stocks_wb,
            "stocks_mp": r.stocks_mp,
            "add_to_wishlist": r.add_to_wishlist,
            "period_start": r.period_start.isoformat() if r.period_start else None,
            "period_end": r.period_end.isoformat() if r.period_end else None,
        })
    return result


@app.get("/api/dashboard/stock-offices")
def dashboard_stock_offices(
    days_back: int = Query(30, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """Остатки по складам и регионам."""
    mapping = load_token_mapping()
    threshold = datetime.now() - timedelta(days=days_back)

    rows = (
        db.query(StockByOffice)
        .filter(StockByOffice.period_end >= threshold)
        .order_by(StockByOffice.stock_sum.desc())
        .limit(50000)
        .all()
    )

    result = []
    for r in rows:
        result.append({
            "cabinet_id": r.cabinet_id,
            "seller_name": mapping.get(r.cabinet_id, r.cabinet_id[:8]),
            "region_name": r.region_name,
            "office_id": r.office_id,
            "office_name": r.office_name,
            "stock_count": r.stock_count,
            "stock_sum": r.stock_sum,
            "sale_rate_days": r.sale_rate_days,
            "to_client_count": r.to_client_count,
            "from_client_count": r.from_client_count,
            "period_start": r.period_start.isoformat() if r.period_start else None,
            "period_end": r.period_end.isoformat() if r.period_end else None,
        })
    return result


@app.get("/api/dashboard/item-ratings")
def dashboard_item_ratings(
    days_back: int = Query(30, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """Оценки и отзывы товаров."""
    from sqlalchemy import func
    mapping = load_token_mapping()
    threshold = datetime.now() - timedelta(days=days_back)

    latest = (
        db.query(
            ItemRating.cabinet_id,
            ItemRating.nm_id,
            func.max(ItemRating.period_end).label("max_period_end")
        )
        .filter(ItemRating.period_end >= threshold)
        .group_by(ItemRating.cabinet_id, ItemRating.nm_id)
        .subquery()
    )

    rows = (
        db.query(ItemRating)
        .join(
            latest,
            (ItemRating.cabinet_id == latest.c.cabinet_id) &
            (ItemRating.nm_id == latest.c.nm_id) &
            (ItemRating.period_end == latest.c.max_period_end)
        )
        .order_by(ItemRating.feedback_count.desc())
        .limit(50000)
        .all()
    )

    result = []
    for r in rows:
        result.append({
            "cabinet_id": r.cabinet_id,
            "seller_name": mapping.get(r.cabinet_id, r.cabinet_id[:8]),
            "nm_id": r.nm_id,
            "vendor_code": r.vendor_code or "",
            "product_name": r.product_name or "",
            "subject_name": r.subject_name or "",
            "brand_name": r.brand_name or "",
            "seller_rating": r.seller_rating,
            "product_rating": r.product_rating,
            "feedback_rating": r.feedback_rating,
            "feedback_percentile": r.feedback_percentile,
            "feedback_count": r.feedback_count,
            "five_star": r.five_star,
            "four_star": r.four_star,
            "three_star": r.three_star,
            "two_star": r.two_star,
            "one_star": r.one_star,
            "disqualified": r.disqualified,
            "period_start": r.period_start.isoformat() if r.period_start else None,
            "period_end": r.period_end.isoformat() if r.period_end else None,
        })
    return result


@app.get("/api/dashboard/funnel")
def dashboard_funnel(
    days_back: int = Query(30, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """Воронка конверсии: сравнение периодов, динамика."""
    mapping = load_token_mapping()
    threshold = datetime.now() - timedelta(days=days_back)

    rows = (
        db.query(FunnelMetric)
        .filter(FunnelMetric.period_end >= threshold)
        .order_by(FunnelMetric.order_sum.desc())
        .limit(10000)
        .all()
    )

    result = []
    for r in rows:
        result.append({
            "cabinet_id": r.cabinet_id,
            "seller_name": mapping.get(r.cabinet_id, r.cabinet_id[:8]),
            "nm_id": r.nm_id,
            "vendor_code": r.vendor_code or "",
            "product_name": r.product_name or "",
            "subject_name": r.subject_name or "",
            "brand_name": r.brand_name or "",
            "open_count": r.open_count,
            "cart_count": r.cart_count,
            "order_count": r.order_count,
            "order_sum": r.order_sum,
            "buyout_count": r.buyout_count,
            "conv_add_to_cart": r.conv_add_to_cart,
            "conv_cart_to_order": r.conv_cart_to_order,
            "conv_buyout": r.conv_buyout,
            "past_open_count": r.past_open_count,
            "past_cart_count": r.past_cart_count,
            "past_order_count": r.past_order_count,
            "past_order_sum": r.past_order_sum,
            "past_buyout_count": r.past_buyout_count,
            "past_conv_buyout": r.past_conv_buyout,
            "dynamic_open": r.dynamic_open,
            "dynamic_cart": r.dynamic_cart,
            "dynamic_order": r.dynamic_order,
            "dynamic_buyout": r.dynamic_buyout,
            "period_start": r.period_start.isoformat() if r.period_start else None,
            "period_end": r.period_end.isoformat() if r.period_end else None,
        })
    return result


@app.get("/api/dashboard/ad-campaigns")
def dashboard_ad_campaigns(
    db: Session = Depends(get_db),
):
    """Рекламные кампании: список, статусы, типы."""
    mapping = load_token_mapping()

    rows = db.query(AdCampaign).order_by(AdCampaign.status.desc(), AdCampaign.advert_id.desc()).limit(50000).all()

    STATUS_MAP = {-1: "Удалена", 4: "Готова", 7: "Завершена", 8: "Отменена", 9: "Активна", 11: "На паузе"}
    TYPE_MAP = {6: "Аукцион", 8: "Единая ставка (устар.)", 9: "Единая/ручная"}

    result = []
    for r in rows:
        result.append({
            "cabinet_id": r.cabinet_id,
            "seller_name": mapping.get(r.cabinet_id, r.cabinet_id[:8]),
            "advert_id": r.advert_id,
            "name": r.name or "",
            "advert_type": r.advert_type,
            "type_name": TYPE_MAP.get(r.advert_type, f"Тип {r.advert_type}"),
            "status": r.status,
            "status_name": STATUS_MAP.get(r.status, f"Статус {r.status}"),
            "bid_type": r.bid_type or "",
            "payment_type": r.payment_type or "",
            "change_time": r.change_time.isoformat() if r.change_time else None,
        })
    return result


@app.get("/api/dashboard/ad-stats")
def dashboard_ad_stats(
    days_back: int = Query(30, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """Статистика рекламных кампаний: просмотры, клики, CTR, CPC, CR, заказы, затраты."""
    mapping = load_token_mapping()
    threshold = datetime.now().date() - timedelta(days=days_back)

    rows = (
        db.query(AdCampaignStats)
        .filter(AdCampaignStats.date >= datetime.combine(threshold, datetime.min.time()))
        .order_by(AdCampaignStats.spend.desc())
        .limit(100000)
        .all()
    )

    result = []
    for r in rows:
        result.append({
            "cabinet_id": r.cabinet_id,
            "seller_name": mapping.get(r.cabinet_id, r.cabinet_id[:8]),
            "advert_id": r.advert_id,
            "date": r.date.strftime("%Y-%m-%d") if r.date else None,
            "views": r.views,
            "clicks": r.clicks,
            "ctr": round(r.ctr, 2),
            "cpc": round(r.cpc, 2),
            "cr": round(r.cr, 2),
            "atbs": r.atbs,
            "orders": r.orders,
            "shks": r.shks,
            "canceled": r.canceled,
            "spend": round(r.spend, 2),
            "sum_price": round(r.sum_price, 2),
        })
    return result


@app.get("/api/dashboard/ad-expenses")
def dashboard_ad_expenses(
    days_back: int = Query(30, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """История затрат на рекламу."""
    mapping = load_token_mapping()
    threshold = datetime.now() - timedelta(days=days_back)

    rows = (
        db.query(AdExpense)
        .filter(AdExpense.upd_time >= threshold)
        .order_by(AdExpense.upd_time.desc())
        .limit(50000)
        .all()
    )

    result = []
    for r in rows:
        result.append({
            "cabinet_id": r.cabinet_id,
            "seller_name": mapping.get(r.cabinet_id, r.cabinet_id[:8]),
            "advert_id": r.advert_id,
            "camp_name": r.camp_name or "",
            "advert_type": r.advert_type,
            "advert_status": r.advert_status,
            "payment_type": r.payment_type or "",
            "upd_time": r.upd_time.isoformat() if r.upd_time else None,
            "upd_sum": r.upd_sum,
        })
    return result


# =====================
# STOCK FORECAST & UNIT ECONOMICS
# =====================

@app.get("/api/dashboard/stock-forecast")
def dashboard_stock_forecast(
    days_back: int = Query(30, ge=1, le=90),
    cabinet_id: str = Query(None),
    db: Session = Depends(get_db),
):
    """Прогноз остатков на 30 дней."""
    return get_stock_forecast(db, cabinet_id, days_back)


@app.get("/api/dashboard/unit-economics")
def dashboard_unit_economics(
    days_back: int = Query(30, ge=1, le=90),
    cabinet_id: str = Query(None),
    db: Session = Depends(get_db),
):
    """Юнит-экономика по каждому SKU."""
    return get_unit_economics(db, cabinet_id, days_back)


@app.get("/api/dashboard/ad-search-clusters")
def dashboard_ad_search_clusters(
    cabinet_id: str = Query(None),
    db: Session = Depends(get_db),
):
    """Поисковые кластеры рекламных кампаний."""
    return get_ad_search_clusters(db, cabinet_id)