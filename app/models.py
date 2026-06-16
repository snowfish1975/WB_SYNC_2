from datetime import datetime
from sqlalchemy import String, Integer, DateTime, JSON, UniqueConstraint, Float, Boolean, BigInteger, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class ProductCharacteristic(Base):
    __tablename__ = "product_characteristics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cabinet_id: Mapped[str] = mapped_column(String(32))  # SHA-256 хэш токена
    nm_id: Mapped[int] = mapped_column(Integer)
    characteristics: Mapped[dict] = mapped_column(JSON)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("cabinet_id", "nm_id", name="uq_cabinet_nm"),
    )


class SyncLog(Base):
    __tablename__ = "sync_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cabinet_id: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(String(500), nullable=True)
    records_saved: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Stock(Base):
    __tablename__ = "stocks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cabinet_id: Mapped[str] = mapped_column(String(32))
    nm_id: Mapped[int] = mapped_column(Integer)
    chrt_id: Mapped[int] = mapped_column(Integer)
    warehouse_id: Mapped[int] = mapped_column(Integer)
    warehouse_name: Mapped[str] = mapped_column(String(200))
    region_name: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[int] = mapped_column(Integer)
    in_way_to_client: Mapped[int] = mapped_column(Integer)
    in_way_from_client: Mapped[int] = mapped_column(Integer)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    raw_data: Mapped[dict] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint("cabinet_id", "chrt_id", "warehouse_id", name="uq_stock"),
    )


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    cabinet_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    
    # Основные поля заказа
    srid: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # Уникальный ID заказа
    g_number: Mapped[str] = mapped_column(String(50), nullable=True, index=True)  # ID корзины
    nm_id: Mapped[int] = mapped_column(Integer, nullable=True, index=True)
    supplier_article: Mapped[str] = mapped_column(String(75), nullable=True)
    barcode: Mapped[str] = mapped_column(String(30), nullable=True)
    
    # Информация о заказе
    date: Mapped[datetime] = mapped_column(DateTime, nullable=True)  # Дата и время заказа (создания)
    last_change_date: Mapped[datetime] = mapped_column(DateTime, nullable=True)  # Дата последнего изменения
    cancel_date: Mapped[datetime] = mapped_column(DateTime, nullable=True)  # Дата отмены
    
    # Цены
    total_price: Mapped[float] = mapped_column(Float, nullable=True)
    finished_price: Mapped[float] = mapped_column(Float, nullable=True)
    price_with_disc: Mapped[float] = mapped_column(Float, nullable=True)
    discount_percent: Mapped[int] = mapped_column(Integer, nullable=True)
    spp: Mapped[float] = mapped_column(Float, nullable=True)
    
    # Статусы
    is_cancel: Mapped[bool] = mapped_column(Boolean, default=False)
    is_supply: Mapped[bool] = mapped_column(Boolean, default=False)
    is_realization: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Дополнительная информация
    warehouse_name: Mapped[str] = mapped_column(String(50), nullable=True)
    warehouse_type: Mapped[str] = mapped_column(String(50), nullable=True)
    country_name: Mapped[str] = mapped_column(String(200), nullable=True)
    region_name: Mapped[str] = mapped_column(String(200), nullable=True)
    category: Mapped[str] = mapped_column(String(50), nullable=True)
    subject: Mapped[str] = mapped_column(String(50), nullable=True)
    brand: Mapped[str] = mapped_column(String(50), nullable=True)
    tech_size: Mapped[str] = mapped_column(String(30), nullable=True)
    sticker: Mapped[str] = mapped_column(String(50), nullable=True)
    income_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    
    # Служебные поля
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    raw_data: Mapped[dict] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint("cabinet_id", "srid", name="uq_cabinet_order"),
    )


class Price(Base):
    __tablename__ = "prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cabinet_id: Mapped[str] = mapped_column(String(32))
    nm_id: Mapped[int] = mapped_column(Integer)
    chrt_id: Mapped[int] = mapped_column(Integer)

    price: Mapped[int] = mapped_column(Integer)
    discounted_price: Mapped[float] = mapped_column(Float)
    club_discounted_price: Mapped[float] = mapped_column(Float)

    currency: Mapped[str] = mapped_column(String(10))

    discount: Mapped[int] = mapped_column(Integer)
    club_discount: Mapped[int] = mapped_column(Integer)

    tech_size_name: Mapped[str] = mapped_column(String(50))

    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    raw_data: Mapped[dict] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint("cabinet_id", "chrt_id", name="uq_price"),
    )


class SalesReport(Base):
    __tablename__ = "sales_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cabinet_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    # Идентификаторы
    rrd_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    realizationreport_id: Mapped[int] = mapped_column(BigInteger, nullable=True, index=True)
    gi_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    nm_id: Mapped[int] = mapped_column(Integer, nullable=True, index=True)
    shk_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    assembly_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    srid: Mapped[str] = mapped_column(String(100), nullable=True, index=True)
    order_uid: Mapped[str] = mapped_column(String(100), nullable=True)

    # Период отчёта
    date_from: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    date_to: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    create_dt: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    rr_dt: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    order_dt: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    sale_dt: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    # Товар
    subject_name: Mapped[str] = mapped_column(String(200), nullable=True)
    brand_name: Mapped[str] = mapped_column(String(200), nullable=True)
    sa_name: Mapped[str] = mapped_column(String(200), nullable=True)
    ts_name: Mapped[str] = mapped_column(String(50), nullable=True)
    barcode: Mapped[str] = mapped_column(String(50), nullable=True)

    # Операция
    doc_type_name: Mapped[str] = mapped_column(String(100), nullable=True)
    supplier_oper_name: Mapped[str] = mapped_column(String(200), nullable=True)
    office_name: Mapped[str] = mapped_column(String(200), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=True)
    currency_name: Mapped[str] = mapped_column(String(10), nullable=True)

    # Цены и скидки
    retail_price: Mapped[float] = mapped_column(Float, nullable=True)
    retail_amount: Mapped[float] = mapped_column(Float, nullable=True)
    retail_price_withdisc_rub: Mapped[float] = mapped_column(Float, nullable=True)
    sale_percent: Mapped[int] = mapped_column(Integer, nullable=True)
    commission_percent: Mapped[float] = mapped_column(Float, nullable=True)
    product_discount_for_report: Mapped[float] = mapped_column(Float, nullable=True)
    supplier_promo: Mapped[float] = mapped_column(Float, nullable=True)
    ppvz_spp_prc: Mapped[float] = mapped_column(Float, nullable=True)

    # Комиссии WB
    ppvz_kvw_prc_base: Mapped[float] = mapped_column(Float, nullable=True)
    ppvz_kvw_prc: Mapped[float] = mapped_column(Float, nullable=True)
    ppvz_sales_commission: Mapped[float] = mapped_column(Float, nullable=True)
    ppvz_for_pay: Mapped[float] = mapped_column(Float, nullable=True)
    ppvz_reward: Mapped[float] = mapped_column(Float, nullable=True)
    ppvz_vw: Mapped[float] = mapped_column(Float, nullable=True)
    ppvz_vw_nds: Mapped[float] = mapped_column(Float, nullable=True)
    sup_rating_prc_up: Mapped[float] = mapped_column(Float, nullable=True)
    is_kgvp_v2: Mapped[float] = mapped_column(Float, nullable=True)

    # Эквайринг
    acquiring_fee: Mapped[float] = mapped_column(Float, nullable=True)
    acquiring_percent: Mapped[float] = mapped_column(Float, nullable=True)
    acquiring_bank: Mapped[str] = mapped_column(String(200), nullable=True)
    payment_processing: Mapped[str] = mapped_column(String(100), nullable=True)

    # Доставка и логистика
    delivery_amount: Mapped[int] = mapped_column(Integer, nullable=True)
    return_amount: Mapped[int] = mapped_column(Integer, nullable=True)
    delivery_rub: Mapped[float] = mapped_column(Float, nullable=True)
    gi_box_type_name: Mapped[str] = mapped_column(String(100), nullable=True)
    rebill_logistic_cost: Mapped[float] = mapped_column(Float, nullable=True)
    rebill_logistic_org: Mapped[str] = mapped_column(String(200), nullable=True)
    dlv_prc: Mapped[float] = mapped_column(Float, nullable=True)

    # Финансы
    penalty: Mapped[float] = mapped_column(Float, nullable=True)
    additional_payment: Mapped[float] = mapped_column(Float, nullable=True)
    storage_fee: Mapped[float] = mapped_column(Float, nullable=True)
    deduction: Mapped[float] = mapped_column(Float, nullable=True)
    acceptance: Mapped[float] = mapped_column(Float, nullable=True)

    # Прочее
    site_country: Mapped[str] = mapped_column(String(100), nullable=True)
    ppvz_office_name: Mapped[str] = mapped_column(String(200), nullable=True)
    ppvz_office_id: Mapped[int] = mapped_column(Integer, nullable=True)
    ppvz_supplier_id: Mapped[int] = mapped_column(Integer, nullable=True)
    ppvz_supplier_name: Mapped[str] = mapped_column(String(200), nullable=True)
    ppvz_inn: Mapped[str] = mapped_column(String(20), nullable=True)
    sticker_id: Mapped[str] = mapped_column(String(100), nullable=True)
    declaration_number: Mapped[str] = mapped_column(String(100), nullable=True)
    bonus_type_name: Mapped[str] = mapped_column(String(200), nullable=True)
    kiz: Mapped[str] = mapped_column(String(200), nullable=True)
    srv_dbs: Mapped[bool] = mapped_column(Boolean, nullable=True)
    is_legal_entity: Mapped[bool] = mapped_column(Boolean, nullable=True)
    report_type: Mapped[int] = mapped_column(Integer, nullable=True)
    fix_tariff_date_from: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    fix_tariff_date_to: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    raw_data: Mapped[dict] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint("cabinet_id", "rrd_id", name="uq_sales_report_row"),
    )


class Sale(Base):
    __tablename__ = "sales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    cabinet_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    srid: Mapped[str] = mapped_column(String(100), nullable=True, index=True)
    sale_id: Mapped[str] = mapped_column(String(50), nullable=True, index=True)  # saleID, напр. S9993700024
    g_number: Mapped[str] = mapped_column(String(50), nullable=True, index=True)
    nm_id: Mapped[int] = mapped_column(Integer, nullable=True, index=True)
    supplier_article: Mapped[str] = mapped_column(String(75), nullable=True)
    barcode: Mapped[str] = mapped_column(String(30), nullable=True)

    date: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    last_change_date: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    total_price: Mapped[float] = mapped_column(Float, nullable=True)
    finished_price: Mapped[float] = mapped_column(Float, nullable=True)
    price_with_disc: Mapped[float] = mapped_column(Float, nullable=True)
    discount_percent: Mapped[int] = mapped_column(Integer, nullable=True)
    spp: Mapped[float] = mapped_column(Float, nullable=True)
    for_pay: Mapped[float] = mapped_column(Float, nullable=True)         # к перечислению продавцу
    payment_sale_amount: Mapped[float] = mapped_column(Float, nullable=True)  # оплата частями

    is_supply: Mapped[bool] = mapped_column(Boolean, default=False)
    is_realization: Mapped[bool] = mapped_column(Boolean, default=False)

    warehouse_name: Mapped[str] = mapped_column(String(100), nullable=True)
    warehouse_type: Mapped[str] = mapped_column(String(50), nullable=True)
    country_name: Mapped[str] = mapped_column(String(200), nullable=True)
    oblast_okrug_name: Mapped[str] = mapped_column(String(200), nullable=True)
    region_name: Mapped[str] = mapped_column(String(200), nullable=True)
    category: Mapped[str] = mapped_column(String(50), nullable=True)
    subject: Mapped[str] = mapped_column(String(50), nullable=True)
    brand: Mapped[str] = mapped_column(String(50), nullable=True)
    tech_size: Mapped[str] = mapped_column(String(30), nullable=True)
    sticker: Mapped[str] = mapped_column(String(50), nullable=True)
    income_id: Mapped[int] = mapped_column(BigInteger, nullable=True)

    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    raw_data: Mapped[dict] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint("cabinet_id", "sale_id", name="uq_cabinet_sale"),
    )


# =====================
# AUTH / TOKEN MANAGEMENT
# =====================


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=True)
    company: Mapped[str] = mapped_column(String(200), nullable=True)
    phone: Mapped[str] = mapped_column(String(50), nullable=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    api_keys: Mapped[list["ApiKey"]] = relationship("ApiKey", back_populates="user", cascade="all, delete-orphan")
    wb_tokens: Mapped[list["WbToken"]] = relationship("WbToken", back_populates="user", cascade="all, delete-orphan")
    cabinet_access: Mapped[list["UserCabinetAccess"]] = relationship("UserCabinetAccess", back_populates="user", cascade="all, delete-orphan")


class UserCabinetAccess(Base):
    __tablename__ = "user_cabinet_access"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    cabinet_id: Mapped[str] = mapped_column(String(32), nullable=False)
    access_all: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship("User", back_populates="cabinet_access")
    __table_args__ = (UniqueConstraint("user_id", "cabinet_id", name="uq_user_cabinet"),)


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_used_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="api_keys")


class WbToken(Base):
    __tablename__ = "wb_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    seller_name: Mapped[str] = mapped_column(String(100), nullable=False)
    token: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="wb_tokens")


# =====================
# ANALYTICS (sales-funnel v3)
# =====================


class ShelfMetric(Base):
    """Витрина продаж: просмотры, конверсия, добавления в корзину, заказы, выкупы."""
    __tablename__ = "shelf_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cabinet_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    nm_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    vendor_code: Mapped[str] = mapped_column(String(200), nullable=True)
    product_name: Mapped[str] = mapped_column(String(500), nullable=True)
    subject_name: Mapped[str] = mapped_column(String(200), nullable=True)
    brand_name: Mapped[str] = mapped_column(String(200), nullable=True)
    product_rating: Mapped[float] = mapped_column(Float, default=0)
    feedback_rating: Mapped[float] = mapped_column(Float, default=0)

    period_start: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    period_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    open_count: Mapped[int] = mapped_column(Integer, default=0)
    cart_count: Mapped[int] = mapped_column(Integer, default=0)
    order_count: Mapped[int] = mapped_column(Integer, default=0)
    order_sum: Mapped[int] = mapped_column(Integer, default=0)
    buyout_count: Mapped[int] = mapped_column(Integer, default=0)
    buyout_sum: Mapped[int] = mapped_column(Integer, default=0)
    cancel_count: Mapped[int] = mapped_column(Integer, default=0)
    cancel_sum: Mapped[int] = mapped_column(Integer, default=0)
    avg_price: Mapped[int] = mapped_column(Integer, default=0)
    avg_orders_per_day: Mapped[float] = mapped_column(Float, default=0)
    share_order_percent: Mapped[float] = mapped_column(Float, default=0)
    add_to_wishlist: Mapped[int] = mapped_column(Integer, default=0)

    conv_add_to_cart: Mapped[int] = mapped_column(Integer, default=0)
    conv_cart_to_order: Mapped[int] = mapped_column(Integer, default=0)
    conv_buyout: Mapped[int] = mapped_column(Integer, default=0)

    stocks_wb: Mapped[int] = mapped_column(Integer, default=0)
    stocks_mp: Mapped[int] = mapped_column(Integer, default=0)

    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    raw_data: Mapped[dict] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint("cabinet_id", "nm_id", "period_start", "period_end", name="uq_shelf_metric"),
    )


class FunnelMetric(Base):
    """Воронка конверсии: сравнение текущего и прошлого периодов, динамика."""
    __tablename__ = "funnel_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cabinet_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    nm_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    vendor_code: Mapped[str] = mapped_column(String(200), nullable=True)
    product_name: Mapped[str] = mapped_column(String(500), nullable=True)
    subject_name: Mapped[str] = mapped_column(String(200), nullable=True)
    brand_name: Mapped[str] = mapped_column(String(200), nullable=True)

    period_start: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    period_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    open_count: Mapped[int] = mapped_column(Integer, default=0)
    cart_count: Mapped[int] = mapped_column(Integer, default=0)
    order_count: Mapped[int] = mapped_column(Integer, default=0)
    order_sum: Mapped[int] = mapped_column(Integer, default=0)
    buyout_count: Mapped[int] = mapped_column(Integer, default=0)
    buyout_sum: Mapped[int] = mapped_column(Integer, default=0)

    conv_add_to_cart: Mapped[int] = mapped_column(Integer, default=0)
    conv_cart_to_order: Mapped[int] = mapped_column(Integer, default=0)
    conv_buyout: Mapped[int] = mapped_column(Integer, default=0)

    past_open_count: Mapped[int] = mapped_column(Integer, default=0)
    past_cart_count: Mapped[int] = mapped_column(Integer, default=0)
    past_order_count: Mapped[int] = mapped_column(Integer, default=0)
    past_order_sum: Mapped[int] = mapped_column(Integer, default=0)
    past_buyout_count: Mapped[int] = mapped_column(Integer, default=0)
    past_conv_buyout: Mapped[int] = mapped_column(Integer, default=0)

    dynamic_open: Mapped[int] = mapped_column(Integer, default=0)
    dynamic_cart: Mapped[int] = mapped_column(Integer, default=0)
    dynamic_order: Mapped[int] = mapped_column(Integer, default=0)
    dynamic_buyout: Mapped[int] = mapped_column(Integer, default=0)

    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    raw_data: Mapped[dict] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint("cabinet_id", "nm_id", "period_start", "period_end", name="uq_funnel_metric"),
    )


class StockByOffice(Base):
    __tablename__ = "stock_by_offices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cabinet_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    region_name: Mapped[str] = mapped_column(String(200), nullable=False)
    office_id: Mapped[int] = mapped_column(Integer, nullable=False)
    office_name: Mapped[str] = mapped_column(String(200), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    period_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    stock_count: Mapped[int] = mapped_column(Integer, default=0)
    stock_sum: Mapped[int] = mapped_column(Integer, default=0)
    sale_rate_days: Mapped[int] = mapped_column(Integer, default=0)
    to_client_count: Mapped[int] = mapped_column(Integer, default=0)
    from_client_count: Mapped[int] = mapped_column(Integer, default=0)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    raw_data: Mapped[dict] = mapped_column(JSON, nullable=True)
    __table_args__ = (UniqueConstraint("cabinet_id", "office_id", "period_start", "period_end", name="uq_stock_office"),)


class ItemRating(Base):
    __tablename__ = "item_ratings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cabinet_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    nm_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    vendor_code: Mapped[str] = mapped_column(String(200), nullable=True)
    product_name: Mapped[str] = mapped_column(String(500), nullable=True)
    subject_name: Mapped[str] = mapped_column(String(200), nullable=True)
    brand_name: Mapped[str] = mapped_column(String(200), nullable=True)
    period_start: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    period_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    seller_rating: Mapped[float] = mapped_column(Float, default=0)
    product_rating: Mapped[float] = mapped_column(Float, default=0)
    feedback_rating: Mapped[float] = mapped_column(Float, default=0)
    feedback_percentile: Mapped[float] = mapped_column(Float, nullable=True, default=0)
    feedback_count: Mapped[int] = mapped_column(Integer, default=0)
    five_star: Mapped[int] = mapped_column(Integer, default=0)
    four_star: Mapped[int] = mapped_column(Integer, default=0)
    three_star: Mapped[int] = mapped_column(Integer, default=0)
    two_star: Mapped[int] = mapped_column(Integer, default=0)
    one_star: Mapped[int] = mapped_column(Integer, default=0)
    disqualified: Mapped[int] = mapped_column(Integer, default=0)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    raw_data: Mapped[dict] = mapped_column(JSON, nullable=True)
    __table_args__ = (UniqueConstraint("cabinet_id", "nm_id", "period_start", "period_end", name="uq_item_rating"),)


# =====================
# ADVERTISING ANALYTICS
# =====================


class AdCampaign(Base):
    __tablename__ = "ad_campaigns"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cabinet_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    advert_id: Mapped[int] = mapped_column(Integer, nullable=False)
    advert_type: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(300), nullable=True)
    bid_type: Mapped[str] = mapped_column(String(50), nullable=True)
    payment_type: Mapped[str] = mapped_column(String(50), nullable=True)
    change_time: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    raw_data: Mapped[dict] = mapped_column(JSON, nullable=True)
    __table_args__ = (UniqueConstraint("cabinet_id", "advert_id", name="uq_ad_campaign"),)


class AdCampaignStats(Base):
    __tablename__ = "ad_campaign_stats"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cabinet_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    advert_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    date: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    views: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    ctr: Mapped[float] = mapped_column(Float, default=0)
    cpc: Mapped[float] = mapped_column(Float, default=0)
    cr: Mapped[float] = mapped_column(Float, default=0)
    atbs: Mapped[int] = mapped_column(Integer, default=0)
    orders: Mapped[int] = mapped_column(Integer, default=0)
    shks: Mapped[int] = mapped_column(Integer, default=0)
    canceled: Mapped[int] = mapped_column(Integer, default=0)
    spend: Mapped[float] = mapped_column(Float, default=0)
    sum_price: Mapped[float] = mapped_column(Float, default=0)
    avg_position: Mapped[float] = mapped_column(Float, nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    raw_data: Mapped[dict] = mapped_column(JSON, nullable=True)
    __table_args__ = (UniqueConstraint("cabinet_id", "advert_id", "date", name="uq_ad_stats"),)


class AdExpense(Base):
    __tablename__ = "ad_expenses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cabinet_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    advert_id: Mapped[int] = mapped_column(Integer, nullable=False)
    camp_name: Mapped[str] = mapped_column(String(300), nullable=True)
    advert_type: Mapped[int] = mapped_column(Integer, default=0)
    advert_status: Mapped[int] = mapped_column(Integer, default=0)
    payment_type: Mapped[str] = mapped_column(String(50), nullable=True)
    upd_time: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    upd_sum: Mapped[int] = mapped_column(Integer, default=0)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    raw_data: Mapped[dict] = mapped_column(JSON, nullable=True)
    __table_args__ = (UniqueConstraint("cabinet_id", "advert_id", "upd_time", name="uq_ad_expense"),)


class AdSearchCluster(Base):
    """Поисковые кластеры рекламных кампаний."""
    __tablename__ = "ad_search_clusters"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cabinet_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    advert_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    nm_id: Mapped[int] = mapped_column(Integer, nullable=True)
    keyword: Mapped[str] = mapped_column(String(500), nullable=False)
    cluster_id: Mapped[int] = mapped_column(Integer, nullable=True)
    bids: Mapped[int] = mapped_column(Integer, default=0)
    views: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    ctr: Mapped[float] = mapped_column(Float, default=0)
    cpc: Mapped[float] = mapped_column(Float, default=0)
    cpm: Mapped[float] = mapped_column(Float, default=0)
    avg_pos: Mapped[float] = mapped_column(Float, default=0)
    atbs: Mapped[int] = mapped_column(Integer, default=0)
    shks: Mapped[int] = mapped_column(Integer, default=0)
    sum_price: Mapped[float] = mapped_column(Float, default=0)
    orders: Mapped[int] = mapped_column(Integer, default=0)
    spend: Mapped[float] = mapped_column(Float, default=0)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    raw_data: Mapped[dict] = mapped_column(JSON, nullable=True)
    __table_args__ = (UniqueConstraint("cabinet_id", "advert_id", "nm_id", "keyword", name="uq_ad_search_cluster"),)


# =====================
# РНП — Настройки кабинета
# =====================


class RnpSetting(Base):
    """Настройки кабинета для расчёта РНП: себестоимость, статьи расходов, налоги."""
    __tablename__ = "rnp_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cabinet_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    usn_rate: Mapped[float] = mapped_column(Float, default=0.06)
    usn_rate_2025: Mapped[float] = mapped_column(Float, default=0.06)
    nds_rate: Mapped[float] = mapped_column(Float, default=0.07)
    nds_rate_2025: Mapped[float] = mapped_column(Float, default=0.07)
    usd_rate: Mapped[float] = mapped_column(Float, default=0.0)
    cny_rate: Mapped[float] = mapped_column(Float, default=0.0)
    paid_acceptance_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    localization_index: Mapped[float] = mapped_column(Float, default=1.0)

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("cabinet_id", name="uq_rnp_settings_cabinet"),)


class RnpCost(Base):
    """Себестоимость/закупочная цена по артикулам для кабинета."""
    __tablename__ = "rnp_costs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cabinet_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    supplier_article: Mapped[str] = mapped_column(String(200), nullable=False)
    cost_rub: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(10), default="RUB")
    manager: Mapped[str] = mapped_column(String(100), nullable=True)
    product_type: Mapped[str] = mapped_column(String(100), nullable=True)
    shipment_type: Mapped[str] = mapped_column(String(100), nullable=True)
    min_price: Mapped[float] = mapped_column(Float, nullable=True)
    min_margin: Mapped[float] = mapped_column(Float, nullable=True)
    target_margin: Mapped[float] = mapped_column(Float, nullable=True)
    target_drr: Mapped[float] = mapped_column(Float, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("cabinet_id", "supplier_article", name="uq_rnp_cost"),)


class RnpFixedExpense(Base):
    """Постоянные расходы продавца (₽/мес)."""
    __tablename__ = "rnp_fixed_expenses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cabinet_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    amount_monthly: Mapped[float] = mapped_column(Float, default=0.0)

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("cabinet_id", "name", name="uq_rnp_fixed_expense"),)


class RnpVariableExpense(Base):
    """Переменные расходы продавца (% от статьи WB)."""
    __tablename__ = "rnp_variable_expenses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cabinet_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_article: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    percent: Mapped[float] = mapped_column(Float, default=0.0)

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("cabinet_id", "name", name="uq_rnp_variable_expense"),)


class RnpLoanPayment(Base):
    """Возврат процентов по займам."""
    __tablename__ = "rnp_loan_payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cabinet_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    amount_monthly: Mapped[float] = mapped_column(Float, default=0.0)

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("cabinet_id", "name", name="uq_rnp_loan_payment"),)


# =====================
# РНП — Планы
# =====================


class RnpPlan(Base):
    """Месячные планы для кабинета."""
    __tablename__ = "rnp_plans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cabinet_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    month: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    orders_amount: Mapped[float] = mapped_column(Float, default=0.0)
    orders_count: Mapped[int] = mapped_column(Integer, default=0)
    sales_minus_returns: Mapped[float] = mapped_column(Float, default=0.0)
    sales_count: Mapped[int] = mapped_column(Integer, default=0)
    returns_count: Mapped[int] = mapped_column(Integer, default=0)
    margin_rub: Mapped[float] = mapped_column(Float, default=0.0)
    margin_percent: Mapped[float] = mapped_column(Float, default=0.0)
    drr: Mapped[float] = mapped_column(Float, default=0.0)
    avg_price: Mapped[float] = mapped_column(Float, default=0.0)
    cost_of_goods: Mapped[float] = mapped_column(Float, default=0.0)
    logistics: Mapped[float] = mapped_column(Float, default=0.0)
    commission: Mapped[float] = mapped_column(Float, default=0.0)
    storage: Mapped[float] = mapped_column(Float, default=0.0)
    paid_acceptance: Mapped[float] = mapped_column(Float, default=0.0)
    promotion: Mapped[float] = mapped_column(Float, default=0.0)
    penalties: Mapped[float] = mapped_column(Float, default=0.0)
    nds: Mapped[float] = mapped_column(Float, default=0.0)
    profit: Mapped[float] = mapped_column(Float, default=0.0)
    spp: Mapped[float] = mapped_column(Float, default=0.0)

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("cabinet_id", "month", name="uq_rnp_plan"),)