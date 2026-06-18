/**
 * ============================================================
 * WB Sync Library for Google Apps Script
 * ============================================================
 *
 * Библиотека для запроса сырых данных к Wildberries через WB Sync API.
 *
 * Использование:
 * 1. Создайте новый Google Apps Script проект
 * 2. Скопируйте этот файл как библиотеку или вставьте код напрямую
 * 3. Настройте BASE_URL в конфигурации
 * 4. Вызывайте функции с токеном API
 *
 * Пример:
 *   const data = WBSync.getProducts('your-api-token');
 *   Logger.log(data.length + ' products loaded');
 *
 * Версия: 1.1.0
 * Дата: 2026-06-18
 * Автор: WB Sync
 * ============================================================
 *
 * МАППИНГ: Endpoints → WB API Sources
 * ============================================================
 *
 * Функция               │ WB Sync Endpoint      │ WB API Source (внутри)
 * ──────────────────────┼───────────────────────┼────────────────────────────────────────────────────
 * getProducts()         │ POST /api/products     │ content-api.wildberries.ru
 *                       │                       │   POST /content/v2/get/cards/list
 * ──────────────────────┼───────────────────────┼────────────────────────────────────────────────────
 * getStocks()           │ POST /api/stocks       │ seller-analytics-api.wildberries.ru
 *                       │                       │   POST /api/analytics/v1/stocks-report/wb-warehouses
 * ──────────────────────┼───────────────────────┼────────────────────────────────────────────────────
 * getOrders()           │ POST /api/orders       │ statistics-api.wildberries.ru
 *                       │                       │   GET /api/v1/supplier/orders
 * ──────────────────────┼───────────────────────┼────────────────────────────────────────────────────
 * getSales()            │ POST /api/sales        │ statistics-api.wildberries.ru
 *                       │                       │   GET /api/v1/supplier/sales
 * ──────────────────────┼───────────────────────┼────────────────────────────────────────────────────
 * getPrices()           │ POST /api/prices       │ discounts-prices-api.wildberries.ru
 *                       │                       │   GET /api/v2/list/goods/filter
 * ──────────────────────┼───────────────────────┼────────────────────────────────────────────────────
 * getSalesReport()      │ POST /api/sales-report │ statistics-api.wildberries.ru
 *                       │                       │   GET /api/v5/supplier/reportDetailByPeriod
 * ──────────────────────┼───────────────────────┼────────────────────────────────────────────────────
 * getShelfMetrics()     │ POST /api/shelf-metrics│ seller-analytics-api.wildberries.ru
 *                       │                       │   POST /api/analytics/v3/sales-funnel/products
 *                       │                       │   (подневные данные, хранятся в БД)
 * ──────────────────────┼───────────────────────┼────────────────────────────────────────────────────
 * getFunnelMetrics()    │ POST /api/funnel-metrics│ seller-analytics-api.wildberries.ru
 *                       │                       │   POST /api/analytics/v3/sales-funnel/products
 *                       │                       │   (30-дневный агрегат)
 * ──────────────────────┼───────────────────────┼────────────────────────────────────────────────────
 * getStockOffices()     │ POST /api/stock-offices│ seller-analytics-api.wildberries.ru
 *                       │                       │   POST /api/v2/stocks-report/offices
 * ──────────────────────┼───────────────────────┼────────────────────────────────────────────────────
 * getItemRatings()      │ POST /api/item-ratings │ seller-analytics-api.wildberries.ru
 *                       │                       │   POST /api/analytics/v1/item-rating
 * ──────────────────────┼───────────────────────┼────────────────────────────────────────────────────
 * getAdCampaigns()      │ POST /api/ad-campaigns │ advert-api.wildberries.ru
 *                       │                       │   GET /adv/v1/promotion/count
 * ──────────────────────┼───────────────────────┼────────────────────────────────────────────────────
 * getAdStats()          │ POST /api/ad-stats     │ advert-api.wildberries.ru
 *                       │                       │   GET /adv/v3/fullstats
 * ──────────────────────┼───────────────────────┼────────────────────────────────────────────────────
 * getAdExpenses()       │ POST /api/ad-expenses  │ advert-api.wildberries.ru
 *                       │                       │   GET /adv/v1/upd
 * ──────────────────────┼───────────────────────┼────────────────────────────────────────────────────
 * getAdSearchClusters() │ POST /api/ad-search-clusters │ advert-api.wildberries.ru
 *                       │                       │   POST /adv/v0/normquery/stats
 * ──────────────────────┼───────────────────────┼────────────────────────────────────────────────────
 * healthCheck()         │ GET /api/health        │ (нет WB API — проверка WB Sync сервера)
 * getCabinets()         │ GET /api/dashboard/cabinets │ (нет WB API — список кабинетов из БД)
 *
 * Rate Limits (WB API):
 *   - content-api:     100 req/min
 *   - statistics-api:  1 req/min (orders, sales, report)
 *   - analytics-api:   3 req/min (funnel, stocks, ratings)
 *   - advert-api:      10 req/min (clusters), глобальный 1 req/min (fullstats, upd)
 *   - prices-api:      100 req/min
 *
 * Все POST-эндпоинты WB Sync принимают токен в теле запроса: { "token": "..." }
 * ============================================================
 */

// =====================
// КОНФИГУРАЦИЯ
// =====================

/**
 * Базовый URL WB Sync сервера.
 * Измените на адрес вашего развернутого сервиса.
 * @type {string}
 */
const BASE_URL = 'http://localhost:8000';

/**
 * Таймаут запроса в секундах.
 * @type {number}
 */
const REQUEST_TIMEOUT = 30;

/**
 * Количество попыток при ошибке.
 * @type {number}
 */
const MAX_RETRIES = 3;

// =====================
// ВНУТРЕННИЕ ФУНКЦИИ
// =====================

/**
 * Логирование в Google Apps Script.
 * @param {string} message - Сообщение для лога
 * @param {string} level - Уровень лога (INFO, WARN, ERROR)
 */
function log_(message, level) {
  level = level || 'INFO';
  const timestamp = new Date().toISOString();
  Logger.log('[' + timestamp + '] [' + level + '] ' + message);
}

/**
 * Выполнение HTTP-запроса к API с retries.
 * @param {string} endpoint - Эндпоинт API (например, '/api/products')
 * @param {Object} params - Параметры запроса (query string)
 * @param {string} token - Токен API для аутентификации
 * @returns {Array} Массив объектов с данными
 */
function fetchWithRetry_(endpoint, params, token) {
  params = params || {};
  let lastError = null;

  for (let attempt = 1; attempt <= MAX_RETRIES; attempt++) {
    try {
      const queryString = Object.keys(params)
        .filter(k => params[k] !== undefined && params[k] !== null)
        .map(k => encodeURIComponent(k) + '=' + encodeURIComponent(params[k]))
        .join('&');

      const url = BASE_URL + endpoint + (queryString ? '?' + queryString : '');

      log_('Запрос #' + attempt + ': ' + url);

      const response = UrlFetchApp.fetch(url, {
        method: 'POST',
        contentType: 'application/json',
        payload: JSON.stringify({ token: token }),
        muteHttpExceptions: true,
        timeout: REQUEST_TIMEOUT * 1000,
      });

      const code = response.getResponseCode();
      const body = response.getContentText();

      if (code === 200) {
        const data = JSON.parse(body);
        log_('Успешно: ' + data.length + ' записей');
        return data;
      } else {
        lastError = 'HTTP ' + code + ': ' + body.substring(0, 200);
        log_('Попытка #' + attempt + ' не удалась: ' + lastError, 'WARN');
      }
    } catch (e) {
      lastError = e.message;
      log_('Ошибка попытки #' + attempt + ': ' + lastError, 'ERROR');
    }

    if (attempt < MAX_RETRIES) {
      Utilities.sleep(1000 * attempt);
    }
  }

  log_('Все попытки исчерпаны. Последняя ошибка: ' + lastError, 'ERROR');
  throw new Error('WB Sync API error: ' + lastError);
}

// =====================
// ЭКСПОРТИРУЕМЫЕ ФУНКЦИИ
// =====================

/**
 * Получить характеристики товаров.
 *
 * Эндпоинт API Wildberries: content-api.wildberries.ru
 * POST /content/v2/get/cards/list
 *
 * Возвращает полную информацию о товарах: название, описание, фотографии,
 * размеры, вес, характеристики (opts), бренд, категория и т.д.
 *
 * @param {string} token - Токен API (token_hash из wb_tokens)
 * @param {number} [nm_id] - Фильтр по артикулу WB (опционально)
 * @returns {Array<Object>} Массив объектов товаров
 *
 * Поля ответа:
 * - id - ID записи в БД
 * - cabinet_id - ID кабинета (SHA-256 хэш токена)
 * - nm_id - Артикул Wildberries
 * - characteristics - JSON с полными характеристиками товара:
 *   - brand - Бренд
 *   - title - Название
 *   - description - Описание
 *   - vendorCode - Артикул поставщика
 *   - subjectName - Категория товара
 *   - opts - Массив опций [{id, name, value}, ...]
 *   - dimensions - Размеры {width, height, length, weightBrutto}
 *   - photos - Массив фотографий [{big, origin, ...}]
 * - synced_at - Дата последней синхронизации
 *
 * Пример:
 *   const products = WBSync.getProducts(token);
 *   products.forEach(p => {
 *     const chars = JSON.parse(p.characteristics);
 *     Logger.log(chars.title + ' - ' + chars.brand);
 *   });
 */
function getProducts(token, nm_id) {
  log_('getProducts: загрузка характеристик товаров');
  return fetchWithRetry_('/api/products', { nm_id: nm_id }, token);
}

/**
 * Получить остатки на складах.
 *
 * Эндпоинт API Wildberries: analytics-api.wildberries.ru
 * POST /api/analytics/v1/stocks-report/wb-warehouses
 *
 * Возвращает информацию об остатках товаров на складах WB:
 * количество на складе, в пути к клиенту, в пути от клиента.
 *
 * @param {string} token - Токен API
 * @param {number} [nm_id] - Фильтр по артикулу WB (опционально)
 * @returns {Array<Object>} Массив объектов остатков
 *
 * Поля ответа:
 * - id - ID записи
 * - cabinet_id - ID кабинета
 * - nm_id - Артикул WB
 * - chrt_id - ID характеристики
 * - warehouse_id - ID склада
 * - warehouse_name - Название склада
 * - region_name - Регион склада
 * - quantity - Количество на складе
 * - in_way_to_client - В пути к клиенту
 * - in_way_from_client - В пути от клиента (возвраты)
 * - synced_at - Дата синхронизации
 * - raw_data - Сырые данные API
 *
 * Пример:
 *   const stocks = WBSync.getStocks(token);
 *   stocks.forEach(s => {
 *     Logger.log(s.warehouse_name + ': ' + s.quantity + ' шт');
 *   });
 */
function getStocks(token, nm_id) {
  log_('getStocks: загрузка остатков на складах');
  return fetchWithRetry_('/api/stocks', { nm_id: nm_id }, token);
}

/**
 * Получить заказы.
 *
 * Эндпоинт API Wildberries: statistics-api.wildberries.ru
 * GET /api/v1/supplier/orders
 *
 * Возвращает информацию о заказах: артикул, цена, статус, склад, регион.
 * Заказы хранятся за последние 90 дней.
 *
 * @param {string} token - Токен API
 * @param {number} [days_back=40] - За сколько дней вернуть заказы (макс 90)
 * @param {number} [limit=1000] - Максимальное количество записей
 * @param {number} [offset=0] - Смещение для пагинации
 * @param {string} [fields] - Поля через запятую (например, 'nm_id,date,total_price')
 * @returns {Array<Object>} Массив объектов заказов
 *
 * Поля ответа:
 * - id - ID записи
 * - cabinet_id - ID кабинета
 * - srid - Уникальный ID заказа
 * - g_number - ID корзины
 * - nm_id - Артикул WB
 * - supplier_article - Артикул поставщика
 * - barcode - Штрихкод
 * - date - Дата заказа
 * - last_change_date - Дата последнего изменения
 * - cancel_date - Дата отмены
 * - total_price - Полная цена
 * - finished_price - Итоговая цена
 * - price_with_disc - Цена с учётом скидки
 * - discount_percent - Процент скидки
 * - spp - СПП (скидка для покупателя)
 * - is_cancel - Отменён ли заказ
 * - warehouse_name - Склад
 * - region_name - Регион доставки
 * - category - Категория
 * - subject - Подкатегория
 * - brand - Бренд
 * - tech_size - Размер
 * - raw_data - Сырые данные API
 *
 * Пример:
 *   const orders = WBSync.getOrders(token, 30);
 *   const total = orders.reduce((s, o) => s + (o.total_price || 0), 0);
 *   Logger.log('Заказов: ' + orders.length + ', сумма: ' + total);
 */
function getOrders(token, days_back, limit, offset, fields) {
  log_('getOrders: загрузка заказов за ' + (days_back || 40) + ' дней');
  return fetchWithRetry_('/api/orders', {
    days_back: days_back,
    limit: limit,
    offset: offset,
    fields: fields,
  }, token);
}

/**
 * Получить продажи.
 *
 * Эндпоинт API Wildberries: statistics-api.wildberries.ru
 * GET /api/v1/supplier/sales
 *
 * Возвращает информацию о продажах и возвратах: артикул, цена, тип операции.
 * Продажи хранятся за последние 90 дней.
 *
 * @param {string} token - Токен API
 * @param {number} [days_back=40] - За сколько дней (макс 90)
 * @param {number} [limit=1000] - Максимальное количество записей
 * @param {number} [offset=0] - Смещение для пагинации
 * @param {string} [fields] - Поля через запятую
 * @returns {Array<Object>} Массив объектов продаж
 *
 * Поля ответа:
 * - id - ID записи
 * - cabinet_id - ID кабинета
 * - srid - ID sale
 * - sale_id - ID продажи
 * - g_number - ID корзины
 * - nm_id - Артикул WB
 * - supplier_article - Артикул поставщика
 * - barcode - Штрихкод
 * - date - Дата продажи
 * - total_price - Полная цена
 * - discount_price - Цена со скидкой
 * - finished_price - Итоговая цена
 * - spp - СПП
 * - for_pay - К зачёту
 * - sale_type - Тип (sale/return)
 * - warehouse_name - Склад
 * - region_name - Регион
 * - raw_data - Сырые данные API
 *
 * Пример:
 *   const sales = WBSync.getSales(token, 30);
 *   const total = sales.reduce((s, r) => s + (r.finished_price || 0), 0);
 *   Logger.log('Продаж: ' + sales.length + ', выручка: ' + total);
 */
function getSales(token, days_back, limit, offset, fields) {
  log_('getSales: загрузка продаж за ' + (days_back || 40) + ' дней');
  return fetchWithRetry_('/api/sales', {
    days_back: days_back,
    limit: limit,
    offset: offset,
    fields: fields,
  }, token);
}

/**
 * Получить цены и скидки.
 *
 * Эндпоинт API Wildberries: discounts-prices-api.wildberries.ru
 * POST /api/v5/get/products/list
 *
 * Возвращает информацию о ценах: текущая цена, цена со скидкой,
 * рекомендованная цена, минимальная цена.
 *
 * @param {string} token - Токен API
 * @param {number} [nm_id] - Фильтр по артикулу WB (опционально)
 * @returns {Array<Object>} Массив объектов цен
 *
 * Поля ответа:
 * - id - ID записи
 * - cabinet_id - ID кабинета
 * - nm_id - Артикул WB
 * - price - Текущая цена
 * - discount_price - Цена со скидкой
 * - club_price - Цена для клуба
 * - min_price - Минимальная цена
 * - recommended_price - Рекомендованная цена
 * - raw_data - Сырые данные API
 *
 * Пример:
 *   const prices = WBSync.getPrices(token);
 *   prices.forEach(p => {
 *     Logger.log(p.nm_id + ': ' + p.price + '₽ (скидка: ' + p.discount_price + '₽)');
 *   });
 */
function getPrices(token, nm_id) {
  log_('getPrices: загрузка цен и скидок');
  return fetchWithRetry_('/api/prices', { nm_id: nm_id }, token);
}

/**
 * Получить отчёт реализации.
 *
 * Эндпоинт API Wildberries: statistics-api.wildberries.ru
 * GET /api/v1/supplier/report
 *
 * Возвращает детальный финансовый отчёт по продажам с полной разбивкой
 * расходов: комиссия WB, доставка, хранение, штрафы, приёмка, эквайринг.
 * Это основной источник данных для расчёта юнит-экономики.
 *
 * @param {string} token - Токен API
 * @param {string} [date_from] - Дата начала YYYY-MM-DD
 * @param {string} [date_to] - Дата конца YYYY-MM-DD
 * @param {number} [limit=1000] - Максимальное количество записей
 * @returns {Array<Object>} Массив объектов отчёта
 *
 * Поля ответа (55+ полей):
 * - id - ID записи
 * - cabinet_id - ID кабинета
 * - rrd_id - Уникальный ID строки отчёта
 * - nm_id - Артикул WB
 * - sa_name - Артикул поставщика
 * - subject_name - Категория товара
 * - brand_name - Бренд
 * - quantity - Количество
 * - retail_price - Розничная цена
 * - retail_price_withdisc_rub - Цена со скидкой (₽)
 * - sale_percent - Процент скидки
 * - commission_percent - Комиссия WB (%)
 * - ppvz_for_pay - К зачёту (₽)
 * - ppvz_sales_commission - Комиссия WB (₽)
 * - delivery_rub - Стоимость доставки (₽)
 * - storage_fee - Хранение (₽)
 * - penalty - Штрафы (₽)
 * - acceptance - Приёмка (₽)
 * - acquiring_fee - Эквайринг (₽)
 * - additional_payment - Доплата (₽)
 * - deduction - Вычеты (₽)
 * - rebill_logistic_cost - Перебалансировка логистики (₽)
 * - dlv_prc - Процент доставки (₽)
 * - ppvz_reward - Вознаграждение WB (₽)
 * - sale_dt - Дата продажи
 * - create_dt - Дата создания
 * - raw_data - Сырые данные API
 *
 * Пример:
 *   const report = WBSync.getSalesReport(token, '2026-06-01', '2026-06-30');
 *   const totalForPay = report.reduce((s, r) => s + (r.ppvz_for_pay || 0), 0);
 *   Logger.log('К зачёту: ' + totalForPay + '₽');
 */
function getSalesReport(token, date_from, date_to, limit) {
  log_('getSalesReport: загрузка отчёта реализации');
  return fetchWithRetry_('/api/sales-report', {
    date_from: date_from,
    date_to: date_to,
    limit: limit,
  }, token);
}

/**
 * Получить данные витрины продаж.
 *
 * Эндпоинт API Wildberries: seller-analytics-api.wildberries.ru
 * POST /api/analytics/v3/sales-funnel/products
 *
 * Возвращает аналитику витрины: просмотры, добавления в корзину,
 * заказы, выкупы, конверсия, выручка, средняя цена.
 *
 * @param {string} token - Токен API
 * @param {number} [days_back=30] - За сколько дней (макс 90)
 * @param {number} [nm_id] - Фильтр по артикулу WB (опционально)
 * @returns {Array<Object>} Массив объектов витрины
 *
 * Поля ответа:
 * - id - ID записи
 * - cabinet_id - ID кабинета
 * - nm_id - Артикул WB
 * - vendor_code - Артикул поставщика
 * - product_name - Название товара
 * - subject_name - Категория
 * - brand_name - Бренд
 * - product_rating - Рейтинг товара
 * - feedback_rating - Рейтинг отзывов
 * - open_count - Просмотры карточки
 * - cart_count - Добавления в корзину
 * - order_count - Заказы
 * - order_sum - Сумма заказов (₽)
 * - buyout_count - Выкупы
 * - buyout_sum - Сумма выкупов (₽)
 * - cancel_count - Отмены
 * - cancel_sum - Сумма отмен (₽)
 * - avg_price - Средняя цена
 * - conv_add_to_cart - Конверсия в корзину (%)
 * - conv_cart_to_order - Конверсия корзина→заказ (%)
 * - conv_buyout - Конверсия выкупа (%)
 * - stocks_wb - Остатки на WB
 * - stocks_mp - Остатки на MP
 * - period_start - Начало периода
 * - period_end - Конец периода
 * - raw_data - Сырые данные API
 *
 * Пример:
 *   const shelf = WBSync.getShelfMetrics(token, 30);
 *   shelf.forEach(s => {
 *     Logger.log(s.product_name + ': конверсия ' + s.conv_add_to_cart + '%');
 *   });
 */
function getShelfMetrics(token, days_back, nm_id) {
  log_('getShelfMetrics: загрузка данных витрины');
  return fetchWithRetry_('/api/shelf-metrics', {
    days_back: days_back,
    nm_id: nm_id,
  }, token);
}

/**
 * Получить данные воронки конверсии.
 *
 * Эндпоинт API Wildberries: seller-analytics-api.wildberries.ru
 * POST /api/analytics/v3/sales-funnel/products
 *
 * Возвращает данные воронки с сравнением текущего и прошлого периодов:
 * просмотры, корзина, заказы, выкупы, конверсия, динамика.
 *
 * @param {string} token - Токен API
 * @param {number} [days_back=30] - За сколько дней (макс 90)
 * @param {number} [nm_id] - Фильтр по артикулу WB (опционально)
 * @returns {Array<Object>} Массив объектов воронки
 *
 * Поля ответа:
 * - id - ID записи
 * - cabinet_id - ID кабинета
 * - nm_id - Артикул WB
 * - vendor_code - Артикул поставщика
 * - product_name - Название товара
 * - open_count - Просмотры (текущий период)
 * - cart_count - Корзина (текущий)
 * - order_count - Заказы (текущий)
 * - buyout_count - Выкупы (текущий)
 * - order_sum - Сумма заказов (₽)
 * - conv_cart_to_order - Конверсия корзина→заказ (%)
 * - conv_buyout - Конверсия выкупа (%)
 * - past_open_count - Просмотры (прошлый период)
 * - past_cart_count - Корзина (прошлый)
 * - past_order_count - Заказы (прошлый)
 * - past_buyout_count - Выкупы (прошлый)
 * - dynamic_open - Динамика просмотров (%)
 * - dynamic_cart - Динамика корзины (%)
 * - dynamic_order - Динамика заказов (%)
 * - dynamic_buyout - Динамика выкупов (%)
 * - period_start - Начало периода
 * - period_end - Конец периода
 * - raw_data - Сырые данные API
 *
 * Пример:
 *   const funnel = WBSync.getFunnelMetrics(token, 30);
 *   funnel.forEach(f => {
 *     Logger.log(f.product_name + ': конверсия ' + f.conv_buyout + '%');
 *   });
 */
function getFunnelMetrics(token, days_back, nm_id) {
  log_('getFunnelMetrics: загрузка данных воронки');
  return fetchWithRetry_('/api/funnel-metrics', {
    days_back: days_back,
    nm_id: nm_id,
  }, token);
}

/**
 * Получить остатки по офисам/складам.
 *
 * Эндпоинт API Wildberries: seller-analytics-api.wildberries.ru
 * POST /api/v2/stocks-report/products/groups
 *
 * Возвращает информацию об остатках по регионам и складам:
 * количество, сумма, оборачиваемость, доставка, возвраты.
 *
 * @param {string} token - Токен API
 * @param {number} [days_back=30] - За сколько дней (макс 90)
 * @returns {Array<Object>} Массив объектов остатков по офисам
 *
 * Поля ответа:
 * - id - ID записи
 * - cabinet_id - ID кабинета
 * - region_name - Название региона
 * - office_id - ID офиса/склада
 * - office_name - Название офиса/склада
 * - stock_count - Количество остатков
 * - stock_sum - Сумма остатков (₽)
 * - sale_rate_days - Дней до продажи остатков
 * - to_client_count - Доставлено клиентам
 * - from_client_count - Возвраты от клиентов
 * - period_start - Начало периода
 * - period_end - Конец периода
 * - raw_data - Сырые данные API
 *
 * Пример:
 *   const offices = WBSync.getStockOffices(token, 30);
 *   offices.forEach(o => {
 *     Logger.log(o.office_name + ': ' + o.stock_count + ' шт');
 *   });
 */
function getStockOffices(token, days_back) {
  log_('getStockOffices: загрузка остатков по офисам');
  return fetchWithRetry_('/api/stock-offices', {
    days_back: days_back,
  }, token);
}

/**
 * Получить рейтинги и отзывы товаров.
 *
 * Эндпоинт API Wildberries: seller-analytics-api.wildberries.ru
 * POST /api/analytics/v1/item-rating
 *
 * Возвращает рейтинги товаров: общий рейтинг, количество отзывов,
 * распределение по звёздам, перцентиль.
 *
 * @param {string} token - Токен API
 * @param {number} [days_back=30] - За сколько дней (макс 90)
 * @param {number} [nm_id] - Фильтр по артикулу WB (опционально)
 * @returns {Array<Object>} Массив объектов рейтингов
 *
 * Поля ответа:
 * - id - ID записи
 * - cabinet_id - ID кабинета
 * - nm_id - Артикул WB
 * - vendor_code - Артикул поставщика
 * - product_name - Название товара
 * - subject_name - Категория
 * - brand_name - Бренд
 * - seller_rating - Рейтинг продавца
 * - product_rating - Рейтинг товара
 * - feedback_rating - Рейтинг отзывов
 * - feedback_percentile - Перцентиль отзывов
 * - feedback_count - Общее количество отзывов
 * - five_star - Отзывы 5 звёзд
 * - four_star - Отзывы 4 звезды
 * - three_star - Отзывы 3 звезды
 * - two_star - Отзывы 2 звезды
 * - one_star - Отзывы 1 звезда
 * - disqualified - Дисквалифицировано
 * - period_start - Начало периода
 * - period_end - Конец периода
 * - raw_data - Сырые данные API
 *
 * Пример:
 *   const ratings = WBSync.getItemRatings(token, 30);
 *   ratings.forEach(r => {
 *     Logger.log(r.product_name + ': ' + r.feedback_rating + '★ (' + r.feedback_count + ' отзывов)');
 *   });
 */
function getItemRatings(token, days_back, nm_id) {
  log_('getItemRatings: загрузка рейтингов товаров');
  return fetchWithRetry_('/api/item-ratings', {
    days_back: days_back,
    nm_id: nm_id,
  }, token);
}

/**
 * Получить рекламные кампании.
 *
 * Эндпоинт API Wildberries: advert-api.wildberries.ru
 * GET /adv/v1/promotion/count
 *
 * Возвращает список рекламных кампаний: ID, статус, тип, время изменения.
 *
 * @param {string} token - Токен API
 * @returns {Array<Object>} Массив объектов кампаний
 *
 * Поля ответа:
 * - id - ID записи
 * - cabinet_id - ID кабинета
 * - advert_id - ID кампании
 * - advert_type - Тип кампании
 * - status - Статус кампании (-1=удалена, 4=готова, 7=завершена, 8=отменена, 9=активна, 11=пауза)
 * - name - Название кампании
 * - bid_type - Тип ставки
 * - payment_type - Тип оплаты
 * - change_time - Время последнего изменения
 * - synced_at - Дата синхронизации
 * - raw_data - Сырые данные API
 *
 * Пример:
 *   const campaigns = WBSync.getAdCampaigns(token);
 *   campaigns.forEach(c => {
 *     Logger.log('Кампания ' + c.advert_id + ': статус ' + c.status);
 *   });
 */
function getAdCampaigns(token) {
  log_('getAdCampaigns: загрузка рекламных кампаний');
  return fetchWithRetry_('/api/ad-campaigns', {}, token);
}

/**
 * Получить статистику рекламных кампаний по дням.
 *
 * Эндпоинт API Wildberries: advert-api.wildberries.ru
 * GET /adv/v3/fullstats
 *
 * Возвращает дневную статистику по кампаниям: просмотры, клики,
 * CTR, CPC, CR, заказы, затраты, выручка.
 *
 * @param {string} token - Токен API
 * @param {number} [days_back=30] - За сколько дней (макс 90)
 * @returns {Array<Object>} Массив объектов статистики
 *
 * Поля ответа:
 * - id - ID записи
 * - cabinet_id - ID кабинета
 * - advert_id - ID кампании
 * - date - Дата
 * - views - Показы
 * - clicks - Клики
 * - ctr - CTR (%)
 * - cpc - CPC (₽)
 * - cr - CR (%)
 * - atbs - Добавления в корзину
 * - orders - Заказы
 * - shks - Заказы в корзине
 * - canceled - Отмены
 * - spend - Затраты (₽)
 * - sum_price - Сумма заказов (₽)
 * - avg_position - Средняя позиция
 * - synced_at - Дата синхронизации
 * - raw_data - Сырые данные API
 *
 * Пример:
 *   const stats = WBSync.getAdStats(token, 30);
 *   stats.forEach(s => {
 *     Logger.log('Кампания ' + s.advert_id + ': CTR ' + s.ctr + '%');
 *   });
 */
function getAdStats(token, days_back) {
  log_('getAdStats: загрузка статистики рекламы');
  return fetchWithRetry_('/api/ad-stats', {
    days_back: days_back,
  }, token);
}

/**
 * Получить историю затрат на рекламу.
 *
 * Эндпоинт API Wildberries: advert-api.wildberries.ru
 * GET /adv/v1/upd
 *
 * Возвращает историю списаний за рекламу: кампания, сумма, дата, тип оплаты.
 *
 * @param {string} token - Токен API
 * @param {number} [days_back=30] - За сколько дней (макс 90)
 * @returns {Array<Object>} Массив объектов затрат
 *
 * Поля ответа:
 * - id - ID записи
 * - cabinet_id - ID кабинета
 * - advert_id - ID кампании
 * - camp_name - Название кампании
 * - advert_type - Тип кампании
 * - advert_status - Статус кампании
 * - payment_type - Тип оплаты (Баланс/Бюджет)
 * - upd_time - Дата списания
 * - upd_sum - Сумма списания (₽)
 * - synced_at - Дата синхронизации
 * - raw_data - Сырые данные API
 *
 * Пример:
 *   const expenses = WBSync.getAdExpenses(token, 30);
 *   const total = expenses.reduce((s, e) => s + (e.upd_sum || 0), 0);
 *   Logger.log('Затраты на рекламу: ' + total + '₽');
 */
function getAdExpenses(token, days_back) {
  log_('getAdExpenses: загрузка затрат на рекламу');
  return fetchWithRetry_('/api/ad-expenses', {
    days_back: days_back,
  }, token);
}

/**
 * Получить поисковые кластеры рекламных кампаний.
 *
 * Эндпоинт API Wildberries: advert-api.wildberries.ru
 * GET /adv/v1/search
 *
 * Возвращает поисковые запросы, по которым показывается реклама:
 * ключевые слова, ставки, CTR, CPC, заказы, затраты.
 *
 * @param {string} token - Токен API
 * @returns {Array<Object>} Массив объектов поисковых кластеров
 *
 * Поля ответа:
 * - id - ID записи
 * - cabinet_id - ID кабинета
 * - advert_id - ID кампании
 * - keyword - Поисковый запрос
 * - cluster_id - ID кластера
 * - bids - Ставка
 * - views - Показы
 * - clicks - Клики
 * - ctr - CTR (%)
 * - cpc - CPC (₽)
 * - sum_price - Сумма заказов (₽)
 * - orders - Заказы
 * - spend - Затраты (₽)
 * - synced_at - Дата синхронизации
 * - raw_data - Сырые данные API
 *
 * Пример:
 *   const clusters = WBSync.getAdSearchClusters(token);
 *   clusters.forEach(c => {
 *     Logger.log('"' + c.keyword + '": CTR ' + c.ctr + '%, заказов ' + c.orders);
 *   });
 */
function getAdSearchClusters(token) {
  log_('getAdSearchClusters: загрузка поисковых кластеров');
  return fetchWithRetry_('/api/ad-search-clusters', {}, token);
}

// =====================
// УТИЛИТЫ
// =====================

/**
 * Проверка подключения к серверу.
 *
 * @param {string} token - Токен API
 * @returns {Object} Статус сервера
 *
 * Пример:
 *   const status = WBSync.healthCheck(token);
 *   Logger.log('Сервер: ' + status.status);
 */
function healthCheck(token) {
  log_('healthCheck: проверка подключения');
  try {
    const response = UrlFetchApp.fetch(BASE_URL + '/api/health', {
      method: 'GET',
      muteHttpExceptions: true,
      timeout: 5000,
    });
    return JSON.parse(response.getContentText());
  } catch (e) {
    log_('Сервер недоступен: ' + e.message, 'ERROR');
    return { status: 'error', message: e.message };
  }
}

/**
 * Получить список кабинетов.
 *
 * @returns {Array<Object>} Массив кабинетов [{cabinet_id, seller_name}, ...]
 *
 * Пример:
 *   const cabinets = WBSync.getCabinets();
 *   cabinets.forEach(c => {
 *     Logger.log(c.seller_name + ': ' + c.cabinet_id);
 *   });
 */
function getCabinets() {
  log_('getCabinets: загрузка списка кабинетов');
  try {
    const response = UrlFetchApp.fetch(BASE_URL + '/api/dashboard/cabinets', {
      method: 'GET',
      muteHttpExceptions: true,
      timeout: 10000,
    });
    return JSON.parse(response.getContentText());
  } catch (e) {
    log_('Ошибка загрузки кабинетов: ' + e.message, 'ERROR');
    return [];
  }
}

/**
 * Конвертация данных в формат Google Sheets.
 * Преобразует массив объектов в двумерный массив для записи в таблицу.
 *
 * @param {Array<Object>} data - Массив объектов
 * @returns {Array<Array>} Двумерный массив [строки][столбцы]
 *
 * Пример:
 *   const products = WBSync.getProducts(token);
 *   const sheet = WBSync.toArray(products);
 *   SpreadsheetApp.getActiveSheet().getRange(1, 1, sheet.length, sheet[0].length).setValues(sheet);
 */
function toArray(data) {
  if (!data || !data.length) return [];

  const headers = Object.keys(data[0]);
  const result = [headers];

  data.forEach(row => {
    const values = headers.map(h => {
      const v = row[h];
      if (typeof v === 'object' && v !== null) {
        return JSON.stringify(v);
      }
      return v;
    });
    result.push(values);
  });

  return result;
}

// =====================
// ЭКСПОРТ (для библиотеки)
// =====================

// Функции доступны глобально при использовании как библиотека
// или через пространство имён WBSync при копировании кода

var WBSync = {
  getProducts: getProducts,
  getStocks: getStocks,
  getOrders: getOrders,
  getSales: getSales,
  getPrices: getPrices,
  getSalesReport: getSalesReport,
  getShelfMetrics: getShelfMetrics,
  getFunnelMetrics: getFunnelMetrics,
  getStockOffices: getStockOffices,
  getItemRatings: getItemRatings,
  getAdCampaigns: getAdCampaigns,
  getAdStats: getAdStats,
  getAdExpenses: getAdExpenses,
  getAdSearchClusters: getAdSearchClusters,
  healthCheck: healthCheck,
  getCabinets: getCabinets,
  toArray: toArray,
};
