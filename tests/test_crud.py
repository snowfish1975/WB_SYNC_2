"""Тесты чистых функций app/crud.py (без обращения к БД).

Функции upsert_* используют pg-специфичный INSERT..ON CONFLICT и требуют
PostgreSQL — они покрываются интеграционными тестами на стенде.
"""
import hashlib
import os

from app import crud


class TestParseDate:
    def test_standard_iso(self):
        assert crud.parse_date("2026-09-15T10:30:00") == __import__("datetime").datetime(2026, 9, 15, 10, 30)

    def test_with_milliseconds(self):
        """Даты с миллисекундами обрезаются до секунд."""
        assert crud.parse_date("2026-09-15T10:30:00.123456") == __import__("datetime").datetime(2026, 9, 15, 10, 30)

    def test_zero_date_is_none(self):
        """0001-01-01 — WB шлёт такую заглушку, должна стать None."""
        assert crud.parse_date("0001-01-01T00:00:00") is None

    def test_empty_is_none(self):
        assert crud.parse_date("") is None
        assert crud.parse_date(None) is None

    def test_garbage_is_none(self):
        assert crud.parse_date("not a date") is None


class TestLoadTokensMapping:
    def test_env_json_mapping(self, monkeypatch):
        token = "secret-token-abc"
        monkeypatch.setenv("WB_TOKENS_JSON", '{"Кабинет Х": "%s"}' % token)
        mapping = crud.load_tokens_mapping()
        expected_id = hashlib.sha256(token.encode()).hexdigest()[:32]
        assert mapping == {expected_id: "Кабинет Х"}

    def test_invalid_json_falls_back_to_empty(self, monkeypatch):
        monkeypatch.setenv("WB_TOKENS_JSON", "{broken json")
        assert crud.load_tokens_mapping() == {}

    def test_empty_env(self, monkeypatch):
        monkeypatch.setenv("WB_TOKENS_JSON", "{}")
        assert crud.load_tokens_mapping() == {}


class TestTokenHashConvention:
    def test_hash_is_sha256_first32(self):
        """cabinet_id = sha256(token)[:32] — конвенция, от которой зависит всё API."""
        token = "eyJhbGciOiJFUzI1NiIsImtpZCI6IjIwMjQwOSJ9.test"
        h = hashlib.sha256(token.encode()).hexdigest()[:32]
        assert len(h) == 32
        # повторная генерация детерминирована
        assert hashlib.sha256(token.encode()).hexdigest()[:32] == h
