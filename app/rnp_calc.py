"""
Расчёт отчёта «Рука на пульсе» (РНП).

Логика основана на GAS-коде из Google Sheets:
- calcEFODay — ежедневные финансовые показатели (ЕФО)
- Агрегация заказов/продаж по дням
- P&L: валовая маржа → операционные расходы → чистая прибыль
- Относительные метрики
"""

from datetime import datetime, timedelta
from calendar import monthrange
from sqlalchemy.orm import Session
from sqlalchemy import func, case, and_, extract

from app.models import (
    Order, Sale, SalesReport, AdCampaignStats,
    RnpSetting, RnpCost, RnpFixedExpense, RnpVariableExpense, RnpLoanPayment, RnpPlan,
)


def _get_rnp_settings(db: Session, cabinet_id: str) -> dict:
    row = db.query(RnpSetting).filter(RnpSetting.cabinet_id == cabinet_id).first()
    if row:
        return {
            "usn_rate": row.usn_rate,
            "usn_rate_2025": row.usn_rate_2025,
            "nds_rate": row.nds_rate,
            "nds_rate_2025": row.nds_rate_2025,
            "usd_rate": row.usd_rate,
            "cny_rate": row.cny_rate,
            "paid_acceptance_enabled": row.paid_acceptance_enabled,
            "localization_index": row.localization_index,
        }
    return {"usn_rate": 0.06, "usn_rate_2025": 0.06, "nds_rate": 0.07, "nds_rate_2025": 0.07,
            "usd_rate": 0, "cny_rate": 0, "paid_acceptance_enabled": True, "localization_index": 1}


def _get_cost_map(db: Session, cabinet_id: str) -> dict[str, float]:
    rows = db.query(RnpCost).filter(RnpCost.cabinet_id == cabinet_id).all()
    return {r.supplier_article.upper(): r.cost_rub for r in rows}


def _calc_usn(settings: dict, sale_amount: float, year: int) -> float:
    rate = settings["usn_rate_2025"] if year == 2025 else settings["usn_rate"]
    return sale_amount * rate


def _calc_nds(settings: dict, sale_amount: float, year: int) -> float:
    rate = settings["nds_rate_2025"] if year == 2025 else settings["nds_rate"]
    return sale_amount * rate


def calc_rnp(db: Session, cabinet_id: str, days_back: int = 40) -> dict:
    """
    Рассчитывает полный отчёт РНП.

    Возвращает dict с секциями:
    - daily: дневные данные (40 дней)
    - summary: итоговые метрики за период
    - forecast_block: блок «Прогноз» (на основе заказов)
    - fact_block: блок «Факт» (на основе ЕФО/продаж)
    - pnl: P&L
    - relative_metrics: относительные метрики
    """

    settings = _get_rnp_settings(db, cabinet_id)
    cost_map = _get_cost_map(db, cabinet_id)

    today = datetime.utcnow().date()
    date_end = today - timedelta(days=1)
    date_start = date_end - timedelta(days=days_back - 1)

    # =============================
    # 1. ЕЖЕДНЕВНЫЕ ДАННЫЕ (40 дней)
    # =============================
    daily = []

    for day_offset in range(days_back):
        d = date_start + timedelta(days=day_offset)
        day_dt = datetime(d.year, d.month, d.day)
        day_dt_end = day_dt + timedelta(days=1)

        # --- ЗАКАЗЫ за день ---
        orders_q = db.query(Order).filter(
            Order.cabinet_id == cabinet_id,
            Order.date >= day_dt,
            Order.date < day_dt_end,
        )
        orders_data = orders_q.all()

        order_sum_before_spp = sum(o.total_price or 0 for o in orders_data)
        order_sum_with_spp = sum(o.finished_price or 0 for o in orders_data)
        order_count = len([o for o in orders_data if not o.is_cancel])
        order_cancel_count = len([o for o in orders_data if o.is_cancel])

        spp_pct = 0
        if order_sum_before_spp > 0:
            spp_pct = (order_sum_before_spp - order_sum_with_spp) / order_sum_before_spp

        avg_check_orders = order_sum_before_spp / order_count if order_count > 0 else 0

        # --- ПРОДАЖИ (ЕФО) за день ---
        efo_rows = db.query(SalesReport).filter(
            SalesReport.cabinet_id == cabinet_id,
            SalesReport.sale_dt >= day_dt,
            SalesReport.sale_dt < day_dt_end,
        ).all()

        sales_amount = 0
        sales_count = 0
        return_amount = 0
        return_count = 0
        wb_sales_amount = 0
        pay_sales_amount = 0
        delivery_amount = 0
        storage_amount = 0
        accept_amount = 0
        promote_amount = 0
        penalty_amount = 0
        add_pay_amount = 0
        other_amount = 0
        goods_delta = {}

        for row in efo_rows:
            op = (row.supplier_oper_name or "").strip()
            art = (row.sa_name or "").upper()
            qty = row.quantity or 0

            if op == "Продажа":
                sales_amount += row.retail_price_withdisc_rub or 0
                sales_count += qty
                wb_sales_amount += row.retail_amount or 0
                pay_sales_amount += row.ppvz_for_pay or 0
                goods_delta[art] = goods_delta.get(art, 0) + qty

            if op == "Возврат":
                return_amount += row.retail_price_withdisc_rub or 0
                return_count += qty
                pay_sales_amount -= row.ppvz_for_pay or 0
                goods_delta[art] = goods_delta.get(art, 0) - qty

            delivery_amount += row.delivery_rub or 0
            storage_amount += row.storage_fee or 0
            accept_amount += row.acceptance or 0
            penalty_amount += row.penalty or 0
            add_pay_amount += row.additional_payment or 0

            bonus = (row.bonus_type_name or "")
            if "WB Продвижение" in bonus or "ВБ.Продвижение" in bonus:
                promote_amount += row.deduction or 0

            other_amount += row.deduction or 0

        other_amount -= promote_amount

        # Комиссия WB: используем ppvz_sales_commission из SalesReport (фактическая комиссия)
        # Альтернатива (GAS): wb_sales_amount - pay_sales_amount, но в данных ppvz_for_pay может включать компенсации
        total_sales_commission = sum((row.ppvz_sales_commission or 0) for row in efo_rows)
        commission_fact = abs(total_sales_commission) if total_sales_commission != 0 else (wb_sales_amount - pay_sales_amount if wb_sales_amount > 0 else 0)

        # Себестоимость
        total_cost = 0
        for art, qty in goods_delta.items():
            if art in cost_map and qty > 0:
                total_cost += qty * cost_map[art]

        # Средний чек продажи
        avg_check_sales = sales_amount / sales_count if sales_count > 0 else 0

        # % выкупа
        buyout_pct = sales_count / (sales_count + return_count) if (sales_count + return_count) > 0 else 0

        # Отказы (из orders cancelled)
        refusal_count = order_cancel_count

        # СПП продажи
        spp_sales = (sales_amount - wb_sales_amount) / sales_amount if sales_amount > 0 else 0

        # К перечислению продавцу (из ЕФО)
        to_supplier = pay_sales_amount

        # К перечислению на РС
        to_rs = sales_amount + return_amount + delivery_amount + commission_fact + storage_amount + accept_amount + promote_amount + penalty_amount

        # --- РЕКЛАМНЫЙ БЮДЖЕТ за день ---
        ad_spend = 0
        ad_rows = db.query(AdCampaignStats).filter(
            AdCampaignStats.cabinet_id == cabinet_id,
            AdCampaignStats.date == day_dt,
        ).all()
        for ar in ad_rows:
            ad_spend += ar.spend or 0

        drr = ad_spend / order_sum_before_spp if order_sum_before_spp > 0 else 0

        # --- НАЛОГИ ---
        year = d.year
        usn = _calc_usn(settings, sales_amount + return_amount, year)
        nds = _calc_nds(settings, sales_amount + return_amount, year)

        daily.append({
            "date": d.isoformat(),
            # Заказы (прогноз)
            "order_sum": round(order_sum_before_spp),
            "order_sum_spp": round(order_sum_with_spp),
            "order_count": order_count,
            "order_cancel": order_cancel_count,
            "spp_pct": round(spp_pct * 100, 1),
            "avg_check_orders": round(avg_check_orders),
            "ad_spend": round(ad_spend),
            "drr": round(drr * 100, 2),
            # Продажи (факт из ЕФО)
            "sales_amount": round(sales_amount),
            "sales_count": sales_count,
            "return_amount": round(return_amount),
            "return_count": return_count,
            "avg_check_sales": round(avg_check_sales),
            "buyout_pct": round(buyout_pct * 100, 1),
            "refusal_count": refusal_count,
            "spp_sales": round(spp_sales * 100, 1),
            # WB расходы (факт)
            "delivery": round(delivery_amount),
            "commission": round(commission_fact),
            "storage": round(storage_amount),
            "acceptance": round(accept_amount),
            "promotion": round(promote_amount),
            "penalties": round(penalty_amount),
            "add_payments": round(add_pay_amount),
            "other_deductions": round(other_amount),
            # Финансы
            "to_supplier": round(to_supplier),
            "to_rs": round(to_rs),
            "cost_of_goods": round(total_cost),
            # Налоги
            "usn": round(usn),
            "nds": round(nds),
        })

    # =============================
    # 2. ИТОГИ ЗА ПЕРИОД (40 дней)
    # =============================
    total_orders_amount = sum(d["order_sum"] for d in daily)
    total_orders_count = sum(d["order_count"] for d in daily)
    total_sales_amount = sum(d["sales_amount"] for d in daily)
    total_sales_count = sum(d["sales_count"] for d in daily)
    total_return_amount = sum(d["return_amount"] for d in daily)
    total_return_count = sum(d["return_count"] for d in daily)
    total_ad_spend = sum(d["ad_spend"] for d in daily)
    total_delivery = sum(d["delivery"] for d in daily)
    total_commission = sum(d["commission"] for d in daily)
    total_storage = sum(d["storage"] for d in daily)
    total_acceptance = sum(d["acceptance"] for d in daily)
    total_promotion = sum(d["promotion"] for d in daily)
    total_penalties = sum(d["penalties"] for d in daily)
    total_to_supplier = sum(d["to_supplier"] for d in daily)
    total_to_rs = sum(d["to_rs"] for d in daily)
    total_cost = sum(d["cost_of_goods"] for d in daily)
    total_usn = sum(d["usn"] for d in daily)
    total_nds = sum(d["nds"] for d in daily)
    total_refusals = sum(d["refusal_count"] for d in daily)

    avg_check_sales = total_sales_amount / total_sales_count if total_sales_count > 0 else 0
    avg_check_orders = total_orders_amount / total_orders_count if total_orders_count > 0 else 0
    spp_pct = (total_orders_amount - sum(d["order_sum_spp"] for d in daily)) / total_orders_amount * 100 if total_orders_amount > 0 else 0
    drr = total_ad_spend / total_orders_amount * 100 if total_orders_amount > 0 else 0
    buyout_pct = total_sales_count / (total_sales_count + total_return_count) * 100 if (total_sales_count + total_return_count) > 0 else 0
    spp_sales = (total_sales_amount - sum(d.get("sales_amount", 0) for d in daily)) / total_sales_amount * 100 if total_sales_amount > 0 else 0

    # =============================
    # 3. БЛОКИ ОТЧЁТА
    # =============================

    # WB расходы (прогноз) — суммы из ЕФО
    wb_expenses_forecast = {
        "delivery": total_delivery,
        "commission": total_commission,
        "storage": total_storage,
        "acceptance": total_acceptance,
        "promotion": total_promotion,
        "penalties": total_penalties,
    }
    wb_expenses_total = sum(wb_expenses_forecast.values())

    # Постоянные расходы
    fixed_expenses = db.query(RnpFixedExpense).filter(RnpFixedExpense.cabinet_id == cabinet_id).all()
    total_fixed = sum(f.amount_monthly for f in fixed_expenses)
    fixed_items = [{"name": f.name, "amount": f.amount_monthly} for f in fixed_expenses]

    # Переменные расходы (% от статей)
    var_expenses = db.query(RnpVariableExpense).filter(RnpVariableExpense.cabinet_id == cabinet_id).all()
    variable_items = []
    for v in var_expenses:
        # Находим сумму по source_article в daily
        # Пока placeholder — нужно определить откуда брать source amounts
        variable_items.append({"name": v.name, "source_article": v.source_article, "percent": v.percent, "amount": 0})

    # Займы
    loans = db.query(RnpLoanPayment).filter(RnpLoanPayment.cabinet_id == cabinet_id).all()
    total_loans = sum(l.amount_monthly for l in loans)
    loan_items = [{"name": l.name, "amount": l.amount_monthly} for l in loans]

    # Валовая маржа (прогноз) = Прогноз выкупа + WB расходы + Себестоимость
    gross_margin_forecast = total_sales_amount - wb_expenses_total - total_cost

    # Операционные расходы
    operating_expenses = total_fixed + total_loans

    # Операционная прибыль (EBITDA)
    ebitda = gross_margin_forecast - operating_expenses

    # Налоги
    total_taxes = total_usn + total_nds + total_loans

    # Чистая прибыль
    net_profit = ebitda - total_taxes

    # Рентабельность
    profitability = net_profit / total_sales_amount * 100 if total_sales_amount > 0 else 0

    # =============================
    # 4. ОТНОСИТЕЛЬНЫЕ МЕТРИКИ
    # =============================
    effective_units = total_sales_count - total_return_count if (total_sales_count - total_return_count) > 0 else 1
    total_sales_with_returns = total_sales_amount + total_return_amount if (total_sales_amount + total_return_amount) > 0 else 1

    relative = {
        "markup": total_sales_amount / total_cost * -1 if total_cost < 0 else 0,
        "logistics_per_unit": total_delivery / effective_units * -1 if total_delivery > 0 else 0,
        "cost_per_unit": total_cost / effective_units * -1 if total_cost > 0 else 0,
        "promotion_per_unit": total_promotion / effective_units * -1 if total_promotion > 0 else 0,
        "storage_per_unit": total_storage / effective_units * -1 if total_storage > 0 else 0,
        "net_profit_per_unit": net_profit / effective_units if effective_units > 0 else 0,
        "platform_expenses_pct": total_delivery / total_sales_with_returns * -100 if total_sales_with_returns > 0 else 0,
        "commission_pct": total_commission / total_sales_with_returns * -100 if total_sales_with_returns > 0 else 0,
        "logistics_pct": total_delivery / total_sales_with_returns * -100 if total_sales_with_returns > 0 else 0,
        "promotion_pct": total_promotion / total_sales_with_returns * -100 if total_sales_with_returns > 0 else 0,
        "storage_pct": total_storage / total_sales_with_returns * -100 if total_sales_with_returns > 0 else 0,
        "acceptance_pct": total_acceptance / total_sales_with_returns * -100 if total_sales_with_returns > 0 else 0,
        "cost_pct": total_cost / total_sales_with_returns * -100 if total_sales_with_returns > 0 else 0,
        "taxes_pct": total_taxes / total_sales_with_returns * -100 if total_sales_with_returns > 0 else 0,
    }

    # =============================
    # 5. ПЛАНЫ (для сравнения)
    # =============================
    plans_data = []
    for p in db.query(RnpPlan).filter(RnpPlan.cabinet_id == cabinet_id).order_by(RnpPlan.month).all():
        plans_data.append({
            "month": p.month.isoformat(),
            "orders_amount": p.orders_amount,
            "orders_count": p.orders_count,
            "sales_minus_returns": p.sales_minus_returns,
            "sales_count": p.sales_count,
            "returns_count": p.returns_count,
            "margin_rub": p.margin_rub,
            "margin_percent": p.margin_percent,
            "drr": p.drr,
            "avg_price": p.avg_price,
            "cost_of_goods": p.cost_of_goods,
            "logistics": p.logistics,
            "commission": p.commission,
            "storage": p.storage,
            "paid_acceptance": p.paid_acceptance,
            "promotion": p.promotion,
            "penalties": p.penalties,
            "nds": p.nds,
            "profit": p.profit,
            "spp": p.spp,
        })

    return {
        "cabinet_id": cabinet_id,
        "period": {"start": date_start.isoformat(), "end": date_end.isoformat(), "days": days_back},
        "daily": daily,
        "totals": {
            "orders_amount": total_orders_amount,
            "orders_count": total_orders_count,
            "avg_check_orders": round(avg_check_orders),
            "spp_pct": round(spp_pct, 1),
            "ad_spend": total_ad_spend,
            "drr": round(drr, 2),
            "sales_amount": total_sales_amount,
            "sales_count": total_sales_count,
            "return_amount": total_return_amount,
            "return_count": total_return_count,
            "refusal_count": total_refusals,
            "avg_check_sales": round(avg_check_sales),
            "buyout_pct": round(buyout_pct, 1),
            "spp_sales": round(spp_sales, 1),
            "to_supplier": total_to_supplier,
            "cost_of_goods": total_cost,
        },
        "wb_expenses": wb_expenses_forecast,
        "wb_expenses_total": wb_expenses_total,
        "operating_expenses": operating_expenses,
        "fixed_expenses": fixed_items,
        "variable_expenses": variable_items,
        "loan_payments": loan_items,
        "total_loans": total_loans,
        "gross_margin": gross_margin_forecast,
        "ebitda": ebitda,
        "taxes": {"usn": total_usn, "nds": total_nds, "total": total_taxes},
        "net_profit": net_profit,
        "profitability": round(profitability, 1),
        "relative_metrics": {k: round(v, 2) for k, v in relative.items()},
        "plans": plans_data,
        "settings": settings,
    }
