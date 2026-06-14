# Stock Forecast & Unit Economics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add stock forecasting (30-day horizon) and unit economics analysis (per-SKU profitability) to the WB Sync dashboard.

**Architecture:** Server-side computation in Python (crud.py + main.py), two new dashboard tabs with interactive tables, sparklines, and detail views. All data from existing tables — no new models needed.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x, PostgreSQL, Chart.js, vanilla JS

---

## File Structure

| File | Action | Purpose |
|------|--------|---------|
| `app/crud.py` | Modify | Add `get_stock_forecast()` and `get_unit_economics()` functions |
| `app/main.py` | Modify | Add `GET /api/dashboard/stock-forecast` and `GET /api/dashboard/unit-economics` endpoints |
| `static/tabs/stock-forecast.html` | Create | Stock forecast dashboard tab |
| `static/tabs/unit-economics.html` | Create | Unit economics dashboard tab |
| `static/dashboard.html` | Modify | Add tab buttons and content divs |
| `static/js/tabs.js` | Modify | Register new tabs in TAB_SRCS |

---

### Task 1: Backend — Stock Forecast SQL + CRUD

**Covers:** [S2]

**Files:**
- Modify: `app/crud.py`

- [ ] **Step 1: Add `get_stock_forecast()` function to crud.py**

Add at the end of `app/crud.py` (before the last empty line):

```python
# -------------------------
# Stock Forecast (Прогноз остатков)
# -------------------------
def get_stock_forecast(db: Session, cabinet_id: str | None = None, days_back: int = 30):
    """Прогноз остатков на 30 дней на основе скорости продаж."""
    from sqlalchemy import func, case
    from app.models import Stock, Sale, ShelfMetric

    threshold = datetime.now() - timedelta(days=days_back)

    # 1. Получаем текущие остатки по товарам (aggregated across warehouses)
    stock_query = (
        db.query(
            Stock.cabinet_id,
            Stock.nm_id,
            func.sum(Stock.quantity).label("qty"),
            func.sum(Stock.in_way_to_client).label("in_way_to"),
            func.sum(Stock.in_way_from_client).label("in_way_from"),
        )
        .group_by(Stock.cabinet_id, Stock.nm_id)
    )
    if cabinet_id:
        stock_query = stock_query.filter(Stock.cabinet_id == cabinet_id)
    stocks = {row.nm_id: row for row in stock_query.all()}

    # 2. Средняя скорость продаж в день за последние N дней
    velocity_query = (
        db.query(
            Sale.cabinet_id,
            Sale.nm_id,
            func.count(Sale.srid).label("total_sales"),
        )
        .filter(Sale.date >= threshold)
        .group_by(Sale.cabinet_id, Sale.nm_id)
    )
    if cabinet_id:
        velocity_query = velocity_query.filter(Sale.cabinet_id == cabinet_id)
    velocities = {row.nm_id: row.total_sales / days_back for row in velocity_query.all()}

    # 3. Данные из ShelfMetric для названий и доп. информации
    shelf_query = db.query(ShelfMetric).distinct(ShelfMetric.nm_id, ShelfMetric.cabinet_id)
    if cabinet_id:
        shelf_query = shelf_query.filter(ShelfMetric.cabinet_id == cabinet_id)
    shelf_data = {}
    for r in shelf_query.limit(50000).all():
        key = (r.cabinet_id, r.nm_id)
        if key not in shelf_data:
            shelf_data[key] = r

    # 4. Формируем результат
    mapping = load_token_mapping()
    result = []
    for nm_id, stock_row in stocks.items():
        vel = velocities.get(nm_id, 0)
        current_stock = (stock_row.qty or 0) + (stock_row.in_way_to or 0) - (stock_row.in_way_from or 0)
        if current_stock < 0:
            current_stock = 0

        dos = round(current_stock / vel, 1) if vel > 0 else 999
        if dos < 7:
            dos_status = "red"
        elif dos < 14:
            dos_status = "yellow"
        else:
            dos_status = "green"

        # Прогнозная дата заполнения
        if vel > 0:
            forecast_days = int(current_stock / vel)
            forecast_date = (datetime.now() + timedelta(days=forecast_days)).strftime("%Y-%m-%d")
        else:
            forecast_date = None

        # Sparkline: остатки на 30 дней
        forecast_curve = []
        for d in range(31):
            remaining = current_stock - vel * d
            forecast_curve.append(max(0, round(remaining, 1)))

        # Имя товара из shelf_data
        shelf = shelf_data.get((stock_row.cabinet_id, nm_id))
        product_name = shelf.product_name if shelf else ""
        vendor_code = shelf.vendor_code if shelf else ""

        result.append({
            "cabinet_id": stock_row.cabinet_id,
            "seller_name": mapping.get(stock_row.cabinet_id, stock_row.cabinet_id[:8]),
            "nm_id": nm_id,
            "vendor_code": vendor_code,
            "product_name": product_name,
            "current_stock": current_stock,
            "velocity": round(vel, 2),
            "dos": dos,
            "dos_status": dos_status,
            "forecast_date": forecast_date,
            "forecast_curve": forecast_curve,
        })

    result.sort(key=lambda x: x["dos"])
    return result
```

- [ ] **Step 2: Verify syntax**

Run: `cd /home/wbuser/wb_sync && source venv/bin/activate && python -c "import ast; ast.parse(open('app/crud.py').read()); print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
cd /home/wbuser/wb_sync && git add app/crud.py && git commit -m "feat: add get_stock_forecast() CRUD function"
```

---

### Task 2: Backend — Unit Economics SQL + CRUD

**Covers:** [S3]

**Files:**
- Modify: `app/crud.py`

- [ ] **Step 1: Add `get_unit_economics()` function to crud.py**

Add after `get_stock_forecast()`:

```python
# -------------------------
# Unit Economics (Юнит-экономика)
# -------------------------
def get_unit_economics(db: Session, cabinet_id: str | None = None, days_back: int = 30):
    """Юнит-экономика по каждому SKU: выручка, расходы, чистая прибыль, маржа, ROMI."""
    from sqlalchemy import func
    from app.models import SalesReport, AdCampaignStats, ShelfMetric

    threshold = datetime.now() - timedelta(days=days_back)

    # 1. Агрегация финансов из SalesReport по nm_id
    report_query = (
        db.query(
            SalesReport.cabinet_id,
            SalesReport.nm_id,
            SalesReport.sa_name.label("vendor_code"),
            SalesReport.subject_name,
            SalesReport.brand_name,
            func.sum(SalesReport.quantity).label("total_quantity"),
            func.sum(SalesReport.retail_price_withdisc_rub).label("total_revenue"),
            func.sum(SalesReport.ppvz_for_pay).label("total_for_pay"),
            func.sum(SalesReport.ppvz_sales_commission).label("total_commission"),
            func.sum(SalesReport.delivery_rub).label("total_delivery"),
            func.sum(SalesReport.storage_fee).label("total_storage"),
            func.sum(SalesReport.penalty).label("total_penalty"),
            func.sum(SalesReport.acceptance).label("total_acceptance"),
            func.sum(SalesReport.acquiring_fee).label("total_acquiring"),
        )
        .filter(SalesReport.sale_dt >= threshold)
        .group_by(SalesReport.cabinet_id, SalesReport.nm_id, SalesReport.sa_name, SalesReport.subject_name, SalesReport.brand_name)
    )
    if cabinet_id:
        report_query = report_query.filter(SalesReport.cabinet_id == cabinet_id)

    report_data = {}
    for row in report_query.limit(50000).all():
        report_data[(row.cabinet_id, row.nm_id)] = {
            "cabinet_id": row.cabinet_id,
            "nm_id": row.nm_id,
            "vendor_code": row.vendor_code or "",
            "subject_name": row.subject_name or "",
            "brand_name": row.brand_name or "",
            "quantity": row.total_quantity or 0,
            "revenue": round(float(row.total_revenue or 0), 2),
            "for_pay": round(float(row.total_for_pay or 0), 2),
            "commission": round(float(row.total_commission or 0), 2),
            "delivery": round(float(row.total_delivery or 0), 2),
            "storage": round(float(row.total_storage or 0), 2),
            "penalty": round(float(row.total_penalty or 0), 2),
            "acceptance": round(float(row.total_acceptance or 0), 2),
            "acquiring": round(float(row.total_acquiring or 0), 2),
        }

    # 2. Расходы на рекламу по nm_id (из AdCampaignStats)
    ad_query = (
        db.query(
            AdCampaignStats.cabinet_id,
            AdCampaignStats.nm_id,
            func.sum(AdCampaignStats.spend).label("total_ad_spend"),
            func.sum(AdCampaignStats.orders).label("total_ad_orders"),
        )
        .filter(AdCampaignStats.date >= threshold)
        .group_by(AdCampaignStats.cabinet_id, AdCampaignStats.nm_id)
    )
    if cabinet_id:
        ad_query = ad_query.filter(AdCampaignStats.cabinet_id == cabinet_id)

    ad_data = {}
    for row in ad_query.limit(50000).all():
        ad_data[(row.cabinet_id, row.nm_id)] = {
            "ad_spend": round(float(row.total_ad_spend or 0), 2),
            "ad_orders": row.total_ad_orders or 0,
        }

    # 3. ShelfMetric для названий товаров
    shelf_query = db.query(ShelfMetric).distinct(ShelfMetric.nm_id, ShelfMetric.cabinet_id)
    if cabinet_id:
        shelf_query = shelf_query.filter(ShelfMetric.cabinet_id == cabinet_id)
    shelf_names = {}
    for r in shelf_query.limit(50000).all():
        key = (r.cabinet_id, r.nm_id)
        if key not in shelf_names:
            shelf_names[key] = {"product_name": r.product_name or "", "vendor_code": r.vendor_code or ""}

    # 4. Формируем результат с расчётом метрик
    mapping = load_token_mapping()
    result = []
    for key, report in report_data.items():
        cabinet_id_r, nm_id = key
        ad = ad_data.get(key, {"ad_spend": 0, "ad_orders": 0})
        shelf = shelf_names.get(key, {"product_name": "", "vendor_code": ""})

        revenue = report["revenue"]
        for_pay = report["for_pay"]
        total_expenses = (
            report["delivery"] + report["storage"] + report["penalty"] +
            report["acceptance"] + report["acquiring"] + ad["ad_spend"]
        )
        net_profit = for_pay - total_expenses
        margin_percent = round((net_profit / revenue * 100), 1) if revenue > 0 else 0

        # ROMI = (Прибыль - Расходы на рекламу) / Расходы на рекламу * 100
        romi = round(((net_profit - ad["ad_spend"]) / ad["ad_spend"] * 100), 1) if ad["ad_spend"] > 0 else 0

        # CPA = Расходы на рекламу / Заказы с рекламы
        cpa = round(ad["ad_spend"] / ad["ad_orders"], 0) if ad["ad_orders"] > 0 else 0

        # Срок окупаемости: AdSpend / (NetProfit / Days)
        daily_profit = net_profit / days_back if days_back > 0 else 0
        payback_days = round(ad["ad_spend"] / daily_profit, 1) if daily_profit > 0 else 0

        # LTV 30 дней
        ltv_30d = round(net_profit * (30 / days_back), 0) if days_back > 0 else 0

        # Sparkline: прибыль по дням (агрегация из SalesReport)
        # Упрощённо: равномерное распределение по дням
        profit_per_day = round(net_profit / days_back, 0) if days_back > 0 else 0
        profit_curve = [round(profit_per_day * (d + 1), 0) for d in range(min(days_back, 30))]

        result.append({
            "cabinet_id": cabinet_id_r,
            "seller_name": mapping.get(cabinet_id_r, cabinet_id_r[:8]),
            "nm_id": nm_id,
            "vendor_code": shelf["vendor_code"] or report["vendor_code"],
            "product_name": shelf["product_name"],
            "subject_name": report["subject_name"],
            "brand_name": report["brand_name"],
            "quantity": report["quantity"],
            "revenue": revenue,
            "for_pay": for_pay,
            "commission": report["commission"],
            "delivery": report["delivery"],
            "storage": report["storage"],
            "penalty": report["penalty"],
            "acceptance": report["acceptance"],
            "acquiring": report["acquiring"],
            "ad_spend": ad["ad_spend"],
            "ad_orders": ad["ad_orders"],
            "net_profit": net_profit,
            "margin_percent": margin_percent,
            "romi": romi,
            "cpa": cpa,
            "payback_days": payback_days,
            "ltv_30d": ltv_30d,
            "profit_curve": profit_curve,
        })

    result.sort(key=lambda x: x["net_profit"], reverse=True)
    return result
```

- [ ] **Step 2: Verify syntax**

Run: `cd /home/wbuser/wb_sync && source venv/bin/activate && python -c "import ast; ast.parse(open('app/crud.py').read()); print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
cd /home/wbuser/wb_sync && git add app/crud.py && git commit -m "feat: add get_unit_economics() CRUD function"
```

---

### Task 3: Backend — API Endpoints

**Covers:** [S2, S3]

**Files:**
- Modify: `app/main.py`

- [ ] **Step 1: Add imports in main.py**

Find the existing imports block (around line 28-33) and add `get_stock_forecast, get_unit_economics` to the crud import:

```python
from app.crud import (
    ...
    get_stock_forecast, get_unit_economics,
)
```

- [ ] **Step 2: Add `/api/dashboard/stock-forecast` endpoint**

Add before the `# =====================` separator at the end of main.py:

```python
# =====================
# STOCK FORECAST & UNIT ECONOMICS
# =====================

@app.get("/api/dashboard/stock-forecast")
def dashboard_stock_forecast(
    days_back: int = Query(30, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """Прогноз остатков на 30 дней."""
    cabinet_id = request.query_params.get("cabinet_id") or None
    return get_stock_forecast(db, cabinet_id, days_back)
```

- [ ] **Step 3: Add `/api/dashboard/unit-economics` endpoint**

```python
@app.get("/api/dashboard/unit-economics")
def dashboard_unit_economics(
    days_back: int = Query(30, ge=1, le=90),
    db: Session = Depends(get_db),
):
    """Юнит-экономика по каждому SKU."""
    cabinet_id = request.query_params.get("cabinet_id") or None
    return get_unit_economics(db, cabinet_id, days_back)
```

- [ ] **Step 4: Add `Request` import if not present**

Check if `from starlette.requests import Request` is in the imports. If not, add it. Alternatively, use a simpler approach without request.query_params — just pass cabinet_id as a query param:

```python
@app.get("/api/dashboard/stock-forecast")
def dashboard_stock_forecast(
    days_back: int = Query(30, ge=1, le=90),
    cabinet_id: str = Query(None),
    db: Session = Depends(get_db),
):
    """Прогноз остатков на 30 дней."""
    return get_stock_forecast(db, cabinet_id, days_back)


@app.get("/api/dashboard/unit-economics")
def dashboard_unit_economics(
    days_back: int = Query(30, ge=1, le=90),
    cabinet_id: str = Query(None),
    db: Session = Depends(get_db),
):
    """Юнит-экономика по каждому SKU."""
    return get_unit_economics(db, cabinet_id, days_back)
```

- [ ] **Step 5: Verify syntax**

Run: `cd /home/wbuser/wb_sync && source venv/bin/activate && python -c "import ast; ast.parse(open('app/main.py').read()); print('OK')"`

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
cd /home/wbuser/wb_sync && git add app/main.py && git commit -m "feat: add stock-forecast and unit-economics API endpoints"
```

---

### Task 4: Frontend — Stock Forecast Tab

**Covers:** [S4]

**Files:**
- Create: `static/tabs/stock-forecast.html`

- [ ] **Step 1: Create stock-forecast.html**

Create `static/tabs/stock-forecast.html`:

```html
<!-- ============================================================
     TAB: ПРОГНОЗ ОСТАТКОВ
     ============================================================ -->
<div id="stockForecastTab">
  <div class="summary-grid section-mb" id="sfMetrics"></div>

  <div class="card">
    <div class="section-title">Прогноз остатков на 30 дней</div>
    <div class="filters">
      <input class="filter-input" id="sfSearch" placeholder="Артикул / товар..." oninput="sfFilter()">
      <select class="filter-select" id="sfStatusFilter" onchange="sfFilter()">
        <option value="">Все статусы</option>
        <option value="red">Критично (&lt; 7 дней)</option>
        <option value="yellow">Внимание (7-14 дней)</option>
        <option value="green">Норма (&gt; 14 дней)</option>
      </select>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th onclick="sfSort('seller_name')">КАБИНЕТ ↕</th>
          <th onclick="sfSort('nm_id')">АРТ WB ↕</th>
          <th onclick="sfSort('vendor_code')">АРТ ПОСТАВЩИКА ↕</th>
          <th onclick="sfSort('product_name')">ТОВАР ↕</th>
          <th onclick="sfSort('current_stock')">ОСТАТОК ↕</th>
          <th onclick="sfSort('velocity')">СКОРОСТЬ/ДЕНЬ ↕</th>
          <th onclick="sfSort('dos')">DOS ↕</th>
          <th onclick="sfSort('forecast_date')">ПРОГНОЗ ↕</th>
          <th>КРИВАЯ</th>
        </tr></thead>
        <tbody id="sfBody"></tbody>
      </table>
    </div>
    <div class="pagination" id="sfPagination"></div>
  </div>
</div>

<script>
(function() {
  let data = [], filtered = [], page = 1;
  const PER = 50;
  let sortCol = 'dos', sortDir = 1;

  async function sfLoad() {
    document.getElementById('sfBody').innerHTML = '';
    try {
      const res = await fetch(`/api/dashboard/stock-forecast?days_back=${WB.period}`);
      data = await res.json();
    } catch(e) { data = []; }
    sfFilter();
    renderMetrics();
  }
  window.sfLoad = sfLoad;

  function sfFilter() {
    const search = (document.getElementById('sfSearch')?.value || '').toLowerCase();
    const status = document.getElementById('sfStatusFilter')?.value || '';
    filtered = data.filter(r => {
      if (WB.cabinet && r.cabinet_id !== WB.cabinet) return false;
      if (status && r.dos_status !== status) return false;
      if (search && !`${r.nm_id}`.includes(search) && !`${r.vendor_code||''}`.toLowerCase().includes(search) && !`${r.product_name||''}`.toLowerCase().includes(search)) return false;
      return true;
    });
    sortData();
  }
  window.sfFilter = sfFilter;

  function sfSort(col) {
    if (sortCol === col) sortDir *= -1; else { sortCol = col; sortDir = 1; }
    sortData();
  }
  window.sfSort = sfSort;

  function sortData() {
    filtered.sort((a, b) => {
      let va = a[sortCol], vb = b[sortCol];
      if (va == null) va = sortDir > 0 ? Infinity : -Infinity;
      if (vb == null) vb = sortDir > 0 ? Infinity : -Infinity;
      if (typeof va === 'string') return va.localeCompare(vb) * sortDir;
      return (va - vb) * sortDir;
    });
    page = 1;
    render();
  }

  function renderMetrics() {
    const m = document.getElementById('sfMetrics');
    if (!m) return;
    const d = WB.cabinet ? data.filter(r => r.cabinet_id === WB.cabinet) : data;
    const red = d.filter(r => r.dos_status === 'red').length;
    const yellow = d.filter(r => r.dos_status === 'yellow').length;
    const green = d.filter(r => r.dos_status === 'green').length;
    m.innerHTML = `
      <div class="card metric-card red"><div class="metric-label">КРИТИЧНО</div><div class="metric-value">${red}</div><div class="metric-sub">&lt; 7 дней</div></div>
      <div class="card metric-card yellow"><div class="metric-label">ВНИМАНИЕ</div><div class="metric-value">${yellow}</div><div class="metric-sub">7-14 дней</div></div>
      <div class="card metric-card green"><div class="metric-label">НОРМА</div><div class="metric-value">${green}</div><div class="metric-sub">&gt; 14 дней</div></div>
      <div class="card metric-card teal"><div class="metric-label">ВСЕГО</div><div class="metric-value">${d.length}</div><div class="metric-sub">товаров</div></div>
    `;
  }

  function renderSparkline(curve, color) {
    if (!curve || !curve.length) return '';
    const max = Math.max(...curve, 1);
    const w = 80, h = 20;
    const step = w / (curve.length - 1);
    const points = curve.map((v, i) => `${i * step},${h - (v / max) * h}`).join(' ');
    return `<svg width="${w}" height="${h}" style="display:block;"><polyline points="${points}" fill="none" stroke="${color}" stroke-width="1.5"/></svg>`;
  }

  function dosColor(status) {
    if (status === 'red') return 'var(--red)';
    if (status === 'yellow') return 'var(--accent2)';
    return 'var(--green)';
  }

  function render() {
    const body = document.getElementById('sfBody');
    if (!body) return;
    const slice = filtered.slice((page-1)*PER, page*PER);
    if (!filtered.length) {
      body.innerHTML = `<tr><td colspan="9" style="text-align:center;color:var(--text3);padding:30px;">Нет данных</td></tr>`;
      document.getElementById('sfPagination').innerHTML = '';
      return;
    }
    body.innerHTML = slice.map(r => `<tr class="fade-in">
      <td><span class="badge badge-orange">${r.seller_name || '—'}</span></td>
      <td class="td-mono">${r.nm_id}</td>
      <td>${r.vendor_code || '—'}</td>
      <td>${r.product_name || '—'}</td>
      <td class="td-mono" style="font-weight:bold">${fmt(r.current_stock)}</td>
      <td class="td-mono">${r.velocity}</td>
      <td class="td-mono" style="color:${dosColor(r.dos_status)};font-weight:bold">${r.dos} дн</td>
      <td class="td-mono">${r.forecast_date || '—'}</td>
      <td>${renderSparkline(r.forecast_curve, dosColor(r.dos_status))}</td>
    </tr>`).join('');
    renderPagination('sfPagination', filtered.length, PER, page, p => { page = p; render(); });
  }

  window.addEventListener('wb:tab-activated:stock-forecast', sfLoad);
  window.addEventListener('wb:cabinet-changed', () => { if (data.length) { sfFilter(); renderMetrics(); } });
})();
</script>
```

- [ ] **Step 2: Commit**

```bash
cd /home/wbuser/wb_sync && git add static/tabs/stock-forecast.html && git commit -m "feat: add stock forecast dashboard tab"
```

---

### Task 5: Frontend — Unit Economics Tab

**Covers:** [S4]

**Files:**
- Create: `static/tabs/unit-economics.html`

- [ ] **Step 1: Create unit-economics.html**

Create `static/tabs/unit-economics.html`:

```html
<!-- ============================================================
     TAB: ЮНИТ-ЭКОНОМИКА
     ============================================================ -->
<div id="unitEconomicsTab">
  <div class="summary-grid section-mb" id="ueMetrics"></div>

  <div class="card section-mb">
    <div class="section-title">Юнит-экономика по товарам</div>
    <div class="filters">
      <input class="filter-input" id="ueSearch" placeholder="Артикул / товар..." oninput="ueFilter()">
      <select class="filter-select" id="ueMarginFilter" onchange="ueFilter()">
        <option value="">Все маржа</option>
        <option value="high">Высокая (&gt; 20%)</option>
        <option value="mid">Средняя (10-20%)</option>
        <option value="low">Низкая (&lt; 10%)</option>
        <option value="negative">Убыточные</option>
      </select>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th onclick="ueSort('seller_name')">КАБИНЕТ ↕</th>
          <th onclick="ueSort('nm_id')">АРТ WB ↕</th>
          <th onclick="ueSort('vendor_code')">АРТ ПОСТАВЩИКА ↕</th>
          <th onclick="ueSort('product_name')">ТОВАР ↕</th>
          <th onclick="ueSort('revenue')">ВЫРУЧКА ↕</th>
          <th onclick="ueSort('for_pay')">К ЗАЧЁТУ ↕</th>
          <th onclick="ueSort('net_profit')">ПРИБЫЛЬ ↕</th>
          <th onclick="ueSort('margin_percent')">МАРЖА ↕</th>
          <th onclick="ueSort('romi')">ROMI ↕</th>
          <th onclick="ueSort('cpa')">CPA ↕</th>
          <th onclick="ueSort('payback_days')">ОКУП. ↕</th>
          <th>ГРАФИК</th>
        </tr></thead>
        <tbody id="ueBody"></tbody>
      </table>
    </div>
    <div class="pagination" id="uePagination"></div>
  </div>

  <div class="card" id="ueDetail" style="display:none;">
    <div class="section-title">Детализация товара</div>
    <div id="ueDetailContent"></div>
  </div>
</div>

<script>
(function() {
  let data = [], filtered = [], page = 1;
  const PER = 50;
  let sortCol = 'net_profit', sortDir = -1;

  async function ueLoad() {
    document.getElementById('ueBody').innerHTML = '';
    try {
      const res = await fetch(`/api/dashboard/unit-economics?days_back=${WB.period}`);
      data = await res.json();
    } catch(e) { data = []; }
    ueFilter();
    renderMetrics();
  }
  window.ueLoad = ueLoad;

  function ueFilter() {
    const search = (document.getElementById('ueSearch')?.value || '').toLowerCase();
    const marginFilter = document.getElementById('ueMarginFilter')?.value || '';
    filtered = data.filter(r => {
      if (WB.cabinet && r.cabinet_id !== WB.cabinet) return false;
      if (marginFilter === 'high' && r.margin_percent <= 20) return false;
      if (marginFilter === 'mid' && (r.margin_percent < 10 || r.margin_percent > 20)) return false;
      if (marginFilter === 'low' && (r.margin_percent < 0 || r.margin_percent >= 10)) return false;
      if (marginFilter === 'negative' && r.margin_percent >= 0) return false;
      if (search && !`${r.nm_id}`.includes(search) && !`${r.vendor_code||''}`.toLowerCase().includes(search) && !`${r.product_name||''}`.toLowerCase().includes(search)) return false;
      return true;
    });
    sortData();
  }
  window.ueFilter = ueFilter;

  function ueSort(col) {
    if (sortCol === col) sortDir *= -1; else { sortCol = col; sortDir = -1; }
    sortData();
  }
  window.ueSort = ueSort;

  function sortData() {
    filtered.sort((a, b) => {
      let va = a[sortCol], vb = b[sortCol];
      if (va == null) va = 0; if (vb == null) vb = 0;
      if (typeof va === 'string') return va.localeCompare(vb) * sortDir;
      return (va - vb) * sortDir;
    });
    page = 1;
    render();
  }

  function renderMetrics() {
    const m = document.getElementById('ueMetrics');
    if (!m) return;
    const d = WB.cabinet ? data.filter(r => r.cabinet_id === WB.cabinet) : data;
    const totalProfit = d.reduce((s, r) => s + r.net_profit, 0);
    const avgMargin = d.length ? (d.reduce((s, r) => s + r.margin_percent, 0) / d.length).toFixed(1) : 0;
    const totalAdSpend = d.reduce((s, r) => s + r.ad_spend, 0);
    const avgROMI = totalAdSpend > 0 ? ((totalProfit - totalAdSpend) / totalAdSpend * 100).toFixed(0) : 0;
    const avgCPA = d.reduce((s, r) => s + r.cpa, 0) / (d.filter(r => r.cpa > 0).length || 1);
    m.innerHTML = `
      <div class="card metric-card green"><div class="metric-label">ПРИБЫЛЬ</div><div class="metric-value">${fmtMoney(Math.round(totalProfit))}</div></div>
      <div class="card metric-card teal"><div class="metric-label">СР. МАРЖА</div><div class="metric-value">${avgMargin}%</div></div>
      <div class="card metric-card"><div class="metric-label">ROMI</div><div class="metric-value" style="color:${avgROMI >= 0 ? 'var(--green)' : 'var(--red)'}">${avgROMI}%</div></div>
      <div class="card metric-card orange"><div class="metric-label">СР. CPA</div><div class="metric-value">${fmtMoney(Math.round(avgCPA))}</div></div>
      <div class="card metric-card"><div class="metric-label">ТОВАРОВ</div><div class="metric-value">${d.length}</div></div>
    `;
  }

  function marginColor(m) {
    if (m > 20) return 'var(--green)';
    if (m > 10) return 'var(--accent2)';
    if (m >= 0) return 'var(--accent)';
    return 'var(--red)';
  }

  function renderSparkline(curve, color) {
    if (!curve || !curve.length) return '';
    const max = Math.max(...curve.map(Math.abs), 1);
    const w = 80, h = 20;
    const step = w / (curve.length - 1);
    const points = curve.map((v, i) => `${i * step},${h - ((v + max) / (2 * max)) * h}`).join(' ');
    return `<svg width="${w}" height="${h}" style="display:block;"><polyline points="${points}" fill="none" stroke="${color}" stroke-width="1.5"/></svg>`;
  }

  function render() {
    const body = document.getElementById('ueBody');
    if (!body) return;
    const slice = filtered.slice((page-1)*PER, page*PER);
    if (!filtered.length) {
      body.innerHTML = `<tr><td colspan="12" style="text-align:center;color:var(--text3);padding:30px;">Нет данных</td></tr>`;
      document.getElementById('uePagination').innerHTML = '';
      return;
    }
    body.innerHTML = slice.map((r, i) => `<tr class="fade-in" style="cursor:pointer" onclick="showDetail(${(page-1)*PER + i})">
      <td><span class="badge badge-orange">${r.seller_name || '—'}</span></td>
      <td class="td-mono">${r.nm_id}</td>
      <td>${r.vendor_code || '—'}</td>
      <td>${r.product_name || '—'}</td>
      <td class="td-mono">${fmtMoney(Math.round(r.revenue))}</td>
      <td class="td-mono">${fmtMoney(Math.round(r.for_pay))}</td>
      <td class="td-mono" style="color:${r.net_profit >= 0 ? 'var(--green)' : 'var(--red)'};font-weight:bold">${fmtMoney(Math.round(r.net_profit))}</td>
      <td class="td-mono" style="color:${marginColor(r.margin_percent)};font-weight:bold">${r.margin_percent}%</td>
      <td class="td-mono">${r.ad_spend > 0 ? r.romi + '%' : '—'}</td>
      <td class="td-mono">${r.cpa > 0 ? fmtMoney(Math.round(r.cpa)) : '—'}</td>
      <td class="td-mono">${r.payback_days > 0 ? r.payback_days + ' дн' : '—'}</td>
      <td>${renderSparkline(r.profit_curve, marginColor(r.margin_percent))}</td>
    </tr>`).join('');
    renderPagination('uePagination', filtered.length, PER, page, p => { page = p; render(); });
  }

  window.showDetail = function(idx) {
    const r = filtered[idx];
    if (!r) return;
    const el = document.getElementById('ueDetail');
    const content = document.getElementById('ueDetailContent');
    if (!el || !content) return;
    el.style.display = 'block';
    content.innerHTML = `
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;">
        <div>
          <div style="font-family:'IBM Plex Mono',monospace;font-size:12px;color:var(--text2);margin-bottom:12px;">
            <div><b>${r.product_name || r.nm_id}</b></div>
            <div style="margin-top:4px;">АРТ: ${r.vendor_code || '—'} | WB ID: ${r.nm_id}</div>
          </div>
          <div style="font-family:'IBM Plex Mono',monospace;font-size:12px;">
            <div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--border);"><span style="color:var(--text2)">Выручка</span><span>${fmtMoney(Math.round(r.revenue))}</span></div>
            <div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--border);"><span style="color:var(--text2)">- Комиссия WB</span><span style="color:var(--red)">-${fmtMoney(Math.round(r.commission))}</span></div>
            <div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--border);"><span style="color:var(--text2)">- Доставка</span><span style="color:var(--red)">-${fmtMoney(Math.round(r.delivery))}</span></div>
            <div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--border);"><span style="color:var(--text2)">- Хранение</span><span style="color:var(--red)">-${fmtMoney(Math.round(r.storage))}</span></div>
            <div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--border);"><span style="color:var(--text2)">- Штрафы</span><span style="color:var(--red)">-${fmtMoney(Math.round(r.penalty))}</span></div>
            <div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--border);"><span style="color:var(--text2)">- Приёмка</span><span style="color:var(--red)">-${fmtMoney(Math.round(r.acceptance))}</span></div>
            <div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--border);"><span style="color:var(--text2)">- Эквайринг</span><span style="color:var(--red)">-${fmtMoney(Math.round(r.acquiring))}</span></div>
            <div style="display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--border);"><span style="color:var(--text2)">- Реклама</span><span style="color:var(--red)">-${fmtMoney(Math.round(r.ad_spend))}</span></div>
            <div style="display:flex;justify-content:space-between;padding:6px 0;border-top:2px solid var(--accent);font-weight:bold;margin-top:4px;"><span>Чистая прибыль</span><span style="color:${r.net_profit >= 0 ? 'var(--green)' : 'var(--red)'}">${fmtMoney(Math.round(r.net_profit))}</span></div>
          </div>
        </div>
        <div>
          <div style="font-family:'IBM Plex Mono',monospace;font-size:12px;">
            <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border);"><span style="color:var(--text2)">Маржинальность</span><span style="color:${marginColor(r.margin_percent)};font-weight:bold">${r.margin_percent}%</span></div>
            <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border);"><span style="color:var(--text2)">ROMI</span><span style="color:${r.romi >= 0 ? 'var(--green)' : 'var(--red)'}">${r.ad_spend > 0 ? r.romi + '%' : '—'}</span></div>
            <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border);"><span style="color:var(--text2)">CPA</span><span>${r.cpa > 0 ? fmtMoney(Math.round(r.cpa)) : '—'}</span></div>
            <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border);"><span style="color:var(--text2)">Срок окупаемости</span><span>${r.payback_days > 0 ? r.payback_days + ' дней' : '—'}</span></div>
            <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border);"><span style="color:var(--text2)">LTV (30 дней)</span><span style="color:var(--accent)">${fmtMoney(Math.round(r.ltv_30d))}</span></div>
            <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border);"><span style="color:var(--text2)">Продано (шт)</span><span>${fmt(r.quantity)}</span></div>
            <div style="display:flex;justify-content:space-between;padding:6px 0;"><span style="color:var(--text2)">Заказы с рекламы</span><span>${fmt(r.ad_orders)}</span></div>
          </div>
        </div>
      </div>
    `;
    el.scrollIntoView({ behavior: 'smooth' });
  };

  window.addEventListener('wb:tab-activated:unit-economics', ueLoad);
  window.addEventListener('wb:cabinet-changed', () => { if (data.length) { ueFilter(); renderMetrics(); } });
})();
</script>
```

- [ ] **Step 2: Commit**

```bash
cd /home/wbuser/wb_sync && git add static/tabs/unit-economics.html && git commit -m "feat: add unit economics dashboard tab"
```

---

### Task 6: Frontend — Register Tabs

**Covers:** [S4]

**Files:**
- Modify: `static/dashboard.html`
- Modify: `static/js/tabs.js`

- [ ] **Step 1: Add tab buttons in dashboard.html**

In `static/dashboard.html`, add two new tab buttons after the existing "abcxyz" button (around line 65):

```html
  <button class="tab-btn" data-tab="stock-forecast" onclick="switchTab('stock-forecast')">📉 Прогноз</button>
  <button class="tab-btn" data-tab="unit-economics" onclick="switchTab('unit-economics')">💰 Юнит-экономика</button>
```

- [ ] **Step 2: Add tab content divs in dashboard.html**

In `static/dashboard.html`, add two new content divs after the existing "tab-abcxyz" div (around line 81):

```html
  <div id="tab-stock-forecast" class="tab-content"></div>
  <div id="tab-unit-economics" class="tab-content"></div>
```

- [ ] **Step 3: Register tabs in tabs.js**

In `static/js/tabs.js`, add entries to the TAB_SRCS object (around line 17):

```javascript
  'stock-forecast': '/static/tabs/stock-forecast.html',
  'unit-economics': '/static/tabs/unit-economics.html',
```

- [ ] **Step 4: Commit**

```bash
cd /home/wbuser/wb_sync && git add static/dashboard.html static/js/tabs.js && git commit -m "feat: register stock-forecast and unit-economics tabs"
```

---

### Task 7: Integration Testing

**Covers:** [S2, S3, S4]

**Files:** None (verification only)

- [ ] **Step 1: Restart uvicorn**

```bash
cd /home/wbuser/wb_sync && pkill -f "uvicorn app.main" 2>/dev/null; sleep 1; nohup venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 > /tmp/wb-sync.log 2>&1 &
```

- [ ] **Step 2: Test stock-forecast endpoint**

```bash
sleep 3 && curl -s "http://localhost:8000/api/dashboard/stock-forecast?days_back=30" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Items: {len(d)}'); print(json.dumps(d[0], indent=2) if d else 'No data')"
```

Expected: JSON with forecast data for each SKU

- [ ] **Step 3: Test unit-economics endpoint**

```bash
curl -s "http://localhost:8000/api/dashboard/unit-economics?days_back=30" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Items: {len(d)}'); print(json.dumps(d[0], indent=2) if d else 'No data')"
```

Expected: JSON with unit economics data for each SKU

- [ ] **Step 4: Verify dashboard page loads**

```bash
curl -s -o /dev/null -w "%{http_code}" "http://localhost:8000/dashboard"
```

Expected: `200`

- [ ] **Step 5: Verify new tab files load**

```bash
curl -s -o /dev/null -w "%{http_code}" "http://localhost:8000/static/tabs/stock-forecast.html" && echo "" && curl -s -o /dev/null -w "%{http_code}" "http://localhost:8000/static/tabs/unit-economics.html"
```

Expected: `200 200`

---

## Self-Review

- [ ] **Spec coverage:** [S1] context — covered by design doc. [S2] stock forecast — Tasks 1, 3, 4. [S3] unit economics — Tasks 2, 3, 5. [S4] visualization — Tasks 4, 5, 6. [S5] architecture — file structure section. [S6] requirements — Tasks 1-7. [S7] plan — this document.
- [ ] **Placeholder scan:** All steps contain complete code blocks. No TBD/TODO.
- [ ] **Type consistency:** `get_stock_forecast(db, cabinet_id, days_back)` matches CRUD → endpoint → frontend. `get_unit_economics(db, cabinet_id, days_back)` same pattern.
