import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func, case, and_

from app.models import Order, Stock
from app.crud import load_token_mapping

logger = logging.getLogger(__name__)


def get_daily_series(
    db: Session,
    cabinet_id: str | None = None,
    nm_id: int | None = None,
    days_back: int = 40,
    metric: str = "revenue",
) -> pd.DataFrame:
    """
    Агрегация заказов по дням.
    metric: 'revenue' | 'orders' | 'items'
    Возвращает DataFrame с колонками [day, value].
    """
    threshold = datetime.now() - timedelta(days=days_back)

    if metric == "revenue":
        value_expr = func.sum(
            case((Order.is_cancel == False, Order.price_with_disc), else_=0)
        )
    elif metric == "orders":
        value_expr = func.count(Order.id)
    elif metric == "items":
        value_expr = func.count(Order.id)
    else:
        value_expr = func.count(Order.id)

    q = db.query(
        func.date(Order.date).label("day"),
        value_expr.label("value"),
    ).filter(Order.date >= threshold)

    if cabinet_id:
        q = q.filter(Order.cabinet_id == cabinet_id)
    if nm_id:
        q = q.filter(Order.nm_id == nm_id)
    if metric == "orders" or metric == "items":
        q = q.filter(Order.is_cancel == False)

    rows = q.group_by(func.date(Order.date)).order_by(func.date(Order.date)).all()

    if not rows:
        return pd.DataFrame(columns=["day", "value"])

    df = pd.DataFrame([{"day": str(r.day), "value": float(r.value or 0)} for r in rows])
    df["day"] = pd.to_datetime(df["day"])

    yesterday = pd.Timestamp(datetime.now().date()) - timedelta(days=1)
    full_range = pd.date_range(start=df["day"].min(), end=yesterday, freq="D")
    df = df.set_index("day").reindex(full_range, fill_value=0).reset_index()
    df.columns = ["day", "value"]

    if len(df) > 3:
        first_val = df["value"].iloc[0]
        median_val = df["value"].median()
        if first_val < median_val * 0.15:
            df = df.iloc[1:].reset_index(drop=True)

    return df


def _exponential_smoothing(series: np.ndarray, alpha: float = 0.3, forecast_days: int = 7) -> np.ndarray:
    """Простое экспоненциальное сглаживание."""
    n = len(series)
    if n == 0:
        return np.zeros(forecast_days)

    smoothed = np.zeros(n)
    smoothed[0] = series[0]
    for i in range(1, n):
        smoothed[i] = alpha * series[i] + (1 - alpha) * smoothed[i - 1]

    last_level = smoothed[-1]
    return np.full(forecast_days, last_level)


def _holt_linear(series: np.ndarray, alpha: float = 0.3, beta: float = 0.1, forecast_days: int = 7) -> np.ndarray:
    """Метод Холта — линейный тренд."""
    n = len(series)
    if n < 2:
        return np.full(forecast_days, series[-1] if n > 0 else 0)

    level = np.zeros(n)
    trend = np.zeros(n)
    level[0] = series[0]
    trend[0] = series[1] - series[0]

    for i in range(1, n):
        level[i] = alpha * series[i] + (1 - alpha) * (level[i - 1] + trend[i - 1])
        trend[i] = beta * (level[i] - level[i - 1]) + (1 - beta) * trend[i - 1]

    forecast = np.zeros(forecast_days)
    for h in range(forecast_days):
        forecast[h] = level[-1] + trend[-1] * (h + 1)

    return forecast


def _seasonal_naive(series: np.ndarray, season_length: int = 7, forecast_days: int = 7) -> np.ndarray:
    """Сезонный наивный прогноз — повторение паттерна прошлой недели."""
    n = len(series)
    if n < season_length:
        return np.full(forecast_days, series[-1] if n > 0 else 0)

    forecast = np.zeros(forecast_days)
    for h in range(forecast_days):
        idx = n - season_length + (h % season_length)
        forecast[h] = series[idx]

    return forecast


def _holt_winters_additive(
    series: np.ndarray,
    season_length: int = 7,
    alpha: float = 0.3,
    beta: float = 0.1,
    gamma: float = 0.1,
    forecast_days: int = 7,
) -> np.ndarray:
    """Метод Холта-Уинтерса — аддитивная сезонность."""
    n = len(series)
    if n < season_length * 2:
        return _holt_linear(series, alpha, beta, forecast_days)

    season_count = n // season_length

    init_level = np.mean(series[:season_length])
    init_trend = (np.mean(series[season_length:2 * season_length]) - np.mean(series[:season_length])) / season_length
    init_season = np.zeros(season_length)
    for i in range(season_length):
        init_season[i] = series[i] - init_level

    level = np.zeros(n)
    trend = np.zeros(n)
    season = np.zeros(n + forecast_days)

    level[0] = init_level
    trend[0] = init_trend
    for i in range(season_length):
        season[i] = init_season[i]

    for i in range(1, n):
        s_idx = i % season_length
        prev_s_idx = (i - season_length) if (i - season_length) >= 0 else s_idx
        level[i] = alpha * (series[i] - season[prev_s_idx]) + (1 - alpha) * (level[i - 1] + trend[i - 1])
        trend[i] = beta * (level[i] - level[i - 1]) + (1 - beta) * trend[i - 1]
        season[i] = gamma * (series[i] - level[i]) + (1 - gamma) * season[prev_s_idx]

    forecast = np.zeros(forecast_days)
    for h in range(forecast_days):
        s_idx = (n - season_length + (h % season_length))
        forecast[h] = level[-1] + trend[-1] * (h + 1) + season[s_idx]

    return forecast


def _calc_confidence_intervals(
    historical: np.ndarray,
    forecast: np.ndarray,
    confidence: float = 0.8,
) -> tuple[np.ndarray, np.ndarray]:
    """Расчёт доверительного интервала на основе остатков."""
    n = len(historical)
    if n < 7:
        margin = np.mean(np.abs(historical)) * 0.2 if n > 0 else 1
        return forecast - margin, forecast + margin

    smoothed = _exponential_smoothing(historical, alpha=0.3, forecast_days=n)
    residuals = historical - smoothed
    std = np.std(residuals[-14:]) if n >= 14 else np.std(residuals)

    z = 1.28 if confidence == 0.8 else 1.96 if confidence == 0.95 else 1.645
    lower = forecast - z * std * np.sqrt(np.arange(1, len(forecast) + 1))
    upper = forecast + z * std * np.sqrt(np.arange(1, len(forecast) + 1))

    return np.maximum(lower, 0), upper


def forecast(
    db: Session,
    cabinet_id: str | None = None,
    nm_id: int | None = None,
    forecast_days: int = 7,
    metric: str = "revenue",
) -> dict:
    """
    Основная функция прогнозирования.
    Возвращает dict с историческими данными и прогнозом.
    """
    df = get_daily_series(db, cabinet_id, nm_id, days_back=40, metric=metric)

    if df.empty or len(df) < 5:
        return {
            "history": [],
            "forecast": [],
            "confidence_lower": [],
            "confidence_upper": [],
            "methods": {},
            "summary": {},
        }

    series = df["value"].values
    dates = df["day"].values

    # Методы прогнозирования
    pred_es = _exponential_smoothing(series, alpha=0.3, forecast_days=forecast_days)
    pred_holt = _holt_linear(series, alpha=0.3, beta=0.1, forecast_days=forecast_days)
    pred_seasonal = _seasonal_naive(series, season_length=7, forecast_days=forecast_days)
    pred_hw = _holt_winters_additive(series, season_length=7, forecast_days=forecast_days)

    # Ансамбль: взвешенное среднее (Холт-Уинтерс — вес 0.4, Холт — 0.3, сезонный — 0.2, ES — 0.1)
    ensemble = 0.1 * pred_es + 0.3 * pred_holt + 0.2 * pred_seasonal + 0.4 * pred_hw
    ensemble = np.maximum(ensemble, 0)

    # Доверительные интервалы
    lower, upper = _calc_confidence_intervals(series, ensemble, confidence=0.8)

    # Даты прогноза
    last_date = pd.Timestamp(dates[-1])
    forecast_dates = pd.date_range(start=last_date + timedelta(days=1), periods=forecast_days, freq="D")

    # Исторические данные
    history = [
        {"date": str(d)[:10], "value": round(float(v), 2)}
        for d, v in zip(dates, series)
    ]

    # Прогноз
    forecast_data = [
        {
            "date": str(d)[:10],
            "value": round(float(v), 2),
            "lower": round(float(lo), 2),
            "upper": round(float(up), 2),
        }
        for d, v, lo, up in zip(forecast_dates, ensemble, lower, upper)
    ]

    # Методы по отдельности (для сравнения)
    methods = {
        "exponential_smoothing": [round(float(v), 2) for v in pred_es],
        "holt_linear": [round(float(v), 2) for v in pred_holt],
        "seasonal_naive": [round(float(v), 2) for v in pred_seasonal],
        "holt_winters": [round(float(v), 2) for v in pred_hw],
        "ensemble": [round(float(v), 2) for v in ensemble],
    }

    # Сводка
    avg_historical = float(np.mean(series[-7:])) if len(series) >= 7 else float(np.mean(series))
    avg_forecast = float(np.mean(ensemble))
    trend_pct = ((avg_forecast - avg_historical) / avg_historical * 100) if avg_historical > 0 else 0

    total_forecast = float(np.sum(ensemble))

    summary = {
        "avg_historical_7d": round(avg_historical, 2),
        "avg_forecast": round(avg_forecast, 2),
        "trend_percent": round(trend_pct, 1),
        "total_forecast": round(total_forecast, 2),
        "forecast_days": forecast_days,
        "data_points": len(series),
        "metric": metric,
    }

    return {
        "history": history,
        "forecast": forecast_data,
        "confidence_lower": [],
        "confidence_upper": [],
        "methods": methods,
        "summary": summary,
    }


def forecast_top_products(
    db: Session,
    cabinet_id: str | None = None,
    forecast_days: int = 7,
    metric: str = "revenue",
    limit: int = 100,
) -> list[dict]:
    """Прогноз для топ-N товаров по выручке."""
    threshold = datetime.now() - timedelta(days=40)

    q = db.query(
        Order.nm_id,
        Order.supplier_article,
        Order.subject,
        Order.brand,
        func.sum(
            case((Order.is_cancel == False, Order.price_with_disc), else_=0)
        ).label("total_revenue"),
    ).filter(
        Order.date >= threshold,
        Order.is_cancel == False,
        Order.nm_id.isnot(None),
    )

    if cabinet_id:
        q = q.filter(Order.cabinet_id == cabinet_id)

    rows = (
        q.group_by(Order.nm_id, Order.supplier_article, Order.subject, Order.brand)
        .order_by(func.sum(
            case((Order.is_cancel == False, Order.price_with_disc), else_=0)
        ).desc())
        .limit(limit)
        .all()
    )

    results = []
    for r in rows:
        f = forecast(db, cabinet_id=cabinet_id, nm_id=r.nm_id, forecast_days=forecast_days, metric=metric)
        if f["summary"]:
            results.append({
                "cabinet_id": cabinet_id or "",
                "nm_id": r.nm_id,
                "supplier_article": r.supplier_article or "",
                "subject": r.subject or "",
                "brand": r.brand or "",
                "total_revenue_40d": round(float(r.total_revenue or 0), 2),
                "forecast": f["summary"],
            })

    return results
