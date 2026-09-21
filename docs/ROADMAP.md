# WB Sync — Стратегический план развития

> Дата анализа: 2026-06-18
> Автор: Business Analyst (автоматический анализ)
> Статус: УТВЕРЖДЁН

---

## Текущее состояние проекта

**WB Sync** — сервис синхронизации данных с маркетплейса Wildberries.
Stack: Python 3.12, FastAPI, SQLAlchemy 2.x, PostgreSQL, APScheduler, httpx, uvloop.
Деплой: VPS SmartApe, systemd wb-sync.service.

| Компонент | Статус | Объём |
|---|---|---|
| WB API источники | 8 из 8+ | content, statistics, finance, analytics v1/v2/v3, advert, prices, returns-api, suppliers (tariffs) |
| Data модели | 31 | Полное покрытие текущих источников + RNP + Auth + Logistics |
| API эндпоинты | 35+ | 14 raw POST + 21 dashboard GET + RNP CRUD |
| Вкладки дашборда | 19 | Аналитика (9) + Данные (10) |
| Unit-тесты | 39 ✅ | wb_client (нормализация finance-api), rnp_calc (день/агрегация), crud (parse_date/токены); запускаются без БД |
| Синхронизация | ⏸ Отключена | APScheduler выключен флагом `SCHEDULER_ENABLED=false`; включается одной переменной в `.env` |
| Авторизация | Базовая | Cookie-based, 2 роли (admin/user) |
| Кабинетов в системе | 18 active + 1 skip_sync | 18 синхронизируются, 1 (ИП Чернова) исключён |

---

## Доступные WB API источники, которые мы НЕ используем

| WB API | Эндпоинт | Что даёт | Приоритет | Сложность |
|---|---|---|---|---|
| **Suppliers API** | `/api/v1/suppliers/warehouses` | Склады поставщиков, типы, логистика | 🔴 Высокий | Низкая |
| **Suppliers API** | `/api/v1/suppliers/delivery-methods` | Методы доставки, тарифы, сроки | 🔴 Высокий | Низкая |
| **Suppliers API** | `/api/v1/suppliers/acceptance` | Условия приёмки, брак | 🟡 Средний | Низкая |
| **Suppliers API** | `/api/v1/suppliers/candidates` | Кандидаты на поставку | 🟢 Низкий | Низкая |
| **Content API** | `/content/v2/get/category/list` | Категории, атрибуты, обязательные поля | 🔴 Высокий | Низкая |
| **Content API** | `/content/v2/get/cards/list` (расширенный) | Контент-оценка товаров | 🟡 Средний | Средняя |
| **Analytics API** | `/api/v2/search-report/report` | Позиции в поиске (⚠️ требует Jam-токен) | 🔴 Высокий | Высокая |
| **Analytics API** | `/api/v2/nm-report/product` | Конверсия по товарам (детальная) | 🟡 Средний | Средняя |
| **Advert API** | `/adv/v0/normquery/wordstat` | Wordstat — объём поисковых запросов | 🔴 Высокий | Средняя |
| **Advert API** | `/adv/v1/search` | Поисковые запросы кампаний | 🟡 Средний | Низкая |
| **Prices API** | `/api/v5/product/update/set` | Управление ценами программно | 🟡 Средний | Средняя |
| **Prices API** | `/api/v5/product/recommendations/list` | Рекомендованные цены WB | 🟡 Средний | Низкая |
| **Statistics API** | `/api/v5/supplier/returns` | Возвраты с детализацией | 🔴 Высокий | Низкая |
| **Statistics API** | `/api/v5/supplier/warehouse` | Движение по складам | 🟡 Средний | Средняя |
| **Chat API** | `/api/v5/consolidation` | Сообщения с покупателями | 🟡 Средний | Высокая |
| **Claims API** | `/api/v1/claims` | Претензии, возвраты, брак | 🔴 Высокий | Средняя |

---

## Приоритетные направления развития

### 🥇 ПРИОРИТЕТ 1: Закрытие критических дыр в данных

#### 1.1 Возвраты и претензии (Claims + Returns)

**Зачем**: Сейчас мы видим возвраты в SalesReport, но НЕ видим причину, кто конкретно вернул, статус обработки.

**WB API**: 
- `GET /api/v5/supplier/returns` (statistics-api) — возвраты с детализацией
- `GET /api/v1/claims` (suppliers-api) — претензии, рекламации

**Модель данных**:
```sql
CREATE TABLE returns (
    id SERIAL PRIMARY KEY,
    cabinet_id VARCHAR(32) NOT NULL,
    srid VARCHAR(50),
    nm_id INTEGER,
    supplier_article VARCHAR(100),
    reason TEXT,
    reason_code VARCHAR(20),
    status VARCHAR(50),
    quantity INTEGER,
    amount DECIMAL,
    created_at TIMESTAMP,
    processed_at TIMESTAMP,
    raw_data JSON,
    synced_at TIMESTAMP,
    UNIQUE(cabinet_id, srid)
);
```

**Вкладка**: «Возвраты» — таблица с фильтрами по причине, товару, периоду. График возвратов по дням. Топ товаров с highest return rate.

**Ценность**: Выявление проблемных товаров, контроль качества, снижение потерь.

---

#### 1.2 Позиции в поиске (Search Report)

**Зачем**: Без позиций в поиске невозможно оценить SEO-эффект рекламы и органический трафик.

**WB API**: `POST /api/v2/search-report/report` (analytics-api) ⚠️ Требует Jam-токен (403 без него)

**Модель данных**:
```sql
CREATE TABLE search_positions (
    id SERIAL PRIMARY KEY,
    cabinet_id VARCHAR(32) NOT NULL,
    nm_id INTEGER,
    query TEXT,
    position INTEGER,
    is_adv BOOLEAN DEFAULT FALSE,
    date DATE,
    raw_data JSON,
    synced_at TIMESTAMP,
    UNIQUE(cabinet_id, nm_id, query, date)
);
```

**Вкладка**: «Поисковые позиции» — трекинг позиций по ключевым словам. Динамика позиций. Сравнение органика vs реклама.

**Ценность**: Оценка ROI органического трафика, мониторинг видимости товаров.

**⚠️ Блокер**: Нужно получить Jam-токен или найти обходной путь.

---

#### 1.3 Wordstat — объёмы поисковых запросов

**Зачем**: Знать реальный спрос, а не только наши показы.

**WB API**: `POST /adv/v0/normquery/wordstat` (advert-api)

**Модель данных**:
```sql
CREATE TABLE search_volumes (
    id SERIAL PRIMARY KEY,
    query TEXT NOT NULL,
    volume INTEGER,
    date DATE,
    raw_data JSON,
    synced_at TIMESTAMP,
    UNIQUE(query, date)
);
```

**Ценность**: Понимание рынка, выбор ключевых слов для рекламы, оценка ёмкости рынка.

---

### 🥈 ПРИОРИТЕТ 2: Расширение аналитики

#### 2.1 Конкурентный анализ (Market Analytics)

**Зачем**: Видеть цены конкурентов, их динамику, долю рынка.

**Подход**: Собираем цены конкурентов по тем же категориям/товарам через content-api. Анализируем рейтинги, количество отзывов, динамику цен.

**Вкладка**: «Конкуренты» — сравнение цен, рейтингов, продаж по категориям.

---

#### 2.2 ABC/XYZ анализ продвинутый

**Текущий**: Базовый ABC/XYZ по выручке.

**Улучшение**:
- ABC по марже (а не только выручке)
- XYZ по спросу (а не только продажам)
- Комбинированный ABC-XYZ матрица с рекомендациями по управлению each segment

**Ценность**: Точечное управление ассортиментом.

---

#### 2.3 Прогноз продаж ML

**Зачем**: Автоматический прогноз на 7/14/30 дней.

**Подход**: Prophet или простая регрессия на исторических данных (у нас 40+ дней).

**Вкладка**: «Прогноз» — кривая прогноза + доверительный интервал.

**Ценность**: Планирование закупок, управление запасами.

---

### 🥉 ПРИОРИТЕТ 3: Операционная эффективность

#### 3.1 Управление ценами через API

**Зачем**: Автоматическая корректировка цен по правилам.

**WB API**: `POST /api/v5/product/update/set` (prices-api)

**Фича**: Правила:
- «если запас < 10 и маржа > 30% → снизить цену на 5%»
- «если рейтинг < 4.0 → увеличить скидку на 10%»
- «если продажи > плана → поднять цену на 3%»

**Ценность**: Максимизация выручки при минимальных запасах.

---

#### 3.2 Уведомления и алерты

**Типы алертов**:
- Товар закончился на складе (stocks_wb = 0)
- Рейтинг упал ниже 4.0
- Претензия от покупателя
- Рекламный бюджет превышен
- Возврат выше нормы (>5%)
- Заказ без предоплаты (для отслеживания)

**Каналы**: Telegram bot, Email, Webhook.

**Ценность**: Мгновенная реакция на проблемы, предотвращение потерь.

---

#### 3.3 Мульти-кабинетный дашборд

**Текущий**: Выбор кабинета в dropdown.

**Улучшение**: Сводка ВСЕХ кабинетов на одной странице:
- Общая выручка по всем кабинетам
- Суммарные запасы
- Топ-товары跨кабинетно
- Сравнение кабинетов между собой

**Ценность**: Управление бизнесом как единым целым.

---

## Технический долг и надёжность

| Задача | Описание | Приоритет | Сложность |
|---|---|---|---|
| **Rate limit queue** | Централизованная очередь запросов к WB API (сейчас分散ён по scheduler) | 🔴 | Средняя |
| **Unit-тесты** | Тесты для rnp_calc, crud, интеграционные для API | 🔴 | Средняя |
| **Alembic миграции** | Для всех изменений схемы (сейчас ad-hoc) | 🔴 | Низкая |
| **Auth → JWT** | Сейчас cookie-based. JWT позволит мобильным клиентам | 🟡 | Средняя |
| **Redis кэширование** | Для частых запросов (summary, top-products) | 🟡 | Средняя |
| **Structured logging** | JSON-логи, метрики Prometheus | 🟡 | Низкая |
| **WebSocket** | Real-time обновление метрик без перезагрузки | 🟢 | Высокая |

---

## Roadmap по кварталам

### Q3 2026 (июль—сентябрь): Фундамент данных

1. ~~**Suppliers API**: склады, методы доставки, приёмка~~ → частично: тарифы логистики (boxes/pallets/acceptance/return) загружаются, вкладка «Логистика» готова
2. **Claims + Returns**: полная цепочка возвратов — код готов, заблокировано токенами (scope «Маркетплейс»)
3. ~~**Alembic миграции** для всех моделей~~ ✅ (16 миграций, head = f4a5b6c7d8e9, модели ↔ БД синхронны)
4. ~~**Unit-тесты** для критических модулей (rnp_calc, crud)~~ ✅ (21.09.2026: 39 тестов; интеграционные для upsert_* — следующий шаг, нужна тестовая БД)
5. **Rate limit queue** (централизация)

### Q4 2026 (октябрь—декабрь): Аналитика

1. **Search positions** (решить вопрос Jam-токена)
2. **Wordstat объёмы**
3. **Прогноз продаж** (Prophet/regression)
4. **Продвинутый ABC/XYZ**
5. **Telegram алерты**

### Q1 2027 (январь—март): Автоматизация

1. **Управление ценами** через API
2. **Конкурентный анализ**
3. **Мульти-кабинетный дашборд**
4. **Redis кэширование**
5. **WebSocket обновления**

### Q2 2027 (апрель—июнь): Масштабирование

1. **JWT авторизация**
2. **Мобильный дашборд** (React Native / PWA)
3. **Экспорт данных** (Excel, PDF отчёты)
4. **Интеграция с 1С** (XML/JSON выгрузка)
5. **ML-рекомендации** по ассортименту

---

## Quick Wins (1-2 дня)

1. **Telegram-бот для алертов** — минимальная интеграция, максимальная ценность
2. **Экспорт в Excel** — кнопка «Скачать» на каждой вкладке дашборда
3. **Дневная сводка в Telegram** — автоматическое сообщение каждое утро с ключевыми метриками
4. **Кэширование summary** — memcached/Redis для главной страницы
5. **Health check мониторинг** — UptimeRobot / Healthchecks.io на `/api/health`

---

## Текущие known issues

1. **ShelfMetrics daily accumulation** — 40 дней накоплены для всех кабинетов ✅
2. **AdCampaignStats** — работает, rate limits соблюдены ✅
3. **RNP скорость** — ~15 сек на расчёт (нужно оптимизировать per-query агрегаты)
4. **Auth JWT** — сейчас cookie-based, ограничивает мобильных клиентов
5. **Search Report заблокирован** — 403 без Jam-токена
6. **Claims (возвраты)** — API `returns-api` требует scope «Маркетплейс»; у большинства кабинетов токены без этого scope
7. **chrt_id BigInteger** — WB ID карточек превысили INT4 max; исправлено 20.08.2026
8. **ItemRating v2** — API v1 deprecated (404); миграция на v2 выполнена 20.08.2026
9. **skip_sync** — механизм исключения кабинетов из синхронизации добавлен 20.08.2026
10. **Отчёт реализации: миграция на finance-api (21.09.2026)** — старый `GET statistics-api /api/v5/supplier/reportDetailByPeriod` WB вывел из эксплуатации и оставил на нём остаточную квоту (~1 запрос в 24–36 ч на аккаунт, отсюда 429 с 07.09). Загрузка переведена на `POST finance-api /api/finance/v1/sales-reports/detailed`; поля переименованы (`ppvz_for_pay`→`forPay`, `storage_fee`→`paidStorage`, `delivery_rub`→`deliveryService`, `acceptance`→`paidAcceptance`, `sa_name`→`vendorCode`, `ts_name`→`techSize`, `barcode`→`sku`, `supplier_oper_name`→`sellerOperName`, `site_country`→`country`, `ppvz_spp_prc`→`spp` и т.д.), суммы приходят строками, убраны `suppliercontract_code` и `ppvz_supplier_id`, добавлены `title`, `paidWithSocialCertificate`, `warehouseLogisticsCoeff`. Маппинг: `app/wb_client.py` → `SALES_REPORT_FIELD_MAP`, колонки БД оставлены прежними. ⚠️ **Требуется токен с категорией «Финансы»** — текущие токены её не имеют (403 «scope is not allowed»), нужно дополнить категорию в кабинете WB; пропущенные 19–21.09 догрузить backfill'ом.
   ✅ 21.09.2026: код выверен (нормализация finance-api проверена unit-тестом на примере строки, все модули импортируются). Протестированы ВСЕ 18 активных токенов реальным запросом к finance-api — **ни один не имеет категории «Финансы»** (все 403 `scope is not allowed`). Блокер целиком на стороне пользователя: в каждом WB-кабинете (Настройки → Интеграции по API) добавить категорию «Финансы» у существующего токена, затем `POST /api/sync/trigger-sales-report-backfill?days=7`. UI: на вкладке «Отчёт реализации» добавлен баннер-подсказка (показывается, если за 2 дня нет данных), в админ-панели добавлено управление токенами (вкл/выкл, skip_sync).
11. **WB токены и категории** — с 15.09.2026 WB разделяет токены по категориям: «Финансы» нужна для finance-api (отчёт реализации), «Маркетплейс» — для returns-api (возвраты/claims). Старые токены без этих категорий продолжают работать для content/statistics/analytics/advert/prices. Проверка категории: тестовый запрос к соответствующему API (см. known issue 10).

---

## Маппинг текущих данных → WB API Sources

| Функция | WB Sync Endpoint | WB API Source |
|---|---|---|
| Характеристики | POST /api/products | content-api `POST /content/v2/get/cards/list` |
| Остатки на складах | POST /api/stocks | analytics-api `POST /api/analytics/v1/stocks-report/wb-warehouses` |
| Заказы | POST /api/orders | statistics-api `GET /api/v1/supplier/orders` |
| Продажи | POST /api/sales | statistics-api `GET /api/v1/supplier/sales` |
| Цены | POST /api/prices | prices-api `GET /api/v2/list/goods/filter` |
| Отчёт реализации | POST /api/sales-report | finance-api `POST /api/finance/v1/sales-reports/detailed` |
| Витрина (подневная) | POST /api/shelf-metrics | analytics-api `POST /api/analytics/v3/sales-funnel/products` |
| Воронка (агрегат) | POST /api/funnel-metrics | analytics-api `POST /api/analytics/v3/sales-funnel/products` |
| Остатки по офисам | POST /api/stock-offices | analytics-api `POST /api/v2/stocks-report/offices` |
| Рейтинги товаров | POST /api/item-ratings | analytics-api `POST /api/analytics/v2/item-rating` |
| Рекламные кампании | POST /api/ad-campaigns | advert-api `GET /adv/v1/promotion/count` |
| Статистика рекламы | POST /api/ad-stats | advert-api `GET /adv/v3/fullstats` |
| Затраты на рекламу | POST /api/ad-expenses | advert-api `GET /adv/v1/upd` |
| Поисковые кластеры | POST /api/ad-search-clusters | advert-api `POST /adv/v0/normquery/stats` |

---

## Rate Limits (WB API)

- **content-api**: 100 req/min
- **statistics-api**: 1 req/min (orders, sales, report)
- **analytics-api**: 3 req/min (funnel, stocks, ratings)
- **advert-api**: 10 req/min (clusters), глобальный 1 req/min (fullstats, upd)
- **prices-api**: 100 req/min

---

## Использование в следующей сессии

1. Покажи этот файл на старте сессии
2. Спроси: «С какого приоритета продолжаем?»
3. Начни с конкретного пункта из Roadmap
4. При необходимости углубляйся в детали разделов

## Состояние на 21.09.2026 (сверка код ↔ БД ↔ ROADMAP)

- 31 модель ↔ 32 таблицы БД — расхождений нет; alembic head применён
- Сервис на порту 8000: health OK; тесты `pytest tests/` — 39 passed
- Данные свежие: orders до 20.09, shelf_metrics до 20.09, item_ratings до 21.09
- sales_reports: последние данные 17.09 — требуется категория «Финансы» у токенов (known issue 10)
- ad_campaign_stats: данные до 22.08 — при включении планировщика проверить лимиты advert-api
- Незакоммиченных изменений в коде нет; вне репозитория: .mimocode/ (команды/скиллы), 2 CSV (заказы ИП Брыкин), новый_проект_план.txt (план второго проекта)

---

*Последнее обновление: 2026-09-21*
