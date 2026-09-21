"""Общая конфигурация тестов WB Sync.

Тесты unit-level и не требуют PostgreSQL: перед импортом app.* подставляем
SQLite in-memory как DATABASE_URL (движок создаётся, но не подключается,
пока не начнутся запросы). Функции с pg-специфичным INSERT..ON CONFLICT
не тестируем — для них нужны интеграционные тесты с реальным PostgreSQL.
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

# CAB — общий идентификатор кабинета для фикстур
CAB = "test-cabinet-0123456789abcdef"
