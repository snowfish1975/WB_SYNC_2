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
)
from app.models import User, ApiKey, WbToken
from app.models import ProductCharacteristic, Stock, Order, Price, SalesReport, Sale
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