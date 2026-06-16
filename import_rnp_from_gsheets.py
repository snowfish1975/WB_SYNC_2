"""
Импорт настроек РНП из Google Sheets в БД.
Источник: https://docs.google.com/spreadsheets/d/1Z3jbNHG7P1z8KlafwHO1d4qhAmaZg5pBlR_8Njr3lKo
"""

import json
import urllib.request
from datetime import datetime
from app.database import SessionLocal
from app.models import RnpSetting, RnpCost, RnpPlan

SPREADSHEET_ID = "1Z3jbNHG7P1z8KlafwHO1d4qhAmaZg5pBlR_8Njr3lKo"
API_KEY = "AIzaSyBcid8ExtGU3FMiKVbHLkWyTpGaQqyolwM"
CABINET_ID = "f8874ac6d544a7266cf8dc8a471d751d"


def fetch_sheet(range_name: str) -> list[list]:
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{SPREADSHEET_ID}/values/{range_name}?key={API_KEY}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    return data.get("values", [])


def parse_percent(s: str) -> float:
    if not s:
        return 0.0
    s = s.strip().replace(",", ".").replace("%", "").replace(" ", "")
    try:
        return float(s) / 100
    except:
        return 0.0


def parse_number(s: str) -> float:
    if not s:
        return 0.0
    s = s.strip().replace(",", ".").replace(" ", "").replace("\xa0", "")
    try:
        return float(s)
    except:
        return 0.0


def parse_int(s: str) -> int:
    return int(parse_number(s))


def import_settings(db):
    rows = fetch_sheet("%E2%9A%99%EF%B8%8F")
    print(f"[Settings] Fetched {len(rows)} rows")

    # Find settings by label
    settings = {
        "usn_rate": 0.06, "usn_rate_2025": 0.06,
        "nds_rate": 0.07, "nds_rate_2025": 0.07,
        "usd_rate": 0, "cny_rate": 0,
        "paid_acceptance_enabled": True, "localization_index": 1.0,
    }

    for row in rows:
        if len(row) < 2:
            continue
        label = (row[1] if len(row) > 1 else "").strip()
        value = (row[2] if len(row) > 2 else "").strip()

        if "УСН" in label and "2025" in label:
            settings["usn_rate_2025"] = parse_percent(value)
        elif "УСН" in label and "2025" not in label:
            settings["usn_rate"] = parse_percent(value)
        elif "НДС" in label and "2025" in label:
            settings["nds_rate_2025"] = parse_percent(value)
        elif "НДС" in label and "2025" not in label:
            settings["nds_rate"] = parse_percent(value)
        elif "USD" in label:
            settings["usd_rate"] = parse_number(value)
        elif "CNY" in label:
            settings["cny_rate"] = parse_number(value)
        elif "приемки" in label.lower() or "приёмки" in label.lower():
            settings["paid_acceptance_enabled"] = value == "1" or value.lower() == "true"
        elif "индекс" in label.lower() and "локализации" in label.lower():
            settings["localization_index"] = parse_number(value) or 1.0

    settings['usn_rate'] = round(settings['usn_rate'], 4)
    settings['nds_rate'] = round(settings['nds_rate'], 4)
    settings['usn_rate_2025'] = round(settings['usn_rate_2025'], 4)
    settings['nds_rate_2025'] = round(settings['nds_rate_2025'], 4)

    print(f"[Settings] Parsed: USN={settings['usn_rate']*100}%, NDS={settings['nds_rate']*100}%, "
          f"USN2025={settings['usn_rate_2025']*100}%, NDS2025={settings['nds_rate_2025']*100}%, "
          f"USD={settings['usd_rate']}, CNY={settings['cny_rate']}, "
          f"Accept={settings['paid_acceptance_enabled']}, Localization={settings['localization_index']}")

    row_obj = db.query(RnpSetting).filter(RnpSetting.cabinet_id == CABINET_ID).first()
    if row_obj:
        for k, v in settings.items():
            setattr(row_obj, k, v)
        row_obj.updated_at = datetime.utcnow()
    else:
        row_obj = RnpSetting(cabinet_id=CABINET_ID, **settings)
        db.add(row_obj)
    db.commit()
    print("[Settings] Saved to DB")
    return settings


def import_costs(db):
    rows = fetch_sheet("%E2%9A%99%EF%B8%8F!B24:K200")
    print(f"[Costs] Fetched {len(rows)} rows")

    costs = []
    for row in rows:
        if len(row) < 3:
            continue
        article = (row[0] if len(row) > 0 else "").strip()
        cost_str = (row[1] if len(row) > 1 else "").strip()
        currency = (row[2] if len(row) > 2 else "").strip() or "RUB"
        manager = (row[3] if len(row) > 3 else "").strip() or None
        product_type = (row[4] if len(row) > 4 else "").strip() or None
        shipment_type = (row[5] if len(row) > 5 else "").strip() or None
        min_margin_str = (row[7] if len(row) > 7 else "").strip()
        target_margin_str = (row[8] if len(row) > 8 else "").strip()
        target_drr_str = (row[9] if len(row) > 9 else "").strip()

        if not article or article == "Артикул продавца":
            continue

        cost_rub = parse_number(cost_str)
        if cost_rub <= 0:
            continue
        min_margin = parse_percent(min_margin_str)
        target_margin = parse_percent(target_margin_str)
        target_drr = parse_percent(target_drr_str)

        costs.append({
            "supplier_article": article,
            "cost_rub": cost_rub,
            "currency": currency if currency else "RUB",
            "manager": manager,
            "product_type": product_type,
            "shipment_type": shipment_type,
            "min_margin": min_margin if min_margin else None,
            "target_margin": target_margin if target_margin else None,
            "target_drr": target_drr if target_drr else None,
        })

    print(f"[Costs] Parsed {len(costs)} articles")

    # Clear old costs and insert new
    db.query(RnpCost).filter(RnpCost.cabinet_id == CABINET_ID).delete()
    db.commit()

    for c in costs:
        db.add(RnpCost(cabinet_id=CABINET_ID, **c))
    db.commit()
    print(f"[Costs] Saved {len(costs)} articles to DB")
    return costs


def import_plans(db):
    rows = fetch_sheet("%D0%9F%D0%BB%D0%B0%D0%BD!B2:S10")
    print(f"[Plans] Fetched {len(rows)} rows")

    plans = []
    for row in rows:
        if len(row) < 3:
            continue
        month_str = (row[1] if len(row) > 1 else "").strip()
        if not month_str or month_str == "":
            continue
        if "." not in month_str:
            continue

        # Parse month like "02.2026"
        try:
            parts = month_str.split(".")
            month_dt = datetime(int(parts[1]), int(parts[0]), 1)
        except:
            continue

        orders_amount = parse_number(row[2] if len(row) > 2 else "")
        sales_minus_returns = parse_number(row[3] if len(row) > 3 else "")
        margin_rub = parse_number(row[4] if len(row) > 4 else "")
        margin_percent = parse_percent(row[5] if len(row) > 5 else "")
        drr = parse_percent(row[6] if len(row) > 6 else "")
        orders_count = parse_int(row[7] if len(row) > 7 else "")
        avg_price = parse_number(row[8] if len(row) > 8 else "")
        sales_count = parse_int(row[9] if len(row) > 9 else "")
        cost_of_goods = parse_number(row[10] if len(row) > 10 else "")
        commission = parse_number(row[11] if len(row) > 11 else "")
        promotion = parse_number(row[12] if len(row) > 12 else "")
        storage = parse_number(row[13] if len(row) > 13 else "")
        acceptance = parse_number(row[14] if len(row) > 14 else "")
        logistics = parse_number(row[15] if len(row) > 15 else "")
        nds = parse_number(row[16] if len(row) > 16 else "")
        spp = parse_percent(row[17] if len(row) > 17 else "")
        profit = parse_number(row[18] if len(row) > 18 else "")

        plans.append({
            "month": month_dt,
            "orders_amount": orders_amount,
            "orders_count": orders_count,
            "sales_minus_returns": sales_minus_returns,
            "sales_count": sales_count,
            "returns_count": 0,
            "margin_rub": margin_rub,
            "margin_percent": margin_percent,
            "drr": drr,
            "avg_price": avg_price,
            "cost_of_goods": cost_of_goods,
            "logistics": logistics,
            "commission": commission,
            "storage": storage,
            "paid_acceptance": acceptance,
            "promotion": promotion,
            "penalties": 0,
            "nds": nds,
            "profit": profit,
            "spp": spp,
        })

    print(f"[Plans] Parsed {len(plans)} months")

    # Clear old plans and insert new
    db.query(RnpPlan).filter(RnpPlan.cabinet_id == CABINET_ID).delete()
    db.commit()

    for p in plans:
        db.add(RnpPlan(cabinet_id=CABINET_ID, **p))
    db.commit()
    print(f"[Plans] Saved {len(plans)} months to DB")
    return plans


def main():
    db = SessionLocal()
    try:
        print("=== Импорт РНП из Google Sheets ===")
        print(f"Cabinet: ИП Брыкин ({CABINET_ID})")
        print()

        settings = import_settings(db)
        print()

        costs = import_costs(db)
        print()

        plans = import_plans(db)
        print()

        print("=== Импорт завершён ===")
        print(f"Settings: USN={settings['usn_rate']*100}%, NDS={settings['nds_rate']*100}%")
        print(f"Costs: {len(costs)} артикулов")
        print(f"Plans: {len(plans)} месяцев")
    finally:
        db.close()


if __name__ == "__main__":
    main()
