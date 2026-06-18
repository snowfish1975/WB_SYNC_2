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
| WB API источники | 5 из 8+ | content, statistics, analytics, advert, prices |
| Data модели | 18 | Полное покрытие текущих источников |
| API эндпоинты | 33+ | 14 raw POST + 19 dashboard GET + RNP CRUD |
| Вкладки дашборда | 17 | Аналитика (8) + Данные (9) |
| Синхронизация | Ежедневная | APScheduler, rate limits соблюдены |
| Авторизация | Базовая | Cookie-based, 2 роли (admin/user) |
| Кабинетов в системе | 19 | Все активные токены в wb_tokens |

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

1. **Suppliers API**: склады, методы доставки, приёмка
2. **Claims + Returns**: полная цепочка возвратов
3. **Alembic миграции** для всех моделей
4. **Unit-тесты** для критических модулей (rnp_calc, crud)
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

1. **ShelfMetrics daily accumulation** — переключение на подневные данные начато, но нужно дождаться накопления 40 дней для корректных дельт
2. **AdCampaignStats пуст для Brykin** — 0 строк из-за 429 rate limits при синхронизации
3. **RNP скорость** — ~15 сек на расчёт (нужно оптимизировать per-query агрегаты)
4. **Auth JWT** — сейчас cookie-based, ограничивает мобильных клиентов
5. **Search Report заблокирован** — 403 без Jam-токена

---

## Маппинг текущих данных → WB API Sources

| Функция | WB Sync Endpoint | WB API Source |
|---|---|---|
| Характеристики | POST /api/products | content-api `POST /content/v2/get/cards/list` |
| Остатки на складах | POST /api/stocks | analytics-api `POST /api/analytics/v1/stocks-report/wb-warehouses` |
| Заказы | POST /api/orders | statistics-api `GET /api/v1/supplier/orders` |
| Продажи | POST /api/sales | statistics-api `GET /api/v1/supplier/sales` |
| Цены | POST /api/prices | prices-api `GET /api/v2/list/goods/filter` |
| Отчёт реализации | POST /api/sales-report | statistics-api `GET /api/v5/supplier/reportDetailByPeriod` |
| Витрина (подневная) | POST /api/shelf-metrics | analytics-api `POST /api/analytics/v3/sales-funnel/products` |
| Воронка (агрегат) | POST /api/funnel-metrics | analytics-api `POST /api/analytics/v3/sales-funnel/products` |
| Остатки по офисам | POST /api/stock-offices | analytics-api `POST /api/v2/stocks-report/offices` |
| Рейтинги товаров | POST /api/item-ratings | analytics-api `POST /api/analytics/v1/item-rating` |
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

---

*Последнее обновление: 2026-06-18*
