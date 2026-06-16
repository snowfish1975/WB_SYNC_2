from datetime import datetime
from pydantic import BaseModel


class ProductCharacteristicOut(BaseModel):
    id: int
    nm_id: int
    characteristics: dict
    synced_at: datetime
    seller_name: str  # ✅ новое поле

    model_config = {"from_attributes": True}


class SyncLogOut(BaseModel):
    id: int
    status: str
    message: str | None
    records_saved: int
    created_at: datetime
    seller_name: str  # ✅ новое поле

    model_config = {"from_attributes": True}


class TokenRequest(BaseModel):
    token: str


# =====================
# USER SCHEMAS
# =====================

class UserCreate(BaseModel):
    username: str
    email: str | None = None
    password: str | None = None


class UserUpdate(BaseModel):
    username: str | None = None
    email: str | None = None
    is_active: bool | None = None


class UserOut(BaseModel):
    id: int
    username: str
    email: str | None = None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# =====================
# API KEY SCHEMAS
# =====================

class ApiKeyCreate(BaseModel):
    name: str | None = None
    expires_at: datetime | None = None


class ApiKeyOut(BaseModel):
    id: int
    user_id: int
    name: str | None = None
    key_hash: str
    expires_at: datetime | None = None
    created_at: datetime
    last_used_at: datetime | None = None

    model_config = {"from_attributes": True}


class ApiKeyCreatedResponse(BaseModel):
    id: int
    name: str | None = None
    api_key: str  # отображается только один раз!
    expires_at: datetime | None = None
    created_at: datetime


# =====================
# WB TOKEN SCHEMAS
# =====================

class WbTokenCreate(BaseModel):
    seller_name: str
    token: str


class WbTokenUpdate(BaseModel):
    seller_name: str | None = None
    is_active: bool | None = None


class WbTokenOut(BaseModel):
    id: int
    user_id: int
    seller_name: str
    token_hash: str
    is_active: bool
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class StockOut(BaseModel):
    id: int
    nm_id: int
    chrt_id: int
    warehouse_id: int
    warehouse_name: str
    region_name: str
    quantity: int
    in_way_to_client: int
    in_way_from_client: int
    synced_at: datetime
    seller_name: str
    raw_data: dict | None = None

    model_config = {"from_attributes": True}


class OrderOut(BaseModel):
    id: int
    cabinet_id: str
    seller_name: str | None = None
    srid: str | None = None
    g_number: str | None = None
    nm_id: int | None = None
    supplier_article: str | None = None
    barcode: str | None = None
    date: datetime | None = None
    last_change_date: datetime | None = None
    cancel_date: datetime | None = None
    total_price: float | None = None
    finished_price: float | None = None
    price_with_disc: float | None = None
    discount_percent: int | None = None
    spp: float | None = None
    is_cancel: bool = False
    is_supply: bool = False
    is_realization: bool = False
    warehouse_name: str | None = None
    warehouse_type: str | None = None
    country_name: str | None = None
    region_name: str | None = None
    category: str | None = None
    subject: str | None = None
    brand: str | None = None
    tech_size: str | None = None
    sticker: str | None = None
    income_id: int | None = None
    synced_at: datetime
    raw_data: dict | None = None

    model_config = {"from_attributes": True}


# =====================
# РНП SCHEMAS
# =====================


class RnpSettingsUpdate(BaseModel):
    usn_rate: float | None = None
    usn_rate_2025: float | None = None
    nds_rate: float | None = None
    nds_rate_2025: float | None = None
    usd_rate: float | None = None
    cny_rate: float | None = None
    paid_acceptance_enabled: bool | None = None
    localization_index: float | None = None


class RnpCostIn(BaseModel):
    supplier_article: str
    cost_rub: float = 0
    currency: str = "RUB"
    manager: str | None = None
    product_type: str | None = None
    shipment_type: str | None = None
    min_price: float | None = None
    min_margin: float | None = None
    target_margin: float | None = None
    target_drr: float | None = None


class RnpFixedExpenseIn(BaseModel):
    name: str
    amount_monthly: float = 0


class RnpVariableExpenseIn(BaseModel):
    source_article: str
    name: str
    percent: float = 0


class RnpLoanPaymentIn(BaseModel):
    name: str
    amount_monthly: float = 0


class RnpPlanIn(BaseModel):
    month: str
    orders_amount: float = 0
    orders_count: int = 0
    sales_minus_returns: float = 0
    sales_count: int = 0
    returns_count: int = 0
    margin_rub: float = 0
    margin_percent: float = 0
    drr: float = 0
    avg_price: float = 0
    cost_of_goods: float = 0
    logistics: float = 0
    commission: float = 0
    storage: float = 0
    paid_acceptance: float = 0
    promotion: float = 0
    penalties: float = 0
    nds: float = 0
    profit: float = 0
    spp: float = 0


class PriceOut(BaseModel):
    id: int
    nm_id: int
    chrt_id: int
    price: int
    discounted_price: float
    club_discounted_price: float
    currency: str
    discount: int
    club_discount: int
    tech_size_name: str
    synced_at: datetime
    seller_name: str
    raw_data: dict | None = None

    model_config = {"from_attributes": True}


class SalesReportRowOut(BaseModel):
    id: int
    cabinet_id: str
    seller_name: str | None = None
    rrd_id: int | None = None
    realizationreport_id: int | None = None
    nm_id: int | None = None
    srid: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    rr_dt: datetime | None = None
    order_dt: datetime | None = None
    sale_dt: datetime | None = None
    subject_name: str | None = None
    brand_name: str | None = None
    sa_name: str | None = None
    ts_name: str | None = None
    barcode: str | None = None
    doc_type_name: str | None = None
    supplier_oper_name: str | None = None
    office_name: str | None = None
    quantity: int | None = None
    retail_price: float | None = None
    retail_amount: float | None = None
    retail_price_withdisc_rub: float | None = None
    sale_percent: int | None = None
    commission_percent: float | None = None
    ppvz_for_pay: float | None = None
    ppvz_sales_commission: float | None = None
    ppvz_vw: float | None = None
    ppvz_vw_nds: float | None = None
    delivery_rub: float | None = None
    penalty: float | None = None
    additional_payment: float | None = None
    storage_fee: float | None = None
    deduction: float | None = None
    acceptance: float | None = None
    acquiring_fee: float | None = None
    currency_name: str | None = None
    site_country: str | None = None
    synced_at: datetime
    raw_data: dict | None = None

    model_config = {"from_attributes": True}


class SaleOut(BaseModel):
    id: int
    cabinet_id: str
    seller_name: str | None = None
    srid: str | None = None
    sale_id: str | None = None
    g_number: str | None = None
    nm_id: int | None = None
    supplier_article: str | None = None
    barcode: str | None = None
    date: datetime | None = None
    last_change_date: datetime | None = None
    total_price: float | None = None
    finished_price: float | None = None
    price_with_disc: float | None = None
    discount_percent: int | None = None
    spp: float | None = None
    for_pay: float | None = None
    payment_sale_amount: float | None = None
    is_supply: bool = False
    is_realization: bool = False
    warehouse_name: str | None = None
    warehouse_type: str | None = None
    country_name: str | None = None
    oblast_okrug_name: str | None = None
    region_name: str | None = None
    category: str | None = None
    subject: str | None = None
    brand: str | None = None
    tech_size: str | None = None
    sticker: str | None = None
    income_id: int | None = None
    synced_at: datetime
    raw_data: dict | None = None

    model_config = {"from_attributes": True}