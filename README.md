# WB Sync

Сервис синхронизации данных Wildberries.

Приложение регулярно загружает данные из API Wildberries (характеристики товаров, остатки, заказы, цены, продажи, отчёт реализации), сохраняет их в PostgreSQL и предоставляет доступ через REST API и дашборд.

---

## Возможности

- Поддержка нескольких кабинетов продавцов
- Привязка токенов к человекочитаемым именам продавцов
- Ежедневная автоматическая синхронизация (cron)
- Ручной запуск синхронизации через API
- Хранение истории синхронизаций (логов)
- Получение данных через REST API
- Встроенный дашборд с аналитикой
- Отправка отчётов в Telegram

---

## Что синхронизируется

- Характеристики товаров (cards/list)
- Остатки на складах (stocks)
- Заказы за последние 40 дней (orders)
- Цены и скидки (prices)
- Продажи и возвраты за последние 40 дней (sales)
- Отчёт реализации за вчера (reportDetailByPeriod)

---

## Архитектура

```
WB API → scheduler → PostgreSQL → FastAPI → клиент / дашборд
```

- `main.py` — API-эндпоинты и дашборд
- `scheduler.py` — синхронизация и Telegram-отчёты
- `crud.py` — работа с БД (upsert, запросы, очистка)
- `wb_client.py` — запросы к API Wildberries
- `models.py` — SQLAlchemy модели
- `schemas.py` — Pydantic-схемы ответов
- `database.py` — подключение к PostgreSQL

---

## Технологии

- Python 3.11
- FastAPI
- SQLAlchemy 2.0
- PostgreSQL
- APScheduler
- httpx
- Pydantic 2.x
- Render.com (деплой)

---

## Локальный запуск

### 1. Клонировать репозиторий

```bash
git clone https://github.com/ВАШ_ЛОГИН/wb-sync.git
cd wb-sync
```

### 2. Виртуальное окружение

```bash
python -m venv .venv
source .venv/bin/activate   # Linux / macOS
.venv\Scripts\activate      # Windows
pip install -r requirements.txt
```

### 3. Настройка `.env`

```bash
cp .env.example .env
```

### Пример:

```env
DATABASE_URL=postgresql://user:password@localhost/wb_sync

WB_TOKENS_JSON={"ИП Иванов":"token1","ООО Ромашка":"token2"}

SYNC_HOUR=3

TELEGRAM_BOT_TOKEN=xxx
TELEGRAM_CHAT_ID=123456
```

---

## Работа с токенами

Формат переменной окружения:

```env
WB_TOKENS_JSON={"Имя продавца":"API_TOKEN"}
```

### Пример:

```env
WB_TOKENS_JSON={
  "ИП Иванов":"abcdef123...",
  "ООО Ромашка":"987654..."
}
```

### Преимущества:

- Не нужно соблюдать порядок токенов
- Легко добавлять/удалять
- Удобно читать и редактировать
- Сразу есть имя продавца для логов и API

---

## Запуск

```bash
uvicorn app.main:app --reload
```

Swagger: `http://localhost:8000/docs`

Дашборд: `http://localhost:8000/dashboard`

---

## API

Все эндпоинты с токеном принимают JSON-тело:

```json
{
  "token": "API_TOKEN"
}
```

`seller_name` подставляется автоматически из `.env`.

### Данные

| Метод | Эндпоинт | Описание |
|-------|----------|----------|
| POST | `/api/products` | Характеристики товаров |
| POST | `/api/stocks` | Остатки на складах |
| POST | `/api/orders` | Заказы (days_back, limit, offset, fields) |
| POST | `/api/sales` | Продажи и возвраты (days_back, limit, offset, fields) |
| POST | `/api/prices` | Цены и скидки |
| POST | `/api/sales-report` | Отчёт реализации (date_from, date_to, nm_id, limit) |

### Управление

| Метод | Эндпоинт | Описание |
|-------|----------|----------|
| POST | `/api/sync/trigger` | Запуск полной синхронизации |
| POST | `/api/sync/trigger-sales-report` | Запуск синхронизации отчёта реализации |
| GET | `/api/logs` | История синхронизаций |
| GET | `/api/health` | Health-check |

### Дашборд

| Метод | Эндпоинт | Описание |
|-------|----------|----------|
| GET | `/api/dashboard/summary` | Сводные цифры: заказы, выручка, отмены |
| GET | `/api/dashboard/sales-chart` | Продажи по дням для графика |
| GET | `/api/dashboard/top-products` | Топ товаров по выручке |
| GET | `/api/dashboard/stocks-summary` | Остатки сгруппированные по товару |
| GET | `/api/dashboard/sales-report-summary` | Сводка по отчёту реализации |
| GET | `/api/dashboard/orders-raw` | Сырые заказы для таблицы |
| GET | `/dashboard` | HTML-дашборд |

### Параметры запросов (orders / sales)

- `days_back` — за сколько дней вернуть данные (1-90, по умолчанию 40)
- `limit` — максимальное количество записей (до 500000)
- `offset` — смещение для пагинации
- `fields` — поля через запятую (например: `nm_id,date,total_price`)

---

## Планировщик

Два фоновых задания через APScheduler:

1. **Полная синхронизация** — ежедневно в `SYNC_HOUR` UTC (по умолчанию 03:00)
2. **Отчёт реализации** — ежедневно в 07:30 UTC (10:30 МСК)

---

## Telegram уведомления

После каждой синхронизации отправляется отчёт:

- Количество обработанных записей по каждому кабинету
- Ошибки по кабинетам
- Общее время выполнения

---

## Особенности реализации

- Upsert через `ON CONFLICT` для идемпотентной записи
- Потоковая загрузка заказов и продаж (чанками по 5000) для экономии памяти
- Ретраи с backoff при ошибках API Wildberries
- Токены не хранятся в БД — используется `token → SHA256 → cabinet_id`
- Автоочистка заказов и продаж старше 40 дней

---

## Важные замечания

### Токены в БД не хранятся

```
token → SHA256 → cabinet_id
```

### Если JSON сломан — токены не загрузятся

Проверьте валидность:

```bash
python -m json.tool < .env
```

---

## Деплой (Render)

- Создать Web Service
- Указать стартовую команду:

```
uvicorn app.main:app --host 0.0.0.0 --port 10000
```

- Добавить переменные окружения

---

## Планы развития

- Пагинация API для больших объёмов данных
- Фильтрация по seller_name на уровне API
- Аутентификация API-запросов
- Миграции через Alembic
