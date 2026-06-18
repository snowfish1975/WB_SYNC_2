import os
import asyncio
import hashlib
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Query, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
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
    RnpSettingsUpdate, RnpCostIn, RnpFixedExpenseIn, RnpVariableExpenseIn, RnpLoanPaymentIn, RnpPlanIn,
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
    get_rnp_settings, upsert_rnp_settings,
    get_rnp_costs, upsert_rnp_costs_bulk, delete_rnp_cost,
    get_rnp_fixed_expenses, upsert_rnp_fixed_expenses_bulk, delete_rnp_fixed_expense,
    get_rnp_variable_expenses, upsert_rnp_variable_expenses_bulk, delete_rnp_variable_expense,
    get_rnp_loan_payments, upsert_rnp_loan_payments_bulk, delete_rnp_loan_payment,
    get_rnp_plans, upsert_rnp_plans_bulk, delete_rnp_plan,
)
from app.models import User, ApiKey, WbToken, UserCabinetAccess
from app.models import ProductCharacteristic, Stock, Order, Price, SalesReport, Sale
from app.models import ShelfMetric, FunnelMetric, StockByOffice, ItemRating, AdCampaign, AdCampaignStats, AdExpense, AdSearchCluster
from app.scheduler import run_sync_all, run_sales_report_sync, run_search_clusters_sync, run_sales_report_backfill
from app.auth import (
    hash_password, verify_password, check_rate_limit, record_failed_login, clear_rate_limit,
    get_current_user, login_required, admin_required, get_user_cabinet_ids,
    SESSION_KEY_USER_ID, SESSION_KEY_IS_ADMIN,
)

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

from starlette.middleware.sessions import SessionMiddleware
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", "wb-sync-secret-key-change-in-production"), session_cookie="wb_session", max_age=86400 * 7, same_site="strict", https_only=False)

app.mount("/static", StaticFiles(directory="static"), name="static")


def _get_user_cabinets(request: Request, db: Session) -> list[str] | None:
    """Get allowed cabinet_ids for current user. None = all, [] = none."""
    uid = request.session.get(SESSION_KEY_USER_ID)
    if not uid:
        return []
    user = db.query(User).filter(User.id == uid).first()
    if not user or not user.is_active:
        return []
    return get_user_cabinet_ids(user, db)


def _filter_by_cabinets(query, allowed: list[str] | None, cabinet_col):
    """Apply cabinet filter to a SQLAlchemy query. allowed=None means no filter."""
    if allowed is not None:
        query = query.filter(cabinet_col.in_(allowed))
    return query


# =====================
# AUTH: LOGIN / LOGOUT
# =====================

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if request.session.get(SESSION_KEY_USER_ID):
        return RedirectResponse("/dashboard", status_code=302)
    return FileResponse("static/login.html")


@app.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    client_ip = request.client.host if request.client else "unknown"

    if not check_rate_limit(client_ip):
        return HTMLResponse(
            '<!DOCTYPE html><html><head><meta charset="utf-8"><title>Ошибка</title>'
            '<link rel="stylesheet" href="/static/themes.css?v=3"><link rel="stylesheet" href="/static/base.css?v=3">'
            '</head><body data-theme="dark"><div style="max-width:400px;margin:120px auto;text-align:center;">'
            '<h2 style="color:var(--red)">Слишком много попыток</h2>'
            '<p style="color:var(--text2)">Подождите 5 минут и попробуйте снова.</p>'
            '<a href="/login" style="color:var(--accent)">← Назад</a></div></body></html>',
            status_code=429,
        )

    user = get_user_by_username(db, username)
    if not user or not user.password_hash or not verify_password(password, user.password_hash):
        record_failed_login(client_ip)
        return HTMLResponse(
            '<!DOCTYPE html><html><head><meta charset="utf-8"><title>Ошибка</title>'
            '<link rel="stylesheet" href="/static/themes.css?v=3"><link rel="stylesheet" href="/static/base.css?v=3">'
            '</head><body data-theme="dark"><div style="max-width:400px;margin:120px auto;text-align:center;">'
            '<h2 style="color:var(--red)">Неверный логин или пароль</h2>'
            '<a href="/login" style="color:var(--accent)">← Попробовать снова</a></div></body></html>',
            status_code=401,
        )

    if not user.is_active:
        return HTMLResponse(
            '<!DOCTYPE html><html><head><meta charset="utf-8"><title>Ошибка</title>'
            '<link rel="stylesheet" href="/static/themes.css?v=3"><link rel="stylesheet" href="/static/base.css?v=3">'
            '</head><body data-theme="dark"><div style="max-width:400px;margin:120px auto;text-align:center;">'
            '<h2 style="color:var(--red)">Аккаунт деактивирован</h2>'
            '<p style="color:var(--text2)">Обратитесь к администратору.</p>'
            '<a href="/login" style="color:var(--accent)">← Назад</a></div></body></html>',
            status_code=403,
        )

    clear_rate_limit(client_ip)
    request.session[SESSION_KEY_USER_ID] = user.id
    request.session[SESSION_KEY_IS_ADMIN] = user.is_admin
    return RedirectResponse("/dashboard", status_code=302)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


@app.get("/api/auth/me")
def auth_me(request: Request, db: Session = Depends(get_db)):
    uid = request.session.get(SESSION_KEY_USER_ID)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})
    user = db.query(User).filter(User.id == uid).first()
    if not user or not user.is_active:
        request.session.clear()
        return JSONResponse(status_code=401, content={"error": "User not found"})
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "company": user.company,
        "phone": user.phone,
        "email": user.email,
        "is_admin": user.is_admin,
    }


@app.get("/")
def root(request: Request):
    uid = request.session.get(SESSION_KEY_USER_ID)
    if uid:
        return RedirectResponse("/dashboard", status_code=302)
    return RedirectResponse("/login", status_code=302)


@app.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db)):
    uid = request.session.get(SESSION_KEY_USER_ID)
    if not uid:
        return RedirectResponse("/login", status_code=302)
    user = db.query(User).filter(User.id == uid).first()
    if not user or not user.is_active:
        request.session.clear()
        return RedirectResponse("/login", status_code=302)
    return FileResponse("static/dashboard.html")


# =====================
# USER MANAGEMENT (Admin)
# =====================

@app.get("/api/admin/users")
def admin_list_users(request: Request, db: Session = Depends(get_db)):
    uid = request.session.get(SESSION_KEY_USER_ID)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})
    user = db.query(User).filter(User.id == uid).first()
    if not user or not user.is_admin:
        return JSONResponse(status_code=403, content={"error": "Admin access required"})

    users = db.query(User).all()
    mapping = load_token_mapping()
    result = []
    for u in users:
        cab_access = db.query(UserCabinetAccess).filter(UserCabinetAccess.user_id == u.id).all()
        if u.is_admin:
            cabinets = "all"
        elif not cab_access:
            cabinets = "none"
        elif any(r.access_all for r in cab_access):
            cabinets = "all"
        else:
            cabinets = [mapping.get(r.cabinet_id, r.cabinet_id[:8]) for r in cab_access]
        result.append({
            "id": u.id,
            "username": u.username,
            "full_name": u.full_name or "",
            "company": u.company or "",
            "phone": u.phone or "",
            "email": u.email or "",
            "is_active": u.is_active,
            "is_admin": u.is_admin,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "cabinets": cabinets,
        })
    return result


@app.post("/api/admin/users")
def admin_create_user(
    request: Request,
    username: str = Form(...),
    full_name: str = Form(""),
    company: str = Form(""),
    phone: str = Form(""),
    email: str = Form(""),
    password: str = Form(...),
    is_admin: bool = Form(False),
    db: Session = Depends(get_db),
):
    uid = request.session.get(SESSION_KEY_USER_ID)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})
    admin = db.query(User).filter(User.id == uid).first()
    if not admin or not admin.is_admin:
        return JSONResponse(status_code=403, content={"error": "Admin access required"})

    existing = get_user_by_username(db, username)
    if existing:
        return JSONResponse(status_code=400, content={"error": "Username already exists"})

    user = create_user(db, username=username, email=email or None, password_hash=hash_password(password))
    user.full_name = full_name
    user.company = company
    user.phone = phone
    user.is_admin = is_admin
    db.commit()
    return JSONResponse(content={"id": user.id, "username": user.username, "status": "created"})


@app.put("/api/admin/users/{user_id}")
def admin_update_user(
    user_id: int,
    request: Request,
    full_name: str = Form(None),
    company: str = Form(None),
    phone: str = Form(None),
    email: str = Form(None),
    is_active: bool = Form(None),
    is_admin: bool = Form(None),
    password: str = Form(None),
    db: Session = Depends(get_db),
):
    uid = request.session.get(SESSION_KEY_USER_ID)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})
    admin = db.query(User).filter(User.id == uid).first()
    if not admin or not admin.is_admin:
        return JSONResponse(status_code=403, content={"error": "Admin access required"})

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return JSONResponse(status_code=404, content={"error": "User not found"})

    if full_name is not None:
        user.full_name = full_name
    if company is not None:
        user.company = company
    if phone is not None:
        user.phone = phone
    if email is not None:
        user.email = email
    if is_active is not None:
        user.is_active = is_active
    if is_admin is not None:
        user.is_admin = is_admin
    if password:
        user.password_hash = hash_password(password)
    db.commit()
    return JSONResponse(content={"status": "updated"})


@app.delete("/api/admin/users/{user_id}")
def admin_delete_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    uid = request.session.get(SESSION_KEY_USER_ID)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})
    admin = db.query(User).filter(User.id == uid).first()
    if not admin or not admin.is_admin:
        return JSONResponse(status_code=403, content={"error": "Admin access required"})
    if user_id == uid:
        return JSONResponse(status_code=400, content={"error": "Cannot delete yourself"})

    success = delete_user(db, user_id)
    if not success:
        return JSONResponse(status_code=404, content={"error": "User not found"})
    return JSONResponse(content={"status": "deleted"})


@app.post("/api/admin/users/{user_id}/cabinets")
def admin_set_user_cabinets(
    user_id: int,
    request: Request,
    cabinet_ids: str = Form(""),
    access_all: bool = Form(False),
    db: Session = Depends(get_db),
):
    uid = request.session.get(SESSION_KEY_USER_ID)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})
    admin = db.query(User).filter(User.id == uid).first()
    if not admin or not admin.is_admin:
        return JSONResponse(status_code=403, content={"error": "Admin access required"})

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return JSONResponse(status_code=404, content={"error": "User not found"})

    db.query(UserCabinetAccess).filter(UserCabinetAccess.user_id == user_id).delete()

    if access_all:
        db.add(UserCabinetAccess(user_id=user_id, cabinet_id="*", access_all=True))
    elif cabinet_ids:
        for cid in cabinet_ids.split(","):
            cid = cid.strip()
            if cid:
                db.add(UserCabinetAccess(user_id=user_id, cabinet_id=cid))
    db.commit()
    return JSONResponse(content={"status": "updated"})


# =====================
# USER PROFILE (Self-service)
# =====================

@app.put("/api/profile")
def update_profile(
    request: Request,
    full_name: str = Form(None),
    company: str = Form(None),
    phone: str = Form(None),
    db: Session = Depends(get_db),
):
    uid = request.session.get(SESSION_KEY_USER_ID)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})
    user = db.query(User).filter(User.id == uid).first()
    if not user:
        return JSONResponse(status_code=404, content={"error": "User not found"})

    if full_name is not None:
        user.full_name = full_name
    if company is not None:
        user.company = company
    if phone is not None:
        user.phone = phone
    db.commit()
    return JSONResponse(content={"status": "updated"})


@app.put("/api/profile/password")
def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    db: Session = Depends(get_db),
):
    uid = request.session.get(SESSION_KEY_USER_ID)
    if not uid:
        return JSONResponse(status_code=401, content={"error": "Not authenticated"})
    user = db.query(User).filter(User.id == uid).first()
    if not user:
        return JSONResponse(status_code=404, content={"error": "User not found"})

    if not user.password_hash or not verify_password(current_password, user.password_hash):
        return JSONResponse(status_code=400, content={"error": "Current password is incorrect"})

    user.password_hash = hash_password(new_password)
    db.commit()
    return JSONResponse(content={"status": "updated"})


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


@app.post("/api/shelf-metrics")
def list_shelf_metrics(
    body: TokenRequest,
    nm_id: int | None = Query(None, description="Фильтр по артикулу WB"),
    days_back: int = Query(30, ge=1, le=90),
    limit: int = Query(1000, le=50000),
    db: Session = Depends(get_db),
):
    """Сырые данные витрины продаж."""
    mapping = load_token_mapping()
    threshold = datetime.now() - timedelta(days=days_back)
    q = db.query(ShelfMetric).filter(ShelfMetric.period_end >= threshold)
    if nm_id:
        q = q.filter(ShelfMetric.nm_id == nm_id)
    rows = q.order_by(ShelfMetric.order_sum.desc()).limit(limit).all()
    return [{**{k: v for k, v in r.__dict__.items() if not k.startswith("_")}, "seller_name": mapping.get(r.cabinet_id, r.cabinet_id[:8])} for r in rows]


@app.post("/api/funnel-metrics")
def list_funnel_metrics(
    body: TokenRequest,
    nm_id: int | None = Query(None, description="Фильтр по артикулу WB"),
    days_back: int = Query(30, ge=1, le=90),
    limit: int = Query(1000, le=50000),
    db: Session = Depends(get_db),
):
    """Сырые данные воронки конверсии."""
    mapping = load_token_mapping()
    threshold = datetime.now() - timedelta(days=days_back)
    q = db.query(FunnelMetric).filter(FunnelMetric.period_end >= threshold)
    if nm_id:
        q = q.filter(FunnelMetric.nm_id == nm_id)
    rows = q.order_by(FunnelMetric.order_sum.desc()).limit(limit).all()
    return [{**{k: v for k, v in r.__dict__.items() if not k.startswith("_")}, "seller_name": mapping.get(r.cabinet_id, r.cabinet_id[:8])} for r in rows]


@app.post("/api/stock-offices")
def list_stock_offices(
    body: TokenRequest,
    days_back: int = Query(30, ge=1, le=90),
    limit: int = Query(1000, le=50000),
    db: Session = Depends(get_db),
):
    """Сырые данные остатков по офисам."""
    mapping = load_token_mapping()
    threshold = datetime.now() - timedelta(days=days_back)
    rows = db.query(StockByOffice).filter(StockByOffice.period_end >= threshold).order_by(StockByOffice.stock_sum.desc()).limit(limit).all()
    return [{**{k: v for k, v in r.__dict__.items() if not k.startswith("_")}, "seller_name": mapping.get(r.cabinet_id, r.cabinet_id[:8])} for r in rows]


@app.post("/api/item-ratings")
def list_item_ratings(
    body: TokenRequest,
    nm_id: int | None = Query(None, description="Фильтр по артикулу WB"),
    days_back: int = Query(30, ge=1, le=90),
    limit: int = Query(1000, le=50000),
    db: Session = Depends(get_db),
):
    """Сырые данные рейтингов товаров."""
    from sqlalchemy import func
    mapping = load_token_mapping()
    threshold = datetime.now() - timedelta(days=days_back)
    latest = db.query(ItemRating.cabinet_id, ItemRating.nm_id, func.max(ItemRating.period_end).label("mp")).filter(ItemRating.period_end >= threshold).group_by(ItemRating.cabinet_id, ItemRating.nm_id).subquery()
    q = db.query(ItemRating).join(latest, (ItemRating.cabinet_id == latest.c.cabinet_id) & (ItemRating.nm_id == latest.c.nm_id) & (ItemRating.period_end == latest.c.mp))
    if nm_id:
        q = q.filter(ItemRating.nm_id == nm_id)
    rows = q.order_by(ItemRating.feedback_count.desc()).limit(limit).all()
    return [{**{k: v for k, v in r.__dict__.items() if not k.startswith("_")}, "seller_name": mapping.get(r.cabinet_id, r.cabinet_id[:8])} for r in rows]


@app.post("/api/ad-campaigns")
def list_ad_campaigns(
    body: TokenRequest,
    limit: int = Query(1000, le=50000),
    db: Session = Depends(get_db),
):
    """Сырые данные рекламных кампаний."""
    mapping = load_token_mapping()
    rows = db.query(AdCampaign).order_by(AdCampaign.status.desc()).limit(limit).all()
    return [{**{k: v for k, v in r.__dict__.items() if not k.startswith("_")}, "seller_name": mapping.get(r.cabinet_id, r.cabinet_id[:8])} for r in rows]


@app.post("/api/ad-stats")
def list_ad_stats(
    body: TokenRequest,
    days_back: int = Query(30, ge=1, le=90),
    limit: int = Query(1000, le=50000),
    db: Session = Depends(get_db),
):
    """Сырые данные статистики рекламы."""
    mapping = load_token_mapping()
    threshold = datetime.now() - timedelta(days=days_back)
    rows = db.query(AdCampaignStats).filter(AdCampaignStats.date >= threshold).order_by(AdCampaignStats.spend.desc()).limit(limit).all()
    return [{**{k: v for k, v in r.__dict__.items() if not k.startswith("_")}, "seller_name": mapping.get(r.cabinet_id, r.cabinet_id[:8])} for r in rows]


@app.post("/api/ad-expenses")
def list_ad_expenses(
    body: TokenRequest,
    days_back: int = Query(30, ge=1, le=90),
    limit: int = Query(1000, le=50000),
    db: Session = Depends(get_db),
):
    """Сырые данные затрат на рекламу."""
    mapping = load_token_mapping()
    threshold = datetime.now() - timedelta(days=days_back)
    rows = db.query(AdExpense).filter(AdExpense.upd_time >= threshold).order_by(AdExpense.upd_time.desc()).limit(limit).all()
    return [{**{k: v for k, v in r.__dict__.items() if not k.startswith("_")}, "seller_name": mapping.get(r.cabinet_id, r.cabinet_id[:8])} for r in rows]


@app.post("/api/ad-search-clusters")
def list_ad_search_clusters(
    body: TokenRequest,
    limit: int = Query(1000, le=50000),
    db: Session = Depends(get_db),
):
    """Сырые данные поисковых кластеров."""
    mapping = load_token_mapping()
    rows = db.query(AdSearchCluster).order_by(AdSearchCluster.spend.desc()).limit(limit).all()
    return [{**{k: v for k, v in r.__dict__.items() if not k.startswith("_")}, "seller_name": mapping.get(r.cabinet_id, r.cabinet_id[:8])} for r in rows]


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


@app.post("/api/sync/trigger-search-clusters")
def trigger_search_clusters_sync():
    """Принудительный запуск синхронизации поисковых кластеров."""
    import threading
    threading.Thread(target=run_search_clusters_sync, daemon=True).start()
    return {"status": "started"}


@app.post("/api/sync/trigger-sales-report-backfill")
def trigger_sales_report_backfill(days: int = Query(40, ge=1, le=90)):
    """Загрузка отчёта реализации за последние N дней (backfill исторических данных)."""
    import threading
    threading.Thread(target=run_sales_report_backfill, args=(days,), daemon=True).start()
    return {"status": "started", "days": days}


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/dashboard/cabinets")
def dashboard_cabinets(request: Request, db: Session = Depends(get_db)):
    """Список доступных кабинетов для текущего пользователя."""
    mapping = load_token_mapping()
    allowed = _get_user_cabinets(request, db)
    if allowed is None:
        return [{"cabinet_id": cid, "seller_name": name} for cid, name in mapping.items()]
    return [{"cabinet_id": cid, "seller_name": name} for cid, name in mapping.items() if cid in allowed]


@app.get("/api/dashboard/summary")
def dashboard_summary(request: Request, days_back: int = Query(40, ge=1, le=90), db: Session = Depends(get_db)):
    """Сводные цифры: заказы, выручка, возвраты, отмены."""
    allowed = _get_user_cabinets(request, db)
    if allowed is not None and len(allowed) == 0:
        return []
    mapping = load_token_mapping()
    threshold = datetime.now() - timedelta(days=days_back)

    q = db.query(
            Order.cabinet_id,
            func.count(Order.id).label("total_orders"),
            func.sum(case((Order.is_cancel == False, Order.price_with_disc), else_=0)).label("revenue"),
            func.sum(case((Order.is_cancel == True, 1), else_=0)).label("cancels"),
        ).filter(Order.date >= threshold)
    q = _filter_by_cabinets(q, allowed, Order.cabinet_id)
    rows = q.group_by(Order.cabinet_id).all()

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
def dashboard_sales_chart(request: Request, days_back: int = Query(40, ge=1, le=90), db: Session = Depends(get_db)):
    """Продажи по дням для графика."""
    allowed = _get_user_cabinets(request, db)
    if allowed is not None and len(allowed) == 0:
        return []
    mapping = load_token_mapping()
    threshold = datetime.now() - timedelta(days=days_back)

    q = db.query(
            Order.cabinet_id,
            func.date(Order.date).label("day"),
            func.count(Order.id).label("orders_count"),
            func.sum(case((Order.is_cancel == False, Order.price_with_disc), else_=0)).label("revenue"),
        ).filter(Order.date >= threshold, Order.is_cancel == False)
    q = _filter_by_cabinets(q, allowed, Order.cabinet_id)
    rows = q.group_by(Order.cabinet_id, func.date(Order.date)).order_by(func.date(Order.date)).all()

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
def dashboard_top_products(request: Request, days_back: int = Query(40, ge=1, le=90), limit: int = Query(20, le=100), db: Session = Depends(get_db)):
    """Топ товаров по выручке."""
    allowed = _get_user_cabinets(request, db)
    if allowed is not None and len(allowed) == 0:
        return []
    mapping = load_token_mapping()
    threshold = datetime.now() - timedelta(days=days_back)

    q = db.query(
            Order.cabinet_id,
            Order.nm_id,
            Order.supplier_article,
            Order.subject,
            Order.brand,
            func.count(Order.id).label("orders_count"),
            func.sum(Order.price_with_disc).label("revenue"),
        ).filter(Order.date >= threshold, Order.is_cancel == False, Order.nm_id.isnot(None))
    q = _filter_by_cabinets(q, allowed, Order.cabinet_id)
    rows = q.group_by(Order.cabinet_id, Order.nm_id, Order.supplier_article, Order.subject, Order.brand).order_by(func.sum(Order.price_with_disc).desc()).all()

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
    request: Request,
    days_back: int = Query(40, ge=1, le=365),
    db: Session = Depends(get_db),
):
    """Все карточки товаров для дашборда (без токена)."""
    allowed = _get_user_cabinets(request, db)
    if allowed is not None and len(allowed) == 0:
        return []
    mapping = load_token_mapping()
    threshold = datetime.now() - timedelta(days=days_back)
    q = db.query(ProductCharacteristic).filter(ProductCharacteristic.synced_at >= threshold)
    q = _filter_by_cabinets(q, allowed, ProductCharacteristic.cabinet_id)
    data = q.order_by(ProductCharacteristic.synced_at.desc()).limit(5000).all()
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
def dashboard_stocks_summary(request: Request, db: Session = Depends(get_db)):
    """Остатки сгруппированные по товару."""
    allowed = _get_user_cabinets(request, db)
    if allowed is not None and len(allowed) == 0:
        return []
    mapping = load_token_mapping()

    q = db.query(
            Stock.cabinet_id,
            Stock.nm_id,
            func.sum(Stock.quantity).label("quantity"),
            func.sum(Stock.in_way_to_client).label("in_way_to_client"),
            func.sum(Stock.in_way_from_client).label("in_way_from_client"),
        )
    q = _filter_by_cabinets(q, allowed, Stock.cabinet_id)
    rows = q.group_by(Stock.cabinet_id, Stock.nm_id).order_by(func.sum(Stock.quantity).desc()).all()

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
def dashboard_sales_report_summary(request: Request, db: Session = Depends(get_db)):
    """Сводка по отчёту реализации: комиссии WB, к перечислению."""
    allowed = _get_user_cabinets(request, db)
    if allowed is not None and len(allowed) == 0:
        return []
    mapping = load_token_mapping()

    q = db.query(
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
    q = _filter_by_cabinets(q, allowed, SalesReport.cabinet_id)
    rows = q.group_by(SalesReport.cabinet_id, SalesReport.nm_id, SalesReport.sa_name, SalesReport.subject_name).order_by(func.sum(SalesReport.ppvz_for_pay).desc()).all()

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
    request: Request,
    days_back: int = Query(40, ge=1, le=90),
    limit: int = Query(30000, le=30000),
    db: Session = Depends(get_db)
):
    """Сырые заказы для таблицы дашборда."""
    allowed = _get_user_cabinets(request, db)
    if allowed is not None and len(allowed) == 0:
        return []
    mapping = load_token_mapping()
    threshold = datetime.now() - timedelta(days=days_back)

    q = db.query(Order).filter(Order.date >= threshold)
    q = _filter_by_cabinets(q, allowed, Order.cabinet_id)
    rows = q.order_by(Order.date.desc()).limit(limit).all()

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
    request: Request,
    cabinet_id: str | None = Query(None),
    days_back: int = Query(40, ge=7, le=90),
    db: Session = Depends(get_db),
):
    """ABC/XYZ анализ по товарам."""
    allowed = _get_user_cabinets(request, db)
    if allowed is not None and len(allowed) == 0:
        return {"items": [], "matrix": {}, "total_revenue": 0, "total_items": 0}
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
    q = _filter_by_cabinets(q, allowed, Order.cabinet_id)

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
    day_q = _filter_by_cabinets(day_q, allowed, Order.cabinet_id)

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
    request: Request,
    days_back: int = Query(30, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """Витрина продаж: просмотры, конверсия, добавления в корзину, заказы."""
    allowed = _get_user_cabinets(request, db)
    if allowed is not None and len(allowed) == 0:
        return []
    mapping = load_token_mapping()
    threshold = datetime.now() - timedelta(days=days_back)

    q = db.query(ShelfMetric).filter(ShelfMetric.period_end >= threshold)
    q = _filter_by_cabinets(q, allowed, ShelfMetric.cabinet_id)
    rows = q.order_by(ShelfMetric.order_sum.desc()).limit(10000).all()

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
    request: Request,
    days_back: int = Query(30, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """Остатки по складам и регионам."""
    allowed = _get_user_cabinets(request, db)
    if allowed is not None and len(allowed) == 0:
        return []
    mapping = load_token_mapping()
    threshold = datetime.now() - timedelta(days=days_back)

    q = db.query(StockByOffice).filter(StockByOffice.period_end >= threshold)
    q = _filter_by_cabinets(q, allowed, StockByOffice.cabinet_id)
    rows = q.order_by(StockByOffice.stock_sum.desc()).limit(50000).all()

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
    request: Request,
    days_back: int = Query(30, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """Оценки и отзывы товаров."""
    from sqlalchemy import func
    allowed = _get_user_cabinets(request, db)
    if allowed is not None and len(allowed) == 0:
        return []
    mapping = load_token_mapping()
    threshold = datetime.now() - timedelta(days=days_back)

    latest_q = db.query(
            ItemRating.cabinet_id,
            ItemRating.nm_id,
            func.max(ItemRating.period_end).label("max_period_end")
        ).filter(ItemRating.period_end >= threshold)
    latest_q = _filter_by_cabinets(latest_q, allowed, ItemRating.cabinet_id)
    latest = latest_q.group_by(ItemRating.cabinet_id, ItemRating.nm_id).subquery()

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
    request: Request,
    days_back: int = Query(30, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """Воронка конверсии: сравнение периодов, динамика."""
    allowed = _get_user_cabinets(request, db)
    if allowed is not None and len(allowed) == 0:
        return []
    mapping = load_token_mapping()
    threshold = datetime.now() - timedelta(days=days_back)

    q = db.query(FunnelMetric).filter(FunnelMetric.period_end >= threshold)
    q = _filter_by_cabinets(q, allowed, FunnelMetric.cabinet_id)
    rows = q.order_by(FunnelMetric.order_sum.desc()).limit(10000).all()

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
    request: Request,
    db: Session = Depends(get_db),
):
    """Рекламные кампании: список, статусы, типы."""
    allowed = _get_user_cabinets(request, db)
    if allowed is not None and len(allowed) == 0:
        return []
    mapping = load_token_mapping()

    q = db.query(AdCampaign)
    q = _filter_by_cabinets(q, allowed, AdCampaign.cabinet_id)
    rows = q.order_by(AdCampaign.status.desc(), AdCampaign.advert_id.desc()).limit(50000).all()

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
    request: Request,
    days_back: int = Query(30, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """Статистика рекламных кампаний: просмотры, клики, CTR, CPC, CR, заказы, затраты."""
    allowed = _get_user_cabinets(request, db)
    if allowed is not None and len(allowed) == 0:
        return []
    mapping = load_token_mapping()
    threshold = datetime.now().date() - timedelta(days=days_back)

    q = db.query(AdCampaignStats).filter(AdCampaignStats.date >= datetime.combine(threshold, datetime.min.time()))
    q = _filter_by_cabinets(q, allowed, AdCampaignStats.cabinet_id)
    rows = q.order_by(AdCampaignStats.spend.desc()).limit(100000).all()

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
    request: Request,
    days_back: int = Query(30, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """История затрат на рекламу."""
    allowed = _get_user_cabinets(request, db)
    if allowed is not None and len(allowed) == 0:
        return []
    mapping = load_token_mapping()
    threshold = datetime.now() - timedelta(days=days_back)

    q = db.query(AdExpense).filter(AdExpense.upd_time >= threshold)
    q = _filter_by_cabinets(q, allowed, AdExpense.cabinet_id)
    rows = q.order_by(AdExpense.upd_time.desc()).limit(50000).all()

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
    request: Request,
    days_back: int = Query(30, ge=1, le=90),
    cabinet_id: str = Query(None),
    db: Session = Depends(get_db),
):
    """Прогноз остатков на 30 дней."""
    allowed = _get_user_cabinets(request, db)
    if allowed is not None and len(allowed) == 0:
        return {"items": [], "total_skus": 0}
    if allowed is not None and cabinet_id and cabinet_id not in allowed:
        return {"items": [], "total_skus": 0}
    return get_stock_forecast(db, cabinet_id, days_back)


@app.get("/api/dashboard/unit-economics")
def dashboard_unit_economics(
    request: Request,
    days_back: int = Query(30, ge=1, le=90),
    cabinet_id: str = Query(None),
    db: Session = Depends(get_db),
):
    """Юнит-экономика по каждому SKU."""
    allowed = _get_user_cabinets(request, db)
    if allowed is not None and len(allowed) == 0:
        return {"items": [], "total_skus": 0}
    if allowed is not None and cabinet_id and cabinet_id not in allowed:
        return {"items": [], "total_skus": 0}
    return get_unit_economics(db, cabinet_id, days_back)


@app.get("/api/dashboard/ad-search-clusters")
def dashboard_ad_search_clusters(
    request: Request,
    cabinet_id: str = Query(None),
    db: Session = Depends(get_db),
):
    """Поисковые кластеры рекламных кампаний."""
    allowed = _get_user_cabinets(request, db)
    if allowed is not None and len(allowed) == 0:
        return []
    mapping = load_token_mapping()
    data = get_ad_search_clusters(db, cabinet_id)
    result = []
    for r in data:
        if allowed is not None and r.cabinet_id not in allowed:
            continue
        result.append({
            "cabinet_id": r.cabinet_id,
            "seller_name": mapping.get(r.cabinet_id, r.cabinet_id[:8]),
            "advert_id": r.advert_id,
            "nm_id": r.nm_id,
            "keyword": r.keyword,
            "views": r.views,
            "clicks": r.clicks,
            "ctr": r.ctr,
            "cpc": r.cpc,
            "cpm": r.cpm,
            "avg_pos": r.avg_pos,
            "atbs": r.atbs,
            "shks": r.shks,
            "sum_price": r.sum_price,
            "orders": r.orders,
            "spend": r.spend,
        })
    return result


# =====================
# Логистика — Анализ потоков склады → регионы
# =====================


@app.get("/api/dashboard/logistics")
def dashboard_logistics(
    request: Request,
    cabinet_id: str = Query(""),
    days_back: int = Query(30, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """Анализ логистических потоков: склады → регионы доставки."""
    allowed = _get_user_cabinets(request, db)
    threshold = datetime.now() - timedelta(days=days_back)

    q = db.query(Order).filter(
        Order.date >= threshold,
        Order.is_cancel == False,
    )
    if allowed is not None:
        q = q.filter(Order.cabinet_id.in_(allowed))
    if cabinet_id:
        q = q.filter(Order.cabinet_id == cabinet_id)

    from sqlalchemy import func as sa_func

    pairs_q = db.query(
        Order.warehouse_name,
        Order.region_name,
        sa_func.count().label("cnt"),
        sa_func.sum(Order.price_with_disc).label("total_sum"),
    ).filter(
        Order.date >= threshold,
        Order.is_cancel == False,
    )
    if allowed is not None:
        pairs_q = pairs_q.filter(Order.cabinet_id.in_(allowed))
    if cabinet_id:
        pairs_q = pairs_q.filter(Order.cabinet_id == cabinet_id)

    pairs_data = pairs_q.group_by(Order.warehouse_name, Order.region_name).all()

    wh_totals = {}
    reg_totals = {}
    total_orders = 0
    total_sum = 0
    for p in pairs_data:
        wh, reg, cnt, sm = p[0], p[1], p[2], float(p[3] or 0)
        total_orders += cnt
        total_sum += sm
        if wh not in wh_totals:
            wh_totals[wh] = {"orders": 0, "sum": 0, "regions": set()}
        wh_totals[wh]["orders"] += cnt
        wh_totals[wh]["sum"] += sm
        wh_totals[wh]["regions"].add(reg)
        if reg not in reg_totals:
            reg_totals[reg] = {"orders": 0, "sum": 0, "warehouses": set()}
        reg_totals[reg]["orders"] += cnt
        reg_totals[reg]["sum"] += sm
        reg_totals[reg]["warehouses"].add(wh)

    warehouses = [
        {"name": k, "orders": v["orders"], "sum": v["sum"], "regions_count": len(v["regions"])}
        for k, v in sorted(wh_totals.items(), key=lambda x: -x[1]["orders"])
    ]
    regions = [
        {"name": k, "orders": v["orders"], "sum": v["sum"], "warehouses_count": len(v["warehouses"])}
        for k, v in sorted(reg_totals.items(), key=lambda x: -x[1]["orders"])
    ]

    routes = []
    for p in pairs_data:
        wh, reg, cnt, sm = p[0], p[1], p[2], float(p[3] or 0)
        wh_total = wh_totals[wh]["orders"]
        reg_total = reg_totals[reg]["orders"]
        routes.append({
            "warehouse": wh,
            "region": reg,
            "orders": cnt,
            "sum": sm,
            "pct_of_warehouse": round(cnt / wh_total * 100, 1) if wh_total else 0,
            "pct_of_region": round(cnt / reg_total * 100, 1) if reg_total else 0,
        })
    routes.sort(key=lambda x: -x["orders"])

    recs = []
    single_wh_regions = [(reg, data) for reg, data in reg_totals.items() if len(data["warehouses"]) == 1 and data["orders"] > 20]
    if single_wh_regions:
        for reg, data in sorted(single_wh_regions, key=lambda x: -x[1]["orders"])[:5]:
            wh = list(data["warehouses"])[0]
            recs.append({"type": "warning", "text": f"Регион «{reg}» обслуживается только складом «{wh}» ({data['orders']} заказов). Рекомендуется добавить поставки на ближайший склад."})

    top_wh = warehouses[0] if warehouses else None
    if top_wh and top_wh["orders"] > total_orders * 0.3:
        recs.append({"type": "info", "text": f"Склад «{top_wh['name']}» обрабатывает {round(top_wh['orders']/total_orders*100,1)}% всех заказов. Высокая концентрация — стоит рассмотреть decentralization."})

    big_routes = [r for r in routes if r["orders"] > 50 and r["pct_of_warehouse"] < 5]
    if big_routes:
        recs.append({"type": "danger", "text": f"Маршруты с малой долей от склада: {len(big_routes)} маршрутов с >50 заказами, но <5% от склада. Возможно, стоит перераспределить запасы."})

    if not recs:
        recs.append({"type": "success", "text": "Распределение запасов выглядит оптимальным. Крупные регионы обслуживаются ближайшими складами."})

    return {
        "warehouses": warehouses,
        "regions": regions,
        "pairs": [{"warehouse": p[0], "region": p[1], "orders": p[2], "sum": float(p[3] or 0)} for p in pairs_data],
        "routes": routes[:50],
        "total_orders": total_orders,
        "total_sum": total_sum,
        "recommendations": recs,
    }


# =====================
# РНП — Настройки, себестоимость, расходы, планы
# =====================


@app.get("/api/rnp/settings")
def rnp_get_settings(
    request: Request,
    cabinet_id: str = Query(...),
    db: Session = Depends(get_db),
):
    return get_rnp_settings(db, cabinet_id) or {"cabinet_id": cabinet_id, "usn_rate": 0.06, "nds_rate": 0.07}


@app.put("/api/rnp/settings")
def rnp_update_settings(
    request: Request,
    cabinet_id: str = Query(...),
    body: RnpSettingsUpdate = ...,
    db: Session = Depends(get_db),
):
    data = {k: v for k, v in body.model_dump().items() if v is not None}
    upsert_rnp_settings(db, cabinet_id, data)
    return {"ok": True}


@app.get("/api/rnp/costs")
def rnp_get_costs(
    request: Request,
    cabinet_id: str = Query(...),
    db: Session = Depends(get_db),
):
    return get_rnp_costs(db, cabinet_id)


@app.post("/api/rnp/costs")
def rnp_upsert_costs(
    request: Request,
    cabinet_id: str = Query(...),
    items: list[RnpCostIn] = ...,
    db: Session = Depends(get_db),
):
    upsert_rnp_costs_bulk(db, cabinet_id, [i.model_dump() for i in items])
    return {"ok": True, "count": len(items)}


@app.delete("/api/rnp/costs/{cost_id}")
def rnp_delete_cost(
    request: Request,
    cabinet_id: str = Query(...),
    cost_id: int = ...,
    db: Session = Depends(get_db),
):
    delete_rnp_cost(db, cabinet_id, cost_id)
    return {"ok": True}


@app.get("/api/rnp/fixed-expenses")
def rnp_get_fixed_expenses(
    request: Request,
    cabinet_id: str = Query(...),
    db: Session = Depends(get_db),
):
    return get_rnp_fixed_expenses(db, cabinet_id)


@app.post("/api/rnp/fixed-expenses")
def rnp_upsert_fixed_expenses(
    request: Request,
    cabinet_id: str = Query(...),
    items: list[RnpFixedExpenseIn] = ...,
    db: Session = Depends(get_db),
):
    upsert_rnp_fixed_expenses_bulk(db, cabinet_id, [i.model_dump() for i in items])
    return {"ok": True, "count": len(items)}


@app.delete("/api/rnp/fixed-expenses/{expense_id}")
def rnp_delete_fixed_expense(
    request: Request,
    cabinet_id: str = Query(...),
    expense_id: int = ...,
    db: Session = Depends(get_db),
):
    delete_rnp_fixed_expense(db, cabinet_id, expense_id)
    return {"ok": True}


@app.get("/api/rnp/variable-expenses")
def rnp_get_variable_expenses(
    request: Request,
    cabinet_id: str = Query(...),
    db: Session = Depends(get_db),
):
    return get_rnp_variable_expenses(db, cabinet_id)


@app.post("/api/rnp/variable-expenses")
def rnp_upsert_variable_expenses(
    request: Request,
    cabinet_id: str = Query(...),
    items: list[RnpVariableExpenseIn] = ...,
    db: Session = Depends(get_db),
):
    upsert_rnp_variable_expenses_bulk(db, cabinet_id, [i.model_dump() for i in items])
    return {"ok": True, "count": len(items)}


@app.delete("/api/rnp/variable-expenses/{expense_id}")
def rnp_delete_variable_expense(
    request: Request,
    cabinet_id: str = Query(...),
    expense_id: int = ...,
    db: Session = Depends(get_db),
):
    delete_rnp_variable_expense(db, cabinet_id, expense_id)
    return {"ok": True}


@app.get("/api/rnp/loan-payments")
def rnp_get_loan_payments(
    request: Request,
    cabinet_id: str = Query(...),
    db: Session = Depends(get_db),
):
    return get_rnp_loan_payments(db, cabinet_id)


@app.post("/api/rnp/loan-payments")
def rnp_upsert_loan_payments(
    request: Request,
    cabinet_id: str = Query(...),
    items: list[RnpLoanPaymentIn] = ...,
    db: Session = Depends(get_db),
):
    upsert_rnp_loan_payments_bulk(db, cabinet_id, [i.model_dump() for i in items])
    return {"ok": True, "count": len(items)}


@app.delete("/api/rnp/loan-payments/{payment_id}")
def rnp_delete_loan_payment(
    request: Request,
    cabinet_id: str = Query(...),
    payment_id: int = ...,
    db: Session = Depends(get_db),
):
    delete_rnp_loan_payment(db, cabinet_id, payment_id)
    return {"ok": True}


@app.get("/api/rnp/plans")
def rnp_get_plans(
    request: Request,
    cabinet_id: str = Query(...),
    db: Session = Depends(get_db),
):
    return get_rnp_plans(db, cabinet_id)


@app.post("/api/rnp/plans")
def rnp_upsert_plans(
    request: Request,
    cabinet_id: str = Query(...),
    items: list[RnpPlanIn] = ...,
    db: Session = Depends(get_db),
):
    upsert_rnp_plans_bulk(db, cabinet_id, [i.model_dump() for i in items])
    return {"ok": True, "count": len(items)}


@app.delete("/api/rnp/plans/{plan_id}")
def rnp_delete_plan(
    request: Request,
    cabinet_id: str = Query(...),
    plan_id: int = ...,
    db: Session = Depends(get_db),
):
    delete_rnp_plan(db, cabinet_id, plan_id)
    return {"ok": True}


@app.get("/api/rnp/calc")
def rnp_calc(
    request: Request,
    cabinet_id: str = Query(...),
    days_back: int = Query(40),
    db: Session = Depends(get_db),
):
    from app.rnp_calc import calc_rnp
    return calc_rnp(db, cabinet_id, days_back)


@app.get("/api/rnp/calc-month")
def rnp_calc_month(
    request: Request,
    cabinet_id: str = Query(...),
    month: str = Query(..., description="YYYY-MM"),
    comparison_mode: str = Query("day", description="day или week"),
    db: Session = Depends(get_db),
):
    from app.rnp_calc import calc_rnp_month
    return calc_rnp_month(db, cabinet_id, month, comparison_mode)