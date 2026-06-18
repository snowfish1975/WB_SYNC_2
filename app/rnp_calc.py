"""
Расчёт отчёта «Рука на пульсе» (РНП) v2 — оптимизированный.
"""

from datetime import datetime, timedelta, date
from calendar import monthrange
from collections import defaultdict
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from app.models import (
    Order, Sale, SalesReport, AdCampaignStats, ShelfMetric,
    RnpSetting, RnpCost, RnpFixedExpense, RnpVariableExpense, RnpLoanPayment, RnpPlan,
)


def _get_rnp_settings(db: Session, cabinet_id: str) -> dict:
    row = db.query(RnpSetting).filter(RnpSetting.cabinet_id == cabinet_id).first()
    if row:
        return {
            "usn_rate": row.usn_rate, "usn_rate_2025": row.usn_rate_2025,
            "nds_rate": row.nds_rate, "nds_rate_2025": row.nds_rate_2025,
            "usd_rate": row.usd_rate, "cny_rate": row.cny_rate,
            "paid_acceptance_enabled": row.paid_acceptance_enabled,
            "localization_index": row.localization_index,
        }
    return {"usn_rate": 0.06, "usn_rate_2025": 0.06, "nds_rate": 0.07, "nds_rate_2025": 0.07,
            "usd_rate": 0, "cny_rate": 0, "paid_acceptance_enabled": True, "localization_index": 1}


def _get_cost_map(db: Session, cabinet_id: str) -> dict[str, float]:
    rows = db.query(RnpCost).filter(RnpCost.cabinet_id == cabinet_id).all()
    return {r.supplier_article.upper(): r.cost_rub for r in rows}


def _fetch_orders_batch(db: Session, cabinet_id: str, start: date, end: date) -> dict[date, list]:
    dt_start = datetime(start.year, start.month, start.day)
    dt_end = datetime(end.year, end.month, end.day) + timedelta(days=1)
    rows = db.query(Order).filter(
        Order.cabinet_id == cabinet_id,
        Order.date >= dt_start, Order.date < dt_end,
    ).all()
    by_day = defaultdict(list)
    for o in rows:
        by_day[o.date.date() if isinstance(o.date, datetime) else o.date].append(o)
    return dict(by_day)


def _fetch_efo_batch(db: Session, cabinet_id: str, start: date, end: date) -> dict[date, list]:
    dt_start = datetime(start.year, start.month, start.day)
    dt_end = datetime(end.year, end.month, end.day) + timedelta(days=1)
    rows = db.query(SalesReport).filter(
        SalesReport.cabinet_id == cabinet_id,
        SalesReport.sale_dt >= dt_start, SalesReport.sale_dt < dt_end,
    ).all()
    by_day = defaultdict(list)
    for r in rows:
        d = r.sale_dt.date() if isinstance(r.sale_dt, datetime) else r.sale_dt
        if d:
            by_day[d].append(r)
    return dict(by_day)


def _fetch_ad_batch(db: Session, cabinet_id: str, start: date, end: date) -> dict[date, float]:
    dt_start = datetime(start.year, start.month, start.day)
    dt_end = datetime(end.year, end.month, end.day) + timedelta(days=1)
    rows = db.query(AdCampaignStats).filter(
        AdCampaignStats.cabinet_id == cabinet_id,
        AdCampaignStats.date >= dt_start, AdCampaignStats.date < dt_end,
    ).all()
    by_day = defaultdict(float)
    for r in rows:
        d = r.date.date() if isinstance(r.date, datetime) else r.date
        by_day[d] += r.spend or 0

    if not by_day:
        from app.models import AdExpense
        exp_rows = db.query(AdExpense).filter(
            AdExpense.cabinet_id == cabinet_id,
            AdExpense.upd_time >= dt_start, AdExpense.upd_time < dt_end,
        ).all()
        for r in exp_rows:
            d = r.upd_time.date() if isinstance(r.upd_time, datetime) else r.upd_time
            by_day[d] += r.upd_sum or 0

    return dict(by_day)


def _fetch_shelf_orders(db: Session, cabinet_id: str, start: date, end: date) -> dict:
    rows = db.query(ShelfMetric).filter(
        ShelfMetric.cabinet_id == cabinet_id,
        ShelfMetric.period_end >= datetime(start.year, start.month, start.day),
        ShelfMetric.period_start < datetime(end.year, end.month, end.day) + timedelta(days=1),
    ).all()
    return {
        "order_count": sum(r.order_count for r in rows),
        "order_sum": sum(r.order_sum for r in rows),
        "buyout_count": sum(r.buyout_count for r in rows),
        "buyout_sum": sum(r.buyout_sum for r in rows),
        "cancel_count": sum(r.cancel_count for r in rows),
        "cancel_sum": sum(r.cancel_sum for r in rows),
    }


def _calc_day_fast(d: date, orders: list, efo_rows: list, ad_spend: float, settings: dict, cost_map: dict) -> dict:
    order_sum_before_spp = sum(o.price_with_disc or 0 for o in orders)
    order_sum_with_spp = sum(o.finished_price or 0 for o in orders)
    order_count = len([o for o in orders if not o.is_cancel])
    order_cancel_count = len([o for o in orders if o.is_cancel])
    spp_pct = (order_sum_before_spp - order_sum_with_spp) / order_sum_before_spp if order_sum_before_spp > 0 else 0
    avg_check = order_sum_before_spp / order_count if order_count > 0 else 0

    sales_amount = 0; sales_count = 0; return_amount = 0; return_count = 0
    wb_sales = 0; pay_sales = 0; delivery = 0; storage = 0; accept = 0
    promote = 0; penalty = 0; add_pay = 0; other_ded = 0
    goods_delta = defaultdict(int)

    for row in efo_rows:
        op = (row.supplier_oper_name or "").strip()
        art = (row.sa_name or "").upper()
        qty = row.quantity or 0
        if op == "Продажа":
            sales_amount += row.retail_price_withdisc_rub or 0; sales_count += qty
            wb_sales += row.retail_amount or 0; pay_sales += row.ppvz_for_pay or 0
            goods_delta[art] += qty
        if op == "Возврат":
            return_amount += row.retail_price_withdisc_rub or 0; return_count += qty
            pay_sales -= row.ppvz_for_pay or 0; goods_delta[art] -= qty
        delivery += row.delivery_rub or 0; storage += row.storage_fee or 0
        accept += row.acceptance or 0; penalty += row.penalty or 0; add_pay += row.additional_payment or 0
        bonus = (row.bonus_type_name or "")
        if "WB Продвижение" in bonus or "ВБ.Продвижение" in bonus:
            promote += row.deduction or 0
        other_ded += row.deduction or 0
    other_ded -= promote

    total_comm = sum((row.ppvz_sales_commission or 0) for row in efo_rows)
    comm = abs(total_comm) if total_comm != 0 else (wb_sales - pay_sales if wb_sales > 0 else 0)
    total_cost = sum(qty * cost_map[art] for art, qty in goods_delta.items() if art in cost_map and qty > 0)
    wb_total = delivery + comm + storage + accept + promote + penalty
    drr = ad_spend / order_sum_before_spp if order_sum_before_spp > 0 else 0
    year = d.year
    usn = sales_amount * (settings["usn_rate_2025"] if year == 2025 else settings["usn_rate"])
    nds = sales_amount * (settings["nds_rate_2025"] if year == 2025 else settings["nds_rate"])
    buyout = sales_count / (sales_count + return_count) * 100 if (sales_count + return_count) > 0 else 0
    to_supplier = pay_sales
    to_rs = pay_sales - delivery - comm - storage - accept - promote - penalty

    return {
        "date": d.isoformat(),
        "order_sum": round(order_sum_before_spp), "order_sum_spp": round(order_sum_with_spp),
        "order_count": order_count, "order_cancel": order_cancel_count,
        "spp_pct": round(spp_pct * 100, 1), "avg_check_orders": round(avg_check),
        "ad_spend": round(ad_spend), "drr": round(drr * 100, 2),
        "sales_amount": round(sales_amount), "sales_count": sales_count,
        "return_amount": round(return_amount), "return_count": return_count,
        "buyout_pct": round(buyout, 1), "refusal_count": order_cancel_count,
        "delivery": round(delivery), "commission": round(comm),
        "storage": round(storage), "acceptance": round(accept),
        "promotion": round(promote), "penalties": round(penalty),
        "add_payments": round(add_pay), "other_deductions": round(other_ded),
        "to_supplier": round(to_supplier), "to_rs": round(to_rs),
        "cost_of_goods": round(total_cost), "usn": round(usn), "nds": round(nds),
        "wb_expenses_total": round(wb_total),
    }


def _aggregate(daily: list) -> dict:
    t = {
        "orders_amount": sum(d["order_sum"] for d in daily),
        "orders_amount_spp": sum(d["order_sum_spp"] for d in daily),
        "orders_count": sum(d["order_count"] for d in daily),
        "order_cancel": sum(d["order_cancel"] for d in daily),
        "ad_spend": sum(d["ad_spend"] for d in daily),
        "sales_amount": sum(d["sales_amount"] for d in daily),
        "sales_count": sum(d["sales_count"] for d in daily),
        "return_amount": sum(d["return_amount"] for d in daily),
        "return_count": sum(d["return_count"] for d in daily),
        "delivery": sum(d["delivery"] for d in daily),
        "commission": sum(d["commission"] for d in daily),
        "storage": sum(d["storage"] for d in daily),
        "acceptance": sum(d["acceptance"] for d in daily),
        "promotion": sum(d["promotion"] for d in daily),
        "penalties": sum(d["penalties"] for d in daily),
        "add_payments": sum(d["add_payments"] for d in daily),
        "other_deductions": sum(d["other_deductions"] for d in daily),
        "to_supplier": sum(d["to_supplier"] for d in daily),
        "to_rs": sum(d["to_rs"] for d in daily),
        "cost_of_goods": sum(d["cost_of_goods"] for d in daily),
        "usn": sum(d["usn"] for d in daily), "nds": sum(d["nds"] for d in daily),
        "wb_expenses_total": sum(d["wb_expenses_total"] for d in daily),
    }
    t["spp_pct"] = (t["orders_amount"] - t["orders_amount_spp"]) / t["orders_amount"] * 100 if t["orders_amount"] > 0 else 0
    t["drr"] = t["ad_spend"] / t["orders_amount"] * 100 if t["orders_amount"] > 0 else 0
    t["avg_check_orders"] = t["orders_amount"] / t["orders_count"] if t["orders_count"] > 0 else 0
    t["avg_check_sales"] = t["sales_amount"] / t["sales_count"] if t["sales_count"] > 0 else 0
    t["buyout_pct"] = t["sales_count"] / (t["sales_count"] + t["return_count"]) * 100 if (t["sales_count"] + t["return_count"]) > 0 else 0
    sa = t["sales_amount"] or 1
    t["platform_pct"] = round(t["wb_expenses_total"] / sa * 100, 1)
    t["cost_pct"] = round(t["cost_of_goods"] / sa * 100, 1)
    t["commission_pct"] = round(t["commission"] / sa * 100, 1)
    t["logistics_pct"] = round(t["delivery"] / sa * 100, 1)
    t["storage_pct"] = round(t["storage"] / sa * 100, 1)
    t["acceptance_pct"] = round(t["acceptance"] / sa * 100, 1)
    t["promotion_pct"] = round(t["promotion"] / sa * 100, 1)
    t["net_profit"] = round(t["sales_amount"] - t["wb_expenses_total"] - t["cost_of_goods"] - t["usn"] - t["nds"])
    t["profitability"] = round(t["net_profit"] / t["sales_amount"] * 100, 1) if t["sales_amount"] > 0 else 0
    t["gross_margin"] = round(t["sales_amount"] - t["wb_expenses_total"] - t["cost_of_goods"])
    t["taxes"] = round(t["usn"] + t["nds"])
    return t


def calc_rnp_month(db: Session, cabinet_id: str, month: str, comparison_mode: str = "day") -> dict:
    settings = _get_rnp_settings(db, cabinet_id)
    cost_map = _get_cost_map(db, cabinet_id)

    year, mon = map(int, month.split("-"))
    days_in_month = monthrange(year, mon)[1]
    month_start = date(year, mon, 1)
    month_end = date(year, mon, days_in_month)
    today = date.today()
    actual_end = min(month_end, today - timedelta(days=1)) if today <= month_end else month_end

    # Батч-загрузка данных для текущего периода
    orders_curr = _fetch_orders_batch(db, cabinet_id, month_start, actual_end)
    efo_curr = _fetch_efo_batch(db, cabinet_id, month_start, actual_end)
    ad_curr = _fetch_ad_batch(db, cabinet_id, month_start, actual_end)

    daily_current = []
    for day_offset in range((actual_end - month_start).days + 1):
        d = month_start + timedelta(days=day_offset)
        daily_current.append(_calc_day_fast(
            d, orders_curr.get(d, []), efo_curr.get(d, []), ad_curr.get(d, 0), settings, cost_map
        ))
    totals_current = _aggregate(daily_current)

    # Переопределяем order_count и order_sum из ShelfMetrics (воронка)
    shelf_curr = _fetch_shelf_orders(db, cabinet_id, month_start, actual_end)
    if shelf_curr["order_count"] > 0:
        totals_current["orders_count"] = shelf_curr["order_count"]
        totals_current["orders_amount"] = shelf_curr["order_sum"]
        totals_current["avg_check_orders"] = (
            shelf_curr["order_sum"] / shelf_curr["order_count"]
        )
        totals_current["drr"] = (
            totals_current["ad_spend"] / shelf_curr["order_sum"] * 100
            if shelf_curr["order_sum"] > 0 else 0
        )
        totals_current["shelf_order_count"] = shelf_curr["order_count"]
        totals_current["shelf_order_sum"] = shelf_curr["order_sum"]
    else:
        totals_current["shelf_order_count"] = 0
        totals_current["shelf_order_sum"] = 0

    # Недельная агрегация
    weekly = []
    if len(daily_current) >= 7:
        for i in range(0, len(daily_current), 7):
            chunk = daily_current[i:i+7]
            if len(chunk) >= 3:
                weekly.append(_aggregate(chunk))

    # Период сравнения: предшествующий период той же длительности
    prev_start = prev_end = None
    if comparison_mode == "day":
        # День к дню: сравнение с предыдущим днём (сдвиг на 1 день назад)
        prev_start = month_start - timedelta(days=1)
        prev_end = actual_end - timedelta(days=1)
    else:
        # Неделя к неделе: сравнение с предыдущей неделей (сдвиг на 7 дней назад)
        prev_start = month_start - timedelta(days=7)
        prev_end = actual_end - timedelta(days=7)

    daily_prev = []
    totals_prev = None
    if prev_start and prev_end and prev_start <= prev_end:
        orders_prev = _fetch_orders_batch(db, cabinet_id, prev_start, prev_end)
        efo_prev = _fetch_efo_batch(db, cabinet_id, prev_start, prev_end)
        ad_prev = _fetch_ad_batch(db, cabinet_id, prev_start, prev_end)
        for day_offset in range((prev_end - prev_start).days + 1):
            d = prev_start + timedelta(days=day_offset)
            daily_prev.append(_calc_day_fast(
                d, orders_prev.get(d, []), efo_prev.get(d, []), ad_prev.get(d, 0), settings, cost_map
            ))
        totals_prev = _aggregate(daily_prev)

        # Переопределяем order_count и order_sum из ShelfMetrics для периода сравнения
        shelf_prev = _fetch_shelf_orders(db, cabinet_id, prev_start, prev_end)
        if shelf_prev["order_count"] > 0:
            totals_prev["orders_count"] = shelf_prev["order_count"]
            totals_prev["orders_amount"] = shelf_prev["order_sum"]
            totals_prev["avg_check_orders"] = (
                shelf_prev["order_sum"] / shelf_prev["order_count"]
            )
            totals_prev["drr"] = (
                totals_prev["ad_spend"] / shelf_prev["order_sum"] * 100
                if shelf_prev["order_sum"] > 0 else 0
            )

    def delta(curr, prev):
        if prev is None or prev == 0:
            return {"value": curr, "delta": 0, "delta_pct": 0}
        d = curr - prev
        return {"value": curr, "delta": round(d), "delta_pct": round(d / abs(prev) * 100, 1)}

    def delta_pct(curr_pct, prev_pct):
        if prev_pct is None:
            return {"value": curr_pct, "delta": 0, "delta_pct": 0}
        return {"value": curr_pct, "delta": round(curr_pct - prev_pct, 2), "delta_pct": 0}

    pp = totals_prev or {}

    gm_curr = totals_current["gross_margin"]
    gm_prev = (pp.get("gross_margin") if pp else None)
    tx_curr = totals_current["taxes"]
    tx_prev = (pp.get("taxes") if pp else None)

    summary = {
        # Block 1: Заказы и продажи
        "orders_amount": delta(totals_current["orders_amount"], pp.get("orders_amount")),
        "orders_count": delta(totals_current["orders_count"], pp.get("orders_count")),
        "avg_check": delta(totals_current["avg_check_orders"], pp.get("avg_check_orders")),
        "spp_pct": delta_pct(totals_current["spp_pct"], pp.get("spp_pct")),
        "sales_amount": delta(totals_current["sales_amount"], pp.get("sales_amount")),
        "sales_count": delta(totals_current["sales_count"], pp.get("sales_count")),
        "buyout_pct": delta_pct(totals_current["buyout_pct"], pp.get("buyout_pct")),
        "return_amount": delta(totals_current["return_amount"], pp.get("return_amount")),
        "return_count": delta(totals_current["return_count"], pp.get("return_count")),
        # Block 2: Расходы
        "cost_of_goods": delta(totals_current["cost_of_goods"], pp.get("cost_of_goods")),
        "commission": delta(totals_current["commission"], pp.get("commission")),
        "delivery": delta(totals_current["delivery"], pp.get("delivery")),
        "storage": delta(totals_current["storage"], pp.get("storage")),
        "acceptance": delta(totals_current["acceptance"], pp.get("acceptance")),
        "ad_spend": delta(totals_current["ad_spend"], pp.get("ad_spend")),
        "promotion": delta(totals_current["promotion"], pp.get("promotion")),
        "penalties": delta(totals_current["penalties"], pp.get("penalties")),
        "wb_expenses": delta(totals_current["wb_expenses_total"], pp.get("wb_expenses_total")),
        # Block 3: Результат
        "gross_margin": delta(gm_curr, gm_prev),
        "taxes": delta(tx_curr, tx_prev),
        "net_profit": delta(totals_current["net_profit"], pp.get("net_profit")),
        "profitability": {"value": totals_current["profitability"], "delta": round(totals_current["profitability"] - (pp.get("profitability") or 0), 1), "delta_pct": 0},
        "to_supplier": delta(totals_current["to_supplier"], pp.get("to_supplier")),
        "to_rs": delta(totals_current["to_rs"], pp.get("to_rs")),
    }

    # Товары: агрегация по артикулам
    art_curr_map = defaultdict(float)
    art_prev_map = defaultdict(float)
    dt_start_c = datetime(month_start.year, month_start.month, month_start.day)
    dt_end_c = datetime(actual_end.year, actual_end.month, actual_end.day) + timedelta(days=1)
    efo_all_curr = db.query(SalesReport).filter(
        SalesReport.cabinet_id == cabinet_id,
        SalesReport.sale_dt >= dt_start_c, SalesReport.sale_dt < dt_end_c,
        SalesReport.supplier_oper_name == "Продажа",
    ).all()
    for r in efo_all_curr:
        art = (r.sa_name or "").strip()
        if art:
            art_curr_map[art] += r.retail_price_withdisc_rub or 0

    if prev_start and prev_end:
        dt_start_p = datetime(prev_start.year, prev_start.month, prev_start.day)
        dt_end_p = datetime(prev_end.year, prev_end.month, prev_end.day) + timedelta(days=1)
        efo_all_prev = db.query(SalesReport).filter(
            SalesReport.cabinet_id == cabinet_id,
            SalesReport.sale_dt >= dt_start_p, SalesReport.sale_dt < dt_end_p,
            SalesReport.supplier_oper_name == "Продажа",
        ).all()
        for r in efo_all_prev:
            art = (r.sa_name or "").strip()
            if art:
                art_prev_map[art] += r.retail_price_withdisc_rub or 0

    all_arts = set(list(art_curr_map.keys()) + list(art_prev_map.keys()))
    art_deltas = []
    for art in all_arts:
        c = art_curr_map.get(art, 0)
        p = art_prev_map.get(art, 0)
        art_deltas.append({"article": art, "current": round(c), "delta": round(c - p)})
    art_deltas.sort(key=lambda x: x["delta"], reverse=True)
    top_products = [a for a in art_deltas if a["delta"] > 0][:10]
    bottom_products = [a for a in art_deltas if a["delta"] < 0][-10:]

    # План
    plan = None
    for p in db.query(RnpPlan).filter(RnpPlan.cabinet_id == cabinet_id).all():
        if p.month.year == year and p.month.month == mon:
            plan = {
                "orders_amount": p.orders_amount, "orders_count": p.orders_count,
                "sales_minus_returns": p.sales_minus_returns, "sales_count": p.sales_count,
                "margin_rub": p.margin_rub, "margin_percent": p.margin_percent,
                "drr": p.drr, "avg_price": p.avg_price, "cost_of_goods": p.cost_of_goods,
                "logistics": p.logistics, "commission": p.commission, "storage": p.storage,
                "paid_acceptance": p.paid_acceptance, "promotion": p.promotion,
                "penalties": p.penalties, "nds": p.nds, "profit": p.profit, "spp": p.spp,
            }
            break

    # Относительные метрики
    sa = totals_current["sales_amount"] or 1
    eff = totals_current["sales_count"] - totals_current["return_count"] or 1
    tc = totals_current
    relative = {
        "markup": round(tc["sales_amount"] / tc["cost_of_goods"], 2) if tc["cost_of_goods"] > 0 else 0,
        "logistics_per_unit": round(tc["delivery"] / eff),
        "cost_per_unit": round(tc["cost_of_goods"] / eff),
        "promotion_per_unit": round(tc["promotion"] / eff),
        "storage_per_unit": round(tc["storage"] / eff),
        "net_profit_per_unit": round(tc["net_profit"] / eff),
        "platform_pct": round(tc["wb_expenses_total"] / sa * 100, 1),
        "commission_pct": round(tc["commission"] / sa * 100, 1),
        "logistics_pct": round(tc["delivery"] / sa * 100, 1),
        "promotion_pct": round(tc["promotion"] / sa * 100, 1),
        "storage_pct": round(tc["storage"] / sa * 100, 1),
        "acceptance_pct": round(tc["acceptance"] / sa * 100, 1),
        "cost_pct": round(tc["cost_of_goods"] / sa * 100, 1),
        "taxes_pct": round((tc["usn"] + tc["nds"]) / sa * 100, 1),
    }

    return {
        "cabinet_id": cabinet_id, "month": month, "comparison_mode": comparison_mode,
        "comparison_period": {"start": prev_start.isoformat() if prev_start else None, "end": prev_end.isoformat() if prev_end else None},
        "daily": daily_current, "daily_prev": daily_prev, "weekly": weekly,
        "totals": totals_current, "totals_prev": totals_prev,
        "summary": summary, "top_products": top_products, "bottom_products": bottom_products,
        "plan": plan, "relative": relative, "settings": settings,
    }


def calc_rnp(db: Session, cabinet_id: str, days_back: int = 40) -> dict:
    settings = _get_rnp_settings(db, cabinet_id)
    cost_map = _get_cost_map(db, cabinet_id)
    today = datetime.utcnow().date()
    date_end = today - timedelta(days=1)
    date_start = date_end - timedelta(days=days_back - 1)

    orders_b = _fetch_orders_batch(db, cabinet_id, date_start, date_end)
    efo_b = _fetch_efo_batch(db, cabinet_id, date_start, date_end)
    ad_b = _fetch_ad_batch(db, cabinet_id, date_start, date_end)

    daily = []
    for day_offset in range(days_back):
        d = date_start + timedelta(days=day_offset)
        daily.append(_calc_day_fast(d, orders_b.get(d, []), efo_b.get(d, []), ad_b.get(d, 0), settings, cost_map))

    t = _aggregate(daily)

    # Переопределяем order_count и order_sum из ShelfMetrics (воронка)
    shelf = _fetch_shelf_orders(db, cabinet_id, date_start, date_end)
    if shelf["order_count"] > 0:
        t["orders_count"] = shelf["order_count"]
        t["orders_amount"] = shelf["order_sum"]
        t["avg_check_orders"] = shelf["order_sum"] / shelf["order_count"]
        t["drr"] = t["ad_spend"] / shelf["order_sum"] * 100 if shelf["order_sum"] > 0 else 0
        t["shelf_order_count"] = shelf["order_count"]
        t["shelf_order_sum"] = shelf["order_sum"]
    else:
        t["shelf_order_count"] = 0
        t["shelf_order_sum"] = 0

    sa = t["sales_amount"] or 1
    relative = {
        "markup": t["sales_amount"] / t["cost_of_goods"] if t["cost_of_goods"] > 0 else 0,
        "logistics_per_unit": round(t["delivery"] / (t["sales_count"] - t["return_count"] or 1)),
        "cost_per_unit": round(t["cost_of_goods"] / (t["sales_count"] - t["return_count"] or 1)),
        "promotion_per_unit": round(t["promotion"] / (t["sales_count"] - t["return_count"] or 1)),
        "storage_per_unit": round(t["storage"] / (t["sales_count"] - t["return_count"] or 1)),
        "net_profit_per_unit": round(t["net_profit"] / (t["sales_count"] - t["return_count"] or 1)),
        "platform_expenses_pct": round(t["wb_expenses_total"] / sa * -100, 1),
        "commission_pct": round(t["commission"] / sa * -100, 1),
        "logistics_pct": round(t["delivery"] / sa * -100, 1),
        "promotion_pct": round(t["promotion"] / sa * -100, 1),
        "storage_pct": round(t["storage"] / sa * -100, 1),
        "acceptance_pct": round(t["acceptance"] / sa * -100, 1),
        "cost_pct": round(t["cost_of_goods"] / sa * -100, 1),
        "taxes_pct": round((t["usn"] + t["nds"]) / sa * -100, 1),
    }

    plans_data = []
    for p in db.query(RnpPlan).filter(RnpPlan.cabinet_id == cabinet_id).order_by(RnpPlan.month).all():
        plans_data.append({
            "month": p.month.isoformat(), "orders_amount": p.orders_amount,
            "orders_count": p.orders_count, "sales_minus_returns": p.sales_minus_returns,
            "sales_count": p.sales_count, "returns_count": p.returns_count,
            "margin_rub": p.margin_rub, "margin_percent": p.margin_percent,
            "drr": p.drr, "avg_price": p.avg_price, "cost_of_goods": p.cost_of_goods,
            "logistics": p.logistics, "commission": p.commission, "storage": p.storage,
            "paid_acceptance": p.paid_acceptance, "promotion": p.promotion,
            "penalties": p.penalties, "nds": p.nds, "profit": p.profit, "spp": p.spp,
        })

    return {
        "cabinet_id": cabinet_id,
        "period": {"start": date_start.isoformat(), "end": date_end.isoformat(), "days": days_back},
        "daily": daily,
        "totals": {
            "orders_amount": t["orders_amount"], "orders_count": t["orders_count"],
            "avg_check_orders": round(t["avg_check_orders"]), "spp_pct": round(t["spp_pct"], 1),
            "ad_spend": t["ad_spend"], "drr": round(t["drr"], 2),
            "sales_amount": t["sales_amount"], "sales_count": t["sales_count"],
            "return_amount": t["return_amount"], "return_count": t["return_count"],
            "refusal_count": t["order_cancel"], "avg_check_sales": round(t["avg_check_sales"]),
            "buyout_pct": round(t["buyout_pct"], 1), "spp_sales": 0,
            "to_supplier": t["to_supplier"], "cost_of_goods": t["cost_of_goods"],
            "shelf_order_count": t.get("shelf_order_count", 0),
            "shelf_order_sum": t.get("shelf_order_sum", 0),
        },
        "wb_expenses": {
            "delivery": t["delivery"], "commission": t["commission"],
            "storage": t["storage"], "acceptance": t["acceptance"],
            "promotion": t["promotion"], "penalties": t["penalties"],
        },
        "wb_expenses_total": t["wb_expenses_total"],
        "operating_expenses": 0, "fixed_expenses": [], "variable_expenses": [],
        "loan_payments": [], "total_loans": 0,
        "gross_margin": t["net_profit"] + t["usn"] + t["nds"],
        "ebitda": t["net_profit"] + t["usn"] + t["nds"],
        "taxes": {"usn": t["usn"], "nds": t["nds"], "total": t["usn"] + t["nds"]},
        "net_profit": t["net_profit"], "profitability": t["profitability"],
        "relative_metrics": relative, "plans": plans_data, "settings": settings,
    }
