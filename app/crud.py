from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert
from app.models import ProductCharacteristic, SyncLog, Stock, Order, Price, SalesReport, Sale, User, ApiKey, WbToken, ShelfMetric, FunnelMetric, StockByOffice, ItemRating
from datetime import datetime, timedelta
import os
import hashlib
import json
import logging
from sqlalchemy.orm import load_only

logger = logging.getLogger(__name__)


# -------------------------
# Загрузка токенов и имён
# -------------------------
def load_tokens_mapping() -> dict[str, str]:
    raw = os.getenv("WB_TOKENS_JSON", "{}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {}

    mapping = {}
    for name, token in data.items():
        tid = hashlib.sha256(token.encode()).hexdigest()[:32]
        mapping[tid] = name

    return mapping


# -------------------------
# Общие функции
# -------------------------
def parse_date(date_str):
    if not date_str or date_str == "0001-01-01T00:00:00":
        return None
    try:
        return datetime.strptime(date_str[:19], "%Y-%m-%dT%H:%M:%S")
    except Exception:
        return None


# -------------------------
# Cleanup
# -------------------------
def clear_characteristics(db: Session, cabinet_id: str):
    """Удалить все характеристики кабинета перед перезаписью."""
    db.query(ProductCharacteristic).filter(
        ProductCharacteristic.cabinet_id == cabinet_id
    ).delete()
    db.commit()


def clear_stocks(db: Session, cabinet_id: str):
    """Удалить все остатки кабинета перед перезаписью."""
    db.query(Stock).filter(
        Stock.cabinet_id == cabinet_id
    ).delete()
    db.commit()


def clear_old_orders(db: Session, cabinet_id: str, days: int = 40):
    """Удалить заказы старше N дней."""
    threshold = datetime.now() - timedelta(days=days)
    db.query(Order).filter(
        Order.cabinet_id == cabinet_id,
        Order.date < threshold
    ).delete()
    db.commit()


def clear_old_sales(db: Session, cabinet_id: str, days: int = 40):
    """Удалить продажи старше N дней."""
    threshold = datetime.now() - timedelta(days=days)
    db.query(Sale).filter(
        Sale.cabinet_id == cabinet_id,
        Sale.date < threshold
    ).delete()
    db.commit()


def clear_sales_report(db: Session, cabinet_id: str):
    """Удалить все записи отчёта реализации кабинета перед перезаписью."""
    db.query(SalesReport).filter(
        SalesReport.cabinet_id == cabinet_id
    ).delete()
    db.commit()


# -------------------------
# ProductCharacteristic
# -------------------------
def upsert_characteristic(db: Session, cabinet_id: str, nm_id: int, data: dict):
    stmt = pg_insert(ProductCharacteristic).values(
        cabinet_id=cabinet_id,
        nm_id=nm_id,
        characteristics=data,
    ).on_conflict_do_update(
        constraint="uq_cabinet_nm",
        set_={
            "characteristics": data,
            "synced_at": datetime.utcnow(),
        },
    )
    db.execute(stmt)


# -------------------------
# Stocks
# -------------------------
def upsert_stock(db: Session, cabinet_id: str, item: dict):
    stmt = pg_insert(Stock).values(
        cabinet_id=cabinet_id,
        nm_id=item["nmId"],
        chrt_id=item["chrtId"],
        warehouse_id=item["warehouseId"],
        warehouse_name=item.get("warehouseName", ""),
        region_name=item.get("regionName", ""),
        quantity=item["quantity"],
        in_way_to_client=item["inWayToClient"],
        in_way_from_client=item["inWayFromClient"],
        raw_data=item,
    ).on_conflict_do_update(
        constraint="uq_stock",
        set_={
            "quantity": item["quantity"],
            "in_way_to_client": item["inWayToClient"],
            "in_way_from_client": item["inWayFromClient"],
            "raw_data": item,
            "synced_at": datetime.utcnow(),
        },
    )
    db.execute(stmt)


# -------------------------
# Orders
# -------------------------
def upsert_orders_chunk(db: Session, cabinet_id: str, chunk: list[dict]):
    if not chunk:
        return

    values = [
        {
            "cabinet_id": cabinet_id,
            "srid": o.get("srid"),
            "g_number": o.get("gNumber"),
            "nm_id": o.get("nmId"),
            "supplier_article": o.get("supplierArticle"),
            "barcode": o.get("barcode"),
            "date": parse_date(o.get("date")),
            "last_change_date": parse_date(o.get("lastChangeDate")),
            "cancel_date": parse_date(o.get("cancelDate")),
            "total_price": o.get("totalPrice"),
            "finished_price": o.get("finishedPrice"),
            "price_with_disc": o.get("priceWithDisc"),
            "discount_percent": o.get("discountPercent"),
            "spp": o.get("spp"),
            "is_cancel": o.get("isCancel", False),
            "is_supply": o.get("isSupply", False),
            "is_realization": o.get("isRealization", False),
            "warehouse_name": o.get("warehouseName"),
            "warehouse_type": o.get("warehouseType"),
            "country_name": o.get("countryName"),
            "region_name": o.get("regionName"),
            "category": o.get("category"),
            "subject": o.get("subject"),
            "brand": o.get("brand"),
            "tech_size": o.get("techSize"),
            "sticker": o.get("sticker"),
            "income_id": o.get("incomeID"),
            "raw_data": o,
            "synced_at": datetime.utcnow(),
        }
        for o in chunk
    ]

    stmt = pg_insert(Order).values(values).on_conflict_do_update(
        constraint="uq_cabinet_order",
        set_={
            "last_change_date": pg_insert(Order).excluded.last_change_date,
            "cancel_date": pg_insert(Order).excluded.cancel_date,
            "finished_price": pg_insert(Order).excluded.finished_price,
            "price_with_disc": pg_insert(Order).excluded.price_with_disc,
            "is_cancel": pg_insert(Order).excluded.is_cancel,
            "raw_data": pg_insert(Order).excluded.raw_data,
            "synced_at": pg_insert(Order).excluded.synced_at,
        },
    )

    db.execute(stmt)
    db.commit()
    db.expunge_all()


def upsert_orders_bulk(db: Session, cabinet_id: str, orders: list[dict], chunk_size: int = 5000):
    for i in range(0, len(orders), chunk_size):
        upsert_orders_chunk(db, cabinet_id, orders[i:i + chunk_size])


# -------------------------
# SyncLog
# -------------------------
def log_sync(db: Session, cabinet_id: str, status: str, message: str | None = None, records: int = 0):
    entry = SyncLog(
        cabinet_id=cabinet_id,
        status=status,
        message=message,
        records_saved=records,
    )
    db.add(entry)


# -------------------------
# Queries
# -------------------------
def get_characteristics(db: Session, cabinet_id: str | None = None, nm_id: int | None = None):
    q = db.query(ProductCharacteristic)
    if cabinet_id:
        q = q.filter(ProductCharacteristic.cabinet_id == cabinet_id)
    if nm_id:
        q = q.filter(ProductCharacteristic.nm_id == nm_id)
    return q.order_by(ProductCharacteristic.synced_at.desc()).limit(500).all()


def get_stocks(db: Session, cabinet_id: str | None = None, nm_id: int | None = None):
    q = db.query(Stock)
    if cabinet_id:
        q = q.filter(Stock.cabinet_id == cabinet_id)
    if nm_id:
        q = q.filter(Stock.nm_id == nm_id)
    return q.order_by(Stock.synced_at.desc()).limit(10000).all()


def get_orders(
    db: Session,
    cabinet_id: str | None = None,
    days_back: int = 40,
    limit: int = 1000,
    offset: int = 0,
    fields=None,
):
    q = db.query(Order)
    if fields:
        cols = [getattr(Order, f) for f in fields if hasattr(Order, f)]
        if cols:
            q = q.options(load_only(*cols, Order.cabinet_id))
    if cabinet_id:
        q = q.filter(Order.cabinet_id == cabinet_id)
    threshold_date = datetime.now() - timedelta(days=days_back)
    q = q.filter(Order.date >= threshold_date)
    return q.order_by(Order.date.desc()).offset(offset).limit(limit).all()


def get_sync_logs(db: Session, limit: int = 50):
    return db.query(SyncLog).order_by(SyncLog.created_at.desc()).limit(limit).all()


# -------------------------
# Prices
# -------------------------
def upsert_price(db: Session, cabinet_id: str, item: dict, size: dict):
    stmt = pg_insert(Price).values(
        cabinet_id=cabinet_id,
        nm_id=item.get("nmID"),
        chrt_id=size.get("sizeID"),
        price=size.get("price", 0),
        discounted_price=size.get("discountedPrice", 0),
        club_discounted_price=size.get("clubDiscountedPrice", 0),
        currency=size.get("currencyIsoCode4217", "RUB"),
        discount=size.get("discount", 0),
        club_discount=size.get("clubDiscount", 0),
        tech_size_name=size.get("techSizeName", ""),
        raw_data={**item, "size": size},
        synced_at=datetime.utcnow(),
    ).on_conflict_do_update(
        constraint="uq_price",
        set_={
            "price": size.get("price", 0),
            "discounted_price": size.get("discountedPrice", 0),
            "club_discounted_price": size.get("clubDiscountedPrice", 0),
            "discount": size.get("discount", 0),
            "club_discount": size.get("clubDiscount", 0),
            "raw_data": pg_insert(Price).excluded.raw_data,
            "synced_at": datetime.utcnow(),
        },
    )
    db.execute(stmt)


def get_prices(db: Session, cabinet_id: str = None, nm_id: int = None):
    q = db.query(Price)
    if cabinet_id:
        q = q.filter(Price.cabinet_id == cabinet_id)
    if nm_id:
        q = q.filter(Price.nm_id == nm_id)
    return q.order_by(Price.synced_at.desc()).limit(10000).all()


# -------------------------
# Sales Report
# -------------------------
def upsert_sales_report_row(db: Session, cabinet_id: str, row: dict):
    def parse_dt(val: str | None) -> datetime | None:
        if not val:
            return None
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(val[:19], fmt[:len(val[:19])])
            except Exception:
                continue
        return None

    stmt = pg_insert(SalesReport).values(
        cabinet_id=cabinet_id,
        rrd_id=row.get("rrd_id"),
        realizationreport_id=row.get("realizationreport_id"),
        gi_id=row.get("gi_id"),
        nm_id=row.get("nm_id"),
        shk_id=row.get("shk_id"),
        assembly_id=row.get("assembly_id"),
        srid=row.get("srid"),
        order_uid=row.get("order_uid"),
        date_from=parse_dt(row.get("date_from")),
        date_to=parse_dt(row.get("date_to")),
        create_dt=parse_dt(row.get("create_dt")),
        rr_dt=parse_dt(row.get("rr_dt")),
        order_dt=parse_dt(row.get("order_dt")),
        sale_dt=parse_dt(row.get("sale_dt")),
        fix_tariff_date_from=parse_dt(row.get("fix_tariff_date_from")),
        fix_tariff_date_to=parse_dt(row.get("fix_tariff_date_to")),
        subject_name=row.get("subject_name"),
        brand_name=row.get("brand_name"),
        sa_name=row.get("sa_name"),
        ts_name=row.get("ts_name"),
        barcode=row.get("barcode"),
        doc_type_name=row.get("doc_type_name"),
        supplier_oper_name=row.get("supplier_oper_name"),
        office_name=row.get("office_name"),
        quantity=row.get("quantity"),
        currency_name=row.get("currency_name"),
        retail_price=row.get("retail_price"),
        retail_amount=row.get("retail_amount"),
        retail_price_withdisc_rub=row.get("retail_price_withdisc_rub"),
        sale_percent=row.get("sale_percent"),
        commission_percent=row.get("commission_percent"),
        product_discount_for_report=row.get("product_discount_for_report"),
        supplier_promo=row.get("supplier_promo"),
        ppvz_spp_prc=row.get("ppvz_spp_prc"),
        ppvz_kvw_prc_base=row.get("ppvz_kvw_prc_base"),
        ppvz_kvw_prc=row.get("ppvz_kvw_prc"),
        ppvz_sales_commission=row.get("ppvz_sales_commission"),
        ppvz_for_pay=row.get("ppvz_for_pay"),
        ppvz_reward=row.get("ppvz_reward"),
        ppvz_vw=row.get("ppvz_vw"),
        ppvz_vw_nds=row.get("ppvz_vw_nds"),
        sup_rating_prc_up=row.get("sup_rating_prc_up"),
        is_kgvp_v2=row.get("is_kgvp_v2"),
        acquiring_fee=row.get("acquiring_fee"),
        acquiring_percent=row.get("acquiring_percent"),
        acquiring_bank=row.get("acquiring_bank"),
        payment_processing=row.get("payment_processing"),
        delivery_amount=row.get("delivery_amount"),
        return_amount=row.get("return_amount"),
        delivery_rub=row.get("delivery_rub"),
        gi_box_type_name=row.get("gi_box_type_name"),
        rebill_logistic_cost=row.get("rebill_logistic_cost"),
        rebill_logistic_org=row.get("rebill_logistic_org"),
        dlv_prc=row.get("dlv_prc"),
        penalty=row.get("penalty"),
        additional_payment=row.get("additional_payment"),
        storage_fee=row.get("storage_fee"),
        deduction=row.get("deduction"),
        acceptance=row.get("acceptance"),
        site_country=row.get("site_country"),
        ppvz_office_name=row.get("ppvz_office_name"),
        ppvz_office_id=row.get("ppvz_office_id"),
        ppvz_supplier_id=row.get("ppvz_supplier_id"),
        ppvz_supplier_name=row.get("ppvz_supplier_name"),
        ppvz_inn=row.get("ppvz_inn"),
        sticker_id=row.get("sticker_id"),
        declaration_number=row.get("declaration_number"),
        bonus_type_name=row.get("bonus_type_name"),
        kiz=row.get("kiz"),
        srv_dbs=row.get("srv_dbs"),
        is_legal_entity=row.get("is_legal_entity"),
        report_type=row.get("report_type"),
        raw_data=row,
        synced_at=datetime.utcnow(),
    ).on_conflict_do_update(
        constraint="uq_sales_report_row",
        set_={
            "ppvz_for_pay": row.get("ppvz_for_pay"),
            "penalty": row.get("penalty"),
            "additional_payment": row.get("additional_payment"),
            "storage_fee": row.get("storage_fee"),
            "deduction": row.get("deduction"),
            "raw_data": pg_insert(SalesReport).excluded.raw_data,
            "synced_at": datetime.utcnow(),
        },
    )
    db.execute(stmt)


def get_sales_report(
    db: Session,
    cabinet_id: str | None = None,
    nm_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 1000,
):
    q = db.query(SalesReport)
    if cabinet_id:
        q = q.filter(SalesReport.cabinet_id == cabinet_id)
    if nm_id:
        q = q.filter(SalesReport.nm_id == nm_id)
    if date_from:
        q = q.filter(SalesReport.rr_dt >= date_from)
    if date_to:
        q = q.filter(SalesReport.rr_dt <= date_to)
    return q.order_by(SalesReport.rr_dt.desc()).limit(limit).all()


# -------------------------
# Sales
# -------------------------
def upsert_sales_chunk(db: Session, cabinet_id: str, chunk: list[dict]):
    if not chunk:
        return

    values = [
        {
            "cabinet_id": cabinet_id,
            "srid": s.get("srid"),
            "sale_id": s.get("saleID"),
            "g_number": s.get("gNumber"),
            "nm_id": s.get("nmId"),
            "supplier_article": s.get("supplierArticle"),
            "barcode": s.get("barcode"),
            "date": parse_date(s.get("date")),
            "last_change_date": parse_date(s.get("lastChangeDate")),
            "total_price": s.get("totalPrice"),
            "finished_price": s.get("finishedPrice"),
            "price_with_disc": s.get("priceWithDisc"),
            "discount_percent": s.get("discountPercent"),
            "spp": s.get("spp"),
            "for_pay": s.get("forPay"),
            "payment_sale_amount": s.get("paymentSaleAmount"),
            "is_supply": s.get("isSupply", False),
            "is_realization": s.get("isRealization", False),
            "warehouse_name": s.get("warehouseName"),
            "warehouse_type": s.get("warehouseType"),
            "country_name": s.get("countryName"),
            "oblast_okrug_name": s.get("oblastOkrugName"),
            "region_name": s.get("regionName"),
            "category": s.get("category"),
            "subject": s.get("subject"),
            "brand": s.get("brand"),
            "tech_size": s.get("techSize"),
            "sticker": s.get("sticker"),
            "income_id": s.get("incomeID"),
            "raw_data": s,
            "synced_at": datetime.utcnow(),
        }
        for s in chunk
    ]

    stmt = pg_insert(Sale).values(values).on_conflict_do_update(
        constraint="uq_cabinet_sale",
        set_={
            "last_change_date": pg_insert(Sale).excluded.last_change_date,
            "for_pay": pg_insert(Sale).excluded.for_pay,
            "finished_price": pg_insert(Sale).excluded.finished_price,
            "raw_data": pg_insert(Sale).excluded.raw_data,
            "synced_at": pg_insert(Sale).excluded.synced_at,
        },
    )

    db.execute(stmt)
    db.commit()
    db.expunge_all()


def upsert_sales_bulk(db: Session, cabinet_id: str, sales: list[dict], chunk_size: int = 5000):
    for i in range(0, len(sales), chunk_size):
        upsert_sales_chunk(db, cabinet_id, sales[i:i + chunk_size])


def get_sales(
    db: Session,
    cabinet_id: str | None = None,
    nm_id: int | None = None,
    days_back: int = 40,
    limit: int = 1000,
    offset: int = 0,
    fields=None,
):
    q = db.query(Sale)
    if fields:
        cols = [getattr(Sale, f) for f in fields if hasattr(Sale, f)]
        if cols:
            q = q.options(load_only(*cols, Sale.cabinet_id))
    if cabinet_id:
        q = q.filter(Sale.cabinet_id == cabinet_id)
    if nm_id:
        q = q.filter(Sale.nm_id == nm_id)
    threshold = datetime.now() - timedelta(days=days_back)
    q = q.filter(Sale.date >= threshold)
    return q.order_by(Sale.date.desc()).offset(offset).limit(limit).all()


# =====================
# USER CRUD
# =====================

def create_user(db: Session, username: str, email: str | None = None, password_hash: str | None = None) -> User:
    user = User(username=username, email=email, password_hash=password_hash)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.query(User).filter(User.id == user_id).first()


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.query(User).filter(User.username == username).first()


def list_users(db: Session) -> list[User]:
    return db.query(User).order_by(User.created_at.desc()).all()


def update_user(db: Session, user_id: int, **kwargs) -> User | None:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return None
    for key, value in kwargs.items():
        if hasattr(user, key):
            setattr(user, key, value)
    db.commit()
    db.refresh(user)
    return user


def delete_user(db: Session, user_id: int) -> bool:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return False
    db.delete(user)
    db.commit()
    return True


# =====================
# API KEY CRUD
# =====================

def create_api_key(db: Session, user_id: int, key_hash: str, name: str | None = None, expires_at: datetime | None = None) -> ApiKey:
    api_key = ApiKey(user_id=user_id, key_hash=key_hash, name=name, expires_at=expires_at)
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return api_key


def get_api_key_by_hash(db: Session, key_hash: str) -> ApiKey | None:
    return db.query(ApiKey).filter(ApiKey.key_hash == key_hash).first()


def list_api_keys(db: Session, user_id: int | None = None) -> list[ApiKey]:
    q = db.query(ApiKey)
    if user_id:
        q = q.filter(ApiKey.user_id == user_id)
    return q.order_by(ApiKey.created_at.desc()).all()


def update_api_key_last_used(db: Session, api_key_id: int):
    api_key = db.query(ApiKey).filter(ApiKey.id == api_key_id).first()
    if api_key:
        api_key.last_used_at = datetime.utcnow()
        db.commit()


def delete_api_key(db: Session, api_key_id: int) -> bool:
    api_key = db.query(ApiKey).filter(ApiKey.id == api_key_id).first()
    if not api_key:
        return False
    db.delete(api_key)
    db.commit()
    return True


# =====================
# WB TOKEN CRUD
# =====================

def create_wb_token(db: Session, user_id: int, seller_name: str, token: str) -> WbToken:
    token_hash = hashlib.sha256(token.encode()).hexdigest()[:32]
    wb_token = WbToken(user_id=user_id, seller_name=seller_name, token=token, token_hash=token_hash)
    db.add(wb_token)
    db.commit()
    db.refresh(wb_token)
    return wb_token


def get_wb_token_by_hash(db: Session, token_hash: str) -> WbToken | None:
    return db.query(WbToken).filter(WbToken.token_hash == token_hash).first()


def list_wb_tokens(db: Session, user_id: int | None = None, active_only: bool = False) -> list[WbToken]:
    q = db.query(WbToken)
    if user_id:
        q = q.filter(WbToken.user_id == user_id)
    if active_only:
        q = q.filter(WbToken.is_active == True)
    return q.order_by(WbToken.created_at.desc()).all()


def update_wb_token(db: Session, token_id: int, **kwargs) -> WbToken | None:
    wb_token = db.query(WbToken).filter(WbToken.id == token_id).first()
    if not wb_token:
        return None
    for key, value in kwargs.items():
        if hasattr(wb_token, key):
            setattr(wb_token, key, value)
    wb_token.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(wb_token)
    return wb_token


def delete_wb_token(db: Session, token_id: int) -> bool:
    wb_token = db.query(WbToken).filter(WbToken.id == token_id).first()
    if not wb_token:
        return False
    db.delete(wb_token)
    db.commit()
    return True


def get_tokens_from_db() -> list[dict]:
    """Загрузка токенов из БД (заменяет load_tokens_from_json)."""
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        tokens = db.query(WbToken).filter(WbToken.is_active == True).all()
        return [{"token": t.token, "name": t.seller_name, "cabinet_id": t.token_hash} for t in tokens]
    finally:
        db.close()


def get_token_mapping_from_db() -> dict[str, str]:
    """Получение маппинга cabinet_id → seller_name из БД."""
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        tokens = db.query(WbToken).filter(WbToken.is_active == True).all()
        return {t.token_hash: t.seller_name for t in tokens}
    finally:
        db.close()


def load_token_mapping() -> dict[str, str]:
    """Единая функция загрузки маппинга токенов (из БД или env var как fallback)."""
    mapping = get_token_mapping_from_db()
    if mapping:
        return mapping

    # Fallback: загрузка из env var (для обратной совместимости)
    raw = os.getenv("WB_TOKENS_JSON", "{}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {}

    for name, token in data.items():
        tid = hashlib.sha256(token.encode()).hexdigest()[:32]
        mapping[tid] = name

    return mapping


# -------------------------
# Shelf Metrics (Витрина продаж — sales-funnel v3)
# -------------------------
def clear_shelf_metrics(db: Session, cabinet_id: str):
    db.query(ShelfMetric).filter(ShelfMetric.cabinet_id == cabinet_id).delete()
    db.commit()


def upsert_shelf_metric(db: Session, cabinet_id: str, item: dict, period_start: datetime, period_end: datetime):
    product = item.get("product", {})
    stats = item.get("statistic", {}).get("selected", {})
    conv = stats.get("conversions", {})
    stocks = product.get("stocks", {})

    stmt = pg_insert(ShelfMetric).values(
        cabinet_id=cabinet_id,
        nm_id=product.get("nmId", 0),
        vendor_code=product.get("vendorCode", ""),
        product_name=product.get("title", ""),
        subject_name=product.get("subjectName", ""),
        brand_name=product.get("brandName", ""),
        product_rating=product.get("productRating", 0),
        feedback_rating=product.get("feedbackRating", 0),
        period_start=period_start,
        period_end=period_end,
        open_count=stats.get("openCount", 0),
        cart_count=stats.get("cartCount", 0),
        order_count=stats.get("orderCount", 0),
        order_sum=stats.get("orderSum", 0),
        buyout_count=stats.get("buyoutCount", 0),
        buyout_sum=stats.get("buyoutSum", 0),
        cancel_count=stats.get("cancelCount", 0),
        cancel_sum=stats.get("cancelSum", 0),
        avg_price=stats.get("avgPrice", 0),
        avg_orders_per_day=stats.get("avgOrdersCountPerDay", 0),
        share_order_percent=stats.get("shareOrderPercent", 0),
        add_to_wishlist=stats.get("addToWishlist", 0),
        conv_add_to_cart=conv.get("addToCartPercent", 0),
        conv_cart_to_order=conv.get("cartToOrderPercent", 0),
        conv_buyout=conv.get("buyoutPercent", 0),
        stocks_wb=stocks.get("wb", 0),
        stocks_mp=stocks.get("mp", 0),
        raw_data=item,
    ).on_conflict_do_update(
        constraint="uq_shelf_metric",
        set_={
            "open_count": pg_insert(ShelfMetric).excluded.open_count,
            "cart_count": pg_insert(ShelfMetric).excluded.cart_count,
            "order_count": pg_insert(ShelfMetric).excluded.order_count,
            "order_sum": pg_insert(ShelfMetric).excluded.order_sum,
            "buyout_count": pg_insert(ShelfMetric).excluded.buyout_count,
            "buyout_sum": pg_insert(ShelfMetric).excluded.buyout_sum,
            "cancel_count": pg_insert(ShelfMetric).excluded.cancel_count,
            "cancel_sum": pg_insert(ShelfMetric).excluded.cancel_sum,
            "conv_add_to_cart": pg_insert(ShelfMetric).excluded.conv_add_to_cart,
            "conv_cart_to_order": pg_insert(ShelfMetric).excluded.conv_cart_to_order,
            "conv_buyout": pg_insert(ShelfMetric).excluded.conv_buyout,
            "stocks_wb": pg_insert(ShelfMetric).excluded.stocks_wb,
            "raw_data": pg_insert(ShelfMetric).excluded.raw_data,
            "synced_at": datetime.utcnow(),
        },
    )
    db.execute(stmt)


def get_shelf_metrics(db: Session, cabinet_id: str | None = None, days_back: int = 30):
    threshold = datetime.now() - timedelta(days=days_back)
    q = db.query(ShelfMetric).filter(ShelfMetric.period_end >= threshold)
    if cabinet_id:
        q = q.filter(ShelfMetric.cabinet_id == cabinet_id)
    return q.order_by(ShelfMetric.order_sum.desc()).limit(50000).all()


# -------------------------
# Funnel Metrics (Воронка конверсии — sales-funnel v3)
# -------------------------
def clear_funnel_metrics(db: Session, cabinet_id: str):
    db.query(FunnelMetric).filter(FunnelMetric.cabinet_id == cabinet_id).delete()
    db.commit()


def upsert_funnel_metric(db: Session, cabinet_id: str, item: dict, period_start: datetime, period_end: datetime):
    product = item.get("product", {})
    stats = item.get("statistic", {})
    selected = stats.get("selected", {})
    past = stats.get("past", {})
    comparison = stats.get("comparison", {})
    conv = selected.get("conversions", {})
    past_conv = past.get("conversions", {})

    stmt = pg_insert(FunnelMetric).values(
        cabinet_id=cabinet_id,
        nm_id=product.get("nmId", 0),
        vendor_code=product.get("vendorCode", ""),
        product_name=product.get("title", ""),
        subject_name=product.get("subjectName", ""),
        brand_name=product.get("brandName", ""),
        period_start=period_start,
        period_end=period_end,
        open_count=selected.get("openCount", 0),
        cart_count=selected.get("cartCount", 0),
        order_count=selected.get("orderCount", 0),
        order_sum=selected.get("orderSum", 0),
        buyout_count=selected.get("buyoutCount", 0),
        buyout_sum=selected.get("buyoutSum", 0),
        conv_add_to_cart=conv.get("addToCartPercent", 0),
        conv_cart_to_order=conv.get("cartToOrderPercent", 0),
        conv_buyout=conv.get("buyoutPercent", 0),
        past_open_count=past.get("openCount", 0),
        past_cart_count=past.get("cartCount", 0),
        past_order_count=past.get("orderCount", 0),
        past_order_sum=past.get("orderSum", 0),
        past_buyout_count=past.get("buyoutCount", 0),
        past_conv_buyout=past_conv.get("buyoutPercent", 0),
        dynamic_open=comparison.get("openCountDynamic", 0),
        dynamic_cart=comparison.get("cartCountDynamic", 0),
        dynamic_order=comparison.get("orderCountDynamic", 0),
        dynamic_buyout=comparison.get("buyoutCountDynamic", 0),
        raw_data=item,
    ).on_conflict_do_update(
        constraint="uq_funnel_metric",
        set_={
            "open_count": pg_insert(FunnelMetric).excluded.open_count,
            "cart_count": pg_insert(FunnelMetric).excluded.cart_count,
            "order_count": pg_insert(FunnelMetric).excluded.order_count,
            "order_sum": pg_insert(FunnelMetric).excluded.order_sum,
            "buyout_count": pg_insert(FunnelMetric).excluded.buyout_count,
            "conv_add_to_cart": pg_insert(FunnelMetric).excluded.conv_add_to_cart,
            "conv_cart_to_order": pg_insert(FunnelMetric).excluded.conv_cart_to_order,
            "conv_buyout": pg_insert(FunnelMetric).excluded.conv_buyout,
            "past_open_count": pg_insert(FunnelMetric).excluded.past_open_count,
            "past_cart_count": pg_insert(FunnelMetric).excluded.past_cart_count,
            "past_order_count": pg_insert(FunnelMetric).excluded.past_order_count,
            "past_order_sum": pg_insert(FunnelMetric).excluded.past_order_sum,
            "past_buyout_count": pg_insert(FunnelMetric).excluded.past_buyout_count,
            "past_conv_buyout": pg_insert(FunnelMetric).excluded.past_conv_buyout,
            "dynamic_open": pg_insert(FunnelMetric).excluded.dynamic_open,
            "dynamic_cart": pg_insert(FunnelMetric).excluded.dynamic_cart,
            "dynamic_order": pg_insert(FunnelMetric).excluded.dynamic_order,
            "dynamic_buyout": pg_insert(FunnelMetric).excluded.dynamic_buyout,
            "raw_data": pg_insert(FunnelMetric).excluded.raw_data,
            "synced_at": datetime.utcnow(),
        },
    )
    db.execute(stmt)


def get_funnel_metrics(db: Session, cabinet_id: str | None = None, days_back: int = 30):
    threshold = datetime.now() - timedelta(days=days_back)
    q = db.query(FunnelMetric).filter(FunnelMetric.period_end >= threshold)
    if cabinet_id:
        q = q.filter(FunnelMetric.cabinet_id == cabinet_id)
    return q.order_by(FunnelMetric.order_sum.desc()).limit(50000).all()


# -------------------------
# Stock By Office (Остатки по offices)
# -------------------------
def clear_stock_by_offices(db: Session, cabinet_id: str):
    db.query(StockByOffice).filter(StockByOffice.cabinet_id == cabinet_id).delete()
    db.commit()

def upsert_stock_by_office(db: Session, cabinet_id: str, region: dict, office: dict, period_start: datetime, period_end: datetime):
    m = office.get("metrics", {})
    sr = m.get("saleRate", {})
    stmt = pg_insert(StockByOffice).values(
        cabinet_id=cabinet_id,
        region_name=region.get("regionName", ""),
        office_id=office.get("officeID", 0),
        office_name=office.get("officeName", ""),
        period_start=period_start, period_end=period_end,
        stock_count=m.get("stockCount", 0), stock_sum=m.get("stockSum", 0),
        sale_rate_days=sr.get("days", 0) if isinstance(sr, dict) else 0,
        to_client_count=m.get("toClientCount", 0), from_client_count=m.get("fromClientCount", 0),
        raw_data={"region": region.get("regionName"), "office": office},
    ).on_conflict_do_update(
        constraint="uq_stock_office",
        set_={"stock_count": pg_insert(StockByOffice).excluded.stock_count, "stock_sum": pg_insert(StockByOffice).excluded.stock_sum, "sale_rate_days": pg_insert(StockByOffice).excluded.sale_rate_days, "to_client_count": pg_insert(StockByOffice).excluded.to_client_count, "from_client_count": pg_insert(StockByOffice).excluded.from_client_count, "raw_data": pg_insert(StockByOffice).excluded.raw_data, "synced_at": datetime.utcnow()},
    )
    db.execute(stmt)

def get_stock_by_offices(db: Session, cabinet_id: str | None = None):
    q = db.query(StockByOffice)
    if cabinet_id:
        q = q.filter(StockByOffice.cabinet_id == cabinet_id)
    return q.order_by(StockByOffice.stock_sum.desc()).limit(50000).all()


# -------------------------
# Item Rating (Рейтинг товаров)
# -------------------------
def clear_item_ratings(db: Session, cabinet_id: str):
    db.query(ItemRating).filter(ItemRating.cabinet_id == cabinet_id).delete()
    db.commit()

def upsert_item_rating(db: Session, cabinet_id: str, card: dict, seller_rating: float, period_start: datetime, period_end: datetime):
    stmt = pg_insert(ItemRating).values(
        cabinet_id=cabinet_id, nm_id=card.get("nmId", 0),
        vendor_code=card.get("vendorCode", ""), product_name=card.get("title", ""),
        subject_name=card.get("subjectName", ""), brand_name=card.get("brandName", ""),
        period_start=period_start, period_end=period_end,
        seller_rating=seller_rating,
        product_rating=card.get("rating", 0),
        feedback_rating=card.get("feedbackRating", {}).get("current", 0),
        feedback_percentile=card.get("feedbackRating", {}).get("percentile", 0),
        feedback_count=card.get("feedbackCount", {}).get("current", 0),
        five_star=card.get("fiveStar", {}).get("current", 0),
        four_star=card.get("fourStar", {}).get("current", 0),
        three_star=card.get("threeStar", {}).get("current", 0),
        two_star=card.get("twoStar", {}).get("current", 0),
        one_star=card.get("oneStar", {}).get("current", 0),
        disqualified=card.get("disqualified", 0),
        raw_data=card,
    ).on_conflict_do_update(
        constraint="uq_item_rating",
        set_={"feedback_rating": pg_insert(ItemRating).excluded.feedback_rating, "feedback_count": pg_insert(ItemRating).excluded.feedback_count, "five_star": pg_insert(ItemRating).excluded.five_star, "four_star": pg_insert(ItemRating).excluded.four_star, "three_star": pg_insert(ItemRating).excluded.three_star, "two_star": pg_insert(ItemRating).excluded.two_star, "one_star": pg_insert(ItemRating).excluded.one_star, "seller_rating": pg_insert(ItemRating).excluded.seller_rating, "raw_data": pg_insert(ItemRating).excluded.raw_data, "synced_at": datetime.utcnow()},
    )
    db.execute(stmt)

def get_item_ratings(db: Session, cabinet_id: str | None = None):
    q = db.query(ItemRating)
    if cabinet_id:
        q = q.filter(ItemRating.cabinet_id == cabinet_id)
    return q.order_by(ItemRating.feedback_count.desc()).limit(50000).all()

    # Fallback: загрузка из env var (для обратной совместимости)
    raw = os.getenv("WB_TOKENS_JSON", "{}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {}

    for name, token in data.items():
        tid = hashlib.sha256(token.encode()).hexdigest()[:32]
        mapping[tid] = name

    return mapping