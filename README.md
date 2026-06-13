# WB Sync

Сервис синхронизации данных Wildberries с дашбордом аналитики.

Загружает данные из API Wildberries (характеристики, остатки, заказы, цены, продажи, аналитику), сохраняет в PostgreSQL и предоставляет REST API + дашборд.

---

## Возможности

- Поддержка нескольких кабинетов продавцов (19 кабинетов)
- Привязка токенов к человекочитаемым именам продавцов
- Автоматическая ежедневная синхронизация по расписанию
- Ручной запуск синхронизации через API
- Telegram-уведомления о результатах синхронизации
- Встроенный дашборд с 12 вкладками аналитики
- Raw data API для внешних потребителей

---

## Что синхронизируется

### Основные данные
- Характеристики товаров (content-api)
- Остатки на складах WB (analytics-api)
- Заказы за 40 дней (statistics-api)
- Цены и скидки (prices-api)
- Продажи за 40 дней (statistics-api)
- Отчёт реализации за вчера (statistics-api)

### Аналитика (analytics-api)
- **Воронка продаж v3** — просмотры, конверсия в корзину/заказ, выкупы, сравнение с прошлым периодом
- **Витрина продаж** — просмотры, добавления в корзину, конверсия по товарам
- **Остатки по складам** — остатки и оборачиваемость по регионам и складам
- **Оценки товаров** — рейтинг, отзывы по звёздам, перцентиль

### Реклама (advert-api)
- **Кампании** — список, статусы, типы ставок
- **Статистика** — просмотры, клики, CTR, CPC, CR, заказы, затраты
- **Затраты** — история списаний по дням с указанием кампании

---

## Архитектура

```
WB API → scheduler → PostgreSQL → FastAPI → клиент / дашборд
```

### Структура проекта

```
app/
├── main.py               — FastAPI: эндпоинты, дашборд, лайфспан
├── scheduler.py           — Планировщик: синхронизация + Telegram
├── crud.py                — CRUD-операции с БД
├── wb_client.py           — Клиент WB API (характеристики, остатки, заказы, цены, продажи)
├── wb_analytics_client.py — Клиент WB Analytics API (воронка, склады, оценки)
├── models.py              — SQLAlchemy модели
├── schemas.py             — Pydantic-схемы
└── database.py            — Подключение к PostgreSQL

static/
├── dashboard.html         — Оболочка дашборда
├── tabs/
│   ├── summary.html       — Сводка
│   ├── orders.html        — Заказы
│   ├── stocks.html        — Остатки
│   ├── top-products.html  — Топ товаров
│   ├── sales-report.html  — Отчёт реализации
│   ├── shelf.html         — Витрина продаж
│   ├── conversion.html    — Воронка конверсии
│   ├── stock-offices.html — Остатки по складам
│   ├── item-ratings.html  — Оценки и отзывы
│   ├── advert.html         — Реклама
│   ├── characteristics.html — Характеристики
│   └── abc-xyz.html       — ABC/XYZ анализ
├── js/
│   ├── core.js            — Глобальное состояние, фильтры, утилиты
│   └── tabs.js            — Логика вкладок и динамическая загрузка
├── base.css               — Стили
└── themes.css             — Темы оформления

alembic/
└── versions/              — Миграции БД
```

---

## Технологии

- Python 3.12
- FastAPI + Uvicorn
- SQLAlchemy 2.0
- PostgreSQL 14+
- APScheduler
- httpx (async HTTP)
- Pydantic 2.x
- Alembic (миграции)

---

## Установка и запуск

### 1. Клонировать

```bash
git clone https://github.com/Snowfish1975/WB_SYNC_2.git
cd WB_SYNC_2
```

### 2. Виртуальное окружение

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Настройка `.env`

```bash
cp .env.example .env
```

```env
DATABASE_URL=postgresql://user:password@localhost:5432/wbdb
SYNC_HOUR=3
TELEGRAM_BOT_TOKEN=xxx
TELEGRAM_CHAT_ID=123456
```

### 4. Инициализация БД

```bash
alembic upgrade head
```

### 5. Токены продавцов

Токены WB добавляются через API или напрямую в таблицу `wb_tokens`.

### 6. Запуск

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- Дашборд: `http://localhost:8000/dashboard`
- Swagger: `http://localhost:8000/docs`
- Health-check: `http://localhost:8000/api/health`

---

## API

### Данные (POST, raw data)

| Эндпоинт | Описание |
|----------|----------|
| `/api/products` | Характеристики товаров |
| `/api/stocks` | Остатки на складах |
| `/api/orders` | Заказы (days_back, limit, offset, fields) |
| `/api/sales` | Продажи и возвраты |
| `/api/prices` | Цены и скидки |
| `/api/sales-report` | Отчёт реализации |

### Аналитика дашборда (GET)

| Эндпоинт | Описание |
|----------|----------|
| `/api/dashboard/summary` | Сводные цифры |
| `/api/dashboard/sales-chart` | Продажи по дням |
| `/api/dashboard/top-products` | Топ товаров по выручке |
| `/api/dashboard/stocks-summary` | Остатки по товарам |
| `/api/dashboard/sales-report-summary` | Сводка отчёта реализации |
| `/api/dashboard/orders-raw` | Заказы для таблицы |
| `/api/dashboard/shelf` | Витрина продаж (просмотры, конверсия) |
| `/api/dashboard/funnel` | Воронка конверсии (сравнение периодов) |
| `/api/dashboard/stock-offices` | Остатки по складам/регионам |
| `/api/dashboard/item-ratings` | Оценки и отзывы товаров |
| `/api/dashboard/ad-campaigns` | Рекламные кампании |
| `/api/dashboard/ad-stats` | Статистика рекламы (CTR, CPC, CR, ROI) |
| `/api/dashboard/ad-expenses` | История затрат на рекламу |
| `/api/dashboard/abc-xyz` | ABC/XYZ анализ |
| `/api/dashboard/characteristics` | Характеристики товаров |
| `/api/dashboard/cabinets` | Список кабинетов |

### Управление

| Метод | Эндпоинт | Описание |
|-------|----------|----------|
| POST | `/api/sync/trigger` | Запуск полной синхронизации |
| POST | `/api/sync/trigger-sales-report` | Синхронизация отчёта реализации |
| GET | `/api/logs` | История синхронизаций |
| GET | `/api/health` | Health-check |
| GET | `/dashboard` | HTML-дашборд |

### Токены / Кабинеты

| Метод | Эндпоинт | Описание |
|-------|----------|----------|
| GET | `/api/wb-tokens` | Список токенов |
| POST | `/api/wb-tokens` | Создать токен |
| DELETE | `/api/wb-tokens/{id}` | Удалить токен |

---

## Планировщик

1. **Основная синхронизация** — ежедневно в `SYNC_HOUR` UTC (по умолчанию 03:00 = 06:00 МСК)
   - Характеристики, остатки, заказы, цены, продажи
   - Воронка продаж v3 (просмотры, конверсия, выкупы)
   - Остатки по складам (регионы, склады)
   - Оценки товаров (рейтинги, отзывы)
2. **Отчёт реализации** — ежедневно в 07:30 UTC (10:30 МСК)

Лимиты WB Analytics API: 3 запроса в минуту, интервал 20 сек.

---

## Telegram-уведомления

После каждой синхронизации в Telegram отправляется отчёт:
- Количество записей по каждому кабинету
- Ошибки по кабинетам
- Время выполнения

---

## Особенности

- Upsert через `ON CONFLICT` для идемпотентной записи
- Потоковая загрузка заказов и продаж (чанками по 5000)
- Ретраи с backoff при ошибках API Wildberries
- Токены хранятся в БД с SHA-256 хэшем (`token_hash` = `cabinet_id`)
- Автоочистка заказов и продаж старше 40 дней
- Кэш-бастинг статических файлов
- raw_data JSON-хранилище для полных ответов API

---

## WB API группы

| API | Домен | Данные |
|-----|-------|--------|
| Content API | `content-api.wildberries.ru` | Характеристики товаров |
| Analytics API v1 | `seller-analytics-api.wildberries.ru` | Остатки на складах, оценки товаров |
| Analytics API v3 | `seller-analytics-api.wildberries.ru` | Воронка продаж |
| Analytics API v2 | `seller-analytics-api.wildberries.ru` | Остатки по группам/складам |
| Statistics API | `statistics-api.wildberries.ru` | Заказы, продажи |
| Prices API | `discounts-prices-api.wildberries.ru` | Цены и скидки |
| Advert API | `advert-api.wildberries.ru` | Рекламные кампании, статистика, затраты |
