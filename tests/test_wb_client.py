"""Тесты нормализации строк отчёта реализации (finance-api) в app/wb_client.py.

Новый метод WB POST /api/finance/v1/sales-reports/detailed отдаёт camelCase-поля
и суммы строками; normalize_sales_report_row() переводит их в термины колонок
SalesReport (snake_case), которые ждут crud, дашборд и РНП.
"""
from app import wb_client


class TestFieldMap:
    def test_map_covers_key_renames(self):
        """Критичные переименования старого API → нового."""
        m = wb_client.SALES_REPORT_FIELD_MAP
        assert m["forPay"] == "ppvz_for_pay"
        assert m["paidStorage"] == "storage_fee"
        assert m["deliveryService"] == "delivery_rub"
        assert m["paidAcceptance"] == "acceptance"
        assert m["vendorCode"] == "sa_name"
        assert m["techSize"] == "ts_name"
        assert m["sku"] == "barcode"
        assert m["sellerOperName"] == "supplier_oper_name"
        assert m["country"] == "site_country"
        assert m["spp"] == "ppvz_spp_prc"
        assert m["isB2b"] == "is_legal_entity"

    def test_removed_fields_have_no_mapping(self):
        """Поля, убранные WB, не должны случайно замапиться."""
        m = wb_client.SALES_REPORT_FIELD_MAP
        assert "suppliercontract_code" not in m.values()
        assert "ppvz_supplier_id" not in m.values()


class TestNormalizeRow:
    def test_full_row(self):
        row = {
            "reportId": 12345,
            "rrdId": 67890,
            "nmId": 111222333,
            "vendorCode": "ART-001",
            "subjectName": "Футболка",
            "quantity": 2,
            "forPay": "376.99",
            "spp": "1.349",
            "retailAmount": "1200.00",
            "saleDt": "2026-09-20T21:00:00Z",
            "orderDt": "2026-09-18T10:30:00Z",
        }
        out = wb_client.normalize_sales_report_row(row)

        assert out["realizationreport_id"] == 12345
        assert out["rrd_id"] == 67890
        assert out["nm_id"] == 111222333
        assert out["sa_name"] == "ART-001"
        assert out["subject_name"] == "Футболка"
        assert out["quantity"] == 2
        # суммы-строки → float
        assert out["ppvz_for_pay"] == 376.99
        assert out["ppvz_spp_prc"] == 1.349
        assert out["retail_amount"] == 1200.0
        # datetime в UTC без суффикса (конвенция БД)
        assert out["sale_dt"] == "2026-09-20T21:00:00"
        assert out["order_dt"] == "2026-09-18T10:30:00"
        # исходная строка сохранена
        assert out["_raw"] is row
        assert out["_api"] == "finance/v1/sales-reports/detailed"

    def test_unknown_fields_go_to_raw_only(self):
        """title/paidWithSocialCertificate/warehouseLogisticsCoeff — колонок нет."""
        row = {"title": "Товар", "paidWithSocialCertificate": True,
               "warehouseLogisticsCoeff": 1.5, "rrdId": 1}
        out = wb_client.normalize_sales_report_row(row)
        assert "title" not in out
        assert "paidWithSocialCertificate" not in out
        assert out["_raw"] == row

    def test_empty_string_amounts_become_none(self):
        """WB отдаёт '' для отсутствующих сумм — не должно падать."""
        out = wb_client.normalize_sales_report_row({"forPay": "", "penalty": ""})
        assert out["ppvz_for_pay"] is None
        assert out["penalty"] is None

    def test_russian_decimal_comma(self):
        out = wb_client.normalize_sales_report_row({"forPay": "1 234,56"})
        assert out["ppvz_for_pay"] == 1234.56

    def test_thin_space_amount(self):
        out = wb_client.normalize_sales_report_row({"forPay": "\xa01\xa0234.56"})
        assert out["ppvz_for_pay"] == 1234.56

    def test_negative_amount(self):
        out = wb_client.normalize_sales_report_row({"forPay": "-1"})
        assert out["ppvz_for_pay"] == -1.0

    def test_int_fields_accept_strings(self):
        out = wb_client.normalize_sales_report_row({"quantity": "3", "nmId": "42"})
        assert out["quantity"] == 3
        assert out["nm_id"] == 42

    def test_garbage_amount_is_none_not_raise(self):
        out = wb_client.normalize_sales_report_row({"forPay": "abc"})
        assert out["ppvz_for_pay"] is None

    def test_datetime_with_offset_normalized_to_utc(self):
        """Дата со смещением +03:00 переводится в naive-UTC."""
        out = wb_client.normalize_sales_report_row({"saleDt": "2026-09-20T21:00:00+03:00"})
        assert out["sale_dt"] == "2026-09-20T18:00:00"

    def test_date_fields_keep_date_only(self):
        out = wb_client.normalize_sales_report_row(
            {"rrDate": "2026-09-20T23:00:00Z", "createDate": "2026-09-19"}
        )
        # rrDate по Москве (UTC+3): 23:00Z → 21.09
        assert out["rr_dt"] == "2026-09-21"
        assert out["create_dt"] == "2026-09-19"

    def test_bad_date_is_none(self):
        out = wb_client.normalize_sales_report_row({"saleDt": "not-a-date"})
        assert out["sale_dt"] is None

    def test_all_string_amounts_parsed(self):
        """Полный прогон float-полей: каждое должно распарситься как число."""
        row = {k: "10.5" for k in
               ["retailPrice", "retailAmount", "retailPriceWithDisc", "forPay",
                "ppvzReward", "kvw", "kvwBase", "spp", "deliveryService",
                "paidStorage", "paidAcceptance", "penalty", "deduction"]}
        out = wb_client.normalize_sales_report_row(row)
        for col in ("retail_price", "retail_amount", "retail_price_withdisc_rub",
                    "ppvz_for_pay", "ppvz_reward", "ppvz_kvw_prc", "ppvz_kvw_prc_base",
                    "ppvz_spp_prc", "delivery_rub", "storage_fee", "acceptance",
                    "penalty", "deduction"):
            assert out[col] == 10.5, col
