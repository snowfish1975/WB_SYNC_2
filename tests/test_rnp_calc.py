"""Тесты расчёта РНП (app/rnp_calc.py): дневной расчёт и агрегация.

Чистые функции _calc_day_fast и _aggregate принимают готовые списки строк —
БД не нужна, строки моделей создаём напрямую.
"""
from datetime import date, datetime

from app import rnp_calc

from conftest import CAB

# Settings по умолчанию (как в _get_rnp_settings при отсутствии записи в БД)
SETTINGS = {"usn_rate": 0.06, "usn_rate_2025": 0.06, "nds_rate": 0.07,
            "nds_rate_2025": 0.07, "usd_rate": 0, "cny_rate": 0,
            "paid_acceptance_enabled": True, "localization_index": 1}


def efo_row(**kw):
    """Строка отчёта реализации (SalesReport) с полями, которые читает _calc_day_fast."""
    base = dict(
        supplier_oper_name="Продажа", sa_name="ART-1", quantity=1,
        retail_price_withdisc_rub=1000.0, retail_amount=900.0, ppvz_for_pay=800.0,
        ppvz_sales_commission=100.0, delivery_rub=50.0, storage_fee=10.0,
        acceptance=5.0, penalty=0.0, additional_payment=0.0, deduction=0.0,
        bonus_type_name="", sa_name_upper=None,
    )
    base.update(kw)
    return type("SR", (), base)()


def order_row(**kw):
    """Строка заказа (Order)."""
    base = dict(price_with_disc=1100.0, finished_price=1000.0, is_cancel=False)
    base.update(kw)
    return type("O", (), base)()


D = date(2026, 9, 15)


class TestCalcDayFast:
    def test_empty_day(self):
        """Пустой день — нули, без деления на ноль.

        net_profit в дневном словаре нет — он считается только в _aggregate.
        """
        r = rnp_calc._calc_day_fast(D, [], [], 0, SETTINGS, {})
        assert r["sales_amount"] == 0
        assert r["order_count"] == 0
        assert r["buyout_pct"] == 0
        assert r["drr"] == 0
        assert "net_profit" not in r

    def test_sale_sums(self):
        rows = [efo_row(), efo_row(quantity=2, retail_price_withdisc_rub=2000.0,
                                   retail_amount=1800.0, ppvz_for_pay=1600.0,
                                   ppvz_sales_commission=200.0)]
        r = rnp_calc._calc_day_fast(D, [], rows, 0, SETTINGS, {})
        assert r["sales_amount"] == 3000
        assert r["sales_count"] == 3
        assert r["commission"] == 300  # сумма ppvz_sales_commission
        assert r["delivery"] == 100    # 50+50
        assert r["storage"] == 20

    def test_return_subtracts(self):
        """Возврат учитывается в отдельных статьях и уменьшает pay_sales
        (sales_amount дня не уменьшает — продажи и возвраты считаются раздельно)."""
        rows = [efo_row(), efo_row(supplier_oper_name="Возврат",
                                   retail_price_withdisc_rub=1000.0,
                                   ppvz_for_pay=800.0)]
        r = rnp_calc._calc_day_fast(D, [], rows, 0, SETTINGS, {})
        assert r["sales_amount"] == 1000
        assert r["sales_count"] == 1
        assert r["return_amount"] == 1000
        assert r["return_count"] == 1
        assert r["buyout_pct"] == 50.0
        # к перечислению: 800 (продажа) − 800 (возврат)
        assert r["to_supplier"] == 0

    def test_commission_fallback_from_amounts(self):
        """Если ppvz_sales_commission все 0 — комиссия = wb_sales - pay_sales."""
        rows = [efo_row(ppvz_sales_commission=0.0)]
        r = rnp_calc._calc_day_fast(D, [], rows, 0, SETTINGS, {})
        assert r["commission"] == 100  # 900 - 800

    def test_promotion_from_bonus_type(self):
        """WB Продвижение выделяется из deduction в отдельную статью."""
        rows = [efo_row(deduction=300.0, bonus_type_name="WB Продвижение")]
        r = rnp_calc._calc_day_fast(D, [], rows, 0, SETTINGS, {})
        assert r["promotion"] == 300
        assert r["other_deductions"] == 0  # promote исключён из прочих

    def test_other_deductions_without_promotion(self):
        rows = [efo_row(deduction=250.0, bonus_type_name="Компенсация")]
        r = rnp_calc._calc_day_fast(D, [], rows, 0, SETTINGS, {})
        assert r["promotion"] == 0
        assert r["other_deductions"] == 250

    def test_cost_of_goods(self):
        """Себестоимость = qty * cost только для проданных (delta>0) артикулов."""
        cost_map = {"ART-1": 400.0, "ART-2": 999.0}
        rows = [
            efo_row(sa_name="art-1", quantity=2),            # +2 → 800
            efo_row(sa_name="ART-2", quantity=1),            # +1, но ART-2 нет продажи? есть → 999
            efo_row(supplier_oper_name="Возврат", sa_name="ART-1", quantity=1),  # -1
        ]
        r = rnp_calc._calc_day_fast(D, [], rows, 0, SETTINGS, cost_map)
        # ART-1: delta=1 → 400; ART-2: delta=1 → 999
        assert r["cost_of_goods"] == 1399

    def test_cost_ignored_without_cost_map(self):
        rows = [efo_row(quantity=3)]
        r = rnp_calc._calc_day_fast(D, [], rows, 0, SETTINGS, {})
        assert r["cost_of_goods"] == 0

    def test_orders_metrics(self):
        """Суммы заказов включают отменённые, счётчик — нет (так задумано:
        сумма отражает спрос, счётчик — валидные заказы)."""
        orders = [order_row(), order_row(is_cancel=True),
                  order_row(price_with_disc=2500.0, finished_price=2300.0)]
        r = rnp_calc._calc_day_fast(D, orders, [], 0, SETTINGS, {})
        assert r["order_count"] == 2
        assert r["order_cancel"] == 1
        assert r["order_sum"] == 4700        # 1100 + 1100 (cancel) + 2500
        assert r["order_sum_spp"] == 4300    # 1000 + 1000 + 2300
        assert r["avg_check_orders"] == 2350  # 4700 / 2 (не-отменённые)
        # spp = (4700−4300)/4700 = 8.51% → 8.5
        assert r["spp_pct"] == 8.5

    def test_drr(self):
        orders = [order_row(price_with_disc=2000.0)]
        r = rnp_calc._calc_day_fast(D, orders, [], 100.0, SETTINGS, {})
        assert r["drr"] == 5.0

    def test_taxes_2025_rates(self):
        """Для 2025 года должны применяться *_2025 ставки."""
        rows = [efo_row(retail_price_withdisc_rub=10000.0)]
        settings = {**SETTINGS, "usn_rate": 0.10, "usn_rate_2025": 0.04,
                    "nds_rate": 0.20, "nds_rate_2025": 0.05}
        r2025 = rnp_calc._calc_day_fast(date(2025, 6, 1), [], rows, 0, settings, {})
        r2026 = rnp_calc._calc_day_fast(D, [], rows, 0, settings, {})
        assert r2025["usn"] == 400
        assert r2025["nds"] == 500
        assert r2026["usn"] == 1000
        assert r2026["nds"] == 2000

    def test_wb_expenses_total(self):
        """wb_expenses_total = delivery + commission + storage + accept + promote + penalty."""
        rows = [efo_row(deduction=100.0, bonus_type_name="WB Продвижение")]
        r = rnp_calc._calc_day_fast(D, [], rows, 0, SETTINGS, {})
        expected = 50 + 100 + 10 + 5 + 100 + 0
        assert r["wb_expenses_total"] == expected

    def test_to_supplier_and_to_rs(self):
        rows = [efo_row()]
        r = rnp_calc._calc_day_fast(D, [], rows, 0, SETTINGS, {})
        assert r["to_supplier"] == 800
        # to_rs = pay_sales - delivery - comm - storage - accept - promote - penalty
        assert r["to_rs"] == 800 - 50 - 100 - 10 - 5 - 0 - 0


class TestAggregate:
    def test_sums_and_pcts(self):
        daily = [
            {"order_sum": 1000, "order_sum_spp": 900, "order_count": 10, "order_cancel": 1,
             "ad_spend": 50, "sales_amount": 800, "sales_count": 5,
             "return_amount": 100, "return_count": 1,
             "delivery": 40, "commission": 80, "storage": 10, "acceptance": 5,
             "promotion": 20, "penalties": 0, "add_payments": 0, "other_deductions": 3,
             "to_supplier": 600, "to_rs": 445, "cost_of_goods": 300,
             "usn": 48, "nds": 56, "wb_expenses_total": 155},
            {"order_sum": 2000, "order_sum_spp": 1800, "order_count": 20, "order_cancel": 2,
             "ad_spend": 150, "sales_amount": 1600, "sales_count": 10,
             "return_amount": 200, "return_count": 2,
             "delivery": 80, "commission": 160, "storage": 20, "acceptance": 10,
             "promotion": 40, "penalties": 0, "add_payments": 0, "other_deductions": 6,
             "to_supplier": 1200, "to_rs": 890, "cost_of_goods": 600,
             "usn": 96, "nds": 112, "wb_expenses_total": 310},
        ]
        t = rnp_calc._aggregate(daily)
        assert t["orders_amount"] == 3000
        assert t["orders_count"] == 30
        assert t["ad_spend"] == 200
        assert t["sales_amount"] == 2400
        # spp = (3000-2700)/3000*100
        assert round(t["spp_pct"], 1) == 10.0
        # drr = 200/3000*100
        assert round(t["drr"], 1) == 6.7
        # buyout = 15/(15+3)*100
        assert round(t["buyout_pct"], 1) == 83.3
        # net_profit = sales - wb_expenses - cost - usn - nds
        assert t["net_profit"] == 2400 - 465 - 900 - 144 - 168
        assert t["gross_margin"] == 2400 - 465 - 900
        assert t["taxes"] == 312

    def test_empty_daily(self):
        t = rnp_calc._aggregate([])
        assert t["sales_amount"] == 0
        assert t["net_profit"] == 0
        assert t["buyout_pct"] == 0
        # sa==0 → заменяется на 1, перценты 0
        assert t["platform_pct"] == 0

    def test_zero_sales_no_division_error(self):
        daily = [{"order_sum": 0, "order_sum_spp": 0, "order_count": 0, "order_cancel": 0,
                  "ad_spend": 0, "sales_amount": 0, "sales_count": 0,
                  "return_amount": 0, "return_count": 0,
                  "delivery": 0, "commission": 0, "storage": 0, "acceptance": 0,
                  "promotion": 0, "penalties": 0, "add_payments": 0, "other_deductions": 0,
                  "to_supplier": 0, "to_rs": 0, "cost_of_goods": 0,
                  "usn": 0, "nds": 0, "wb_expenses_total": 0}]
        t = rnp_calc._aggregate(daily)
        assert t["profitability"] == 0
        assert t["avg_check_orders"] == 0
