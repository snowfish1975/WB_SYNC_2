"""
Миграция: добавление таблиц users, api_keys, wb_tokens
Запуск: python migrate_add_auth_tables.py
"""

import os
import sys
from sqlalchemy import text
from app.database import engine, SessionLocal
from app.models import Base, User, ApiKey, WbToken
from app.crud import create_user, create_wb_token

def migrate():
    """Создание новых таблиц."""
    print("Создание таблиц users, api_keys, wb_tokens...")
    
    # Создаём таблицы
    Base.metadata.create_all(bind=engine)
    
    print("Таблицы успешно созданы!")
    
    # Проверяем, есть ли уже токены в env var
    import json
    raw = os.getenv("WB_TOKENS_JSON", "{}")
    try:
        tokens_data = json.loads(raw)
    except json.JSONDecodeError:
        tokens_data = {}
    
    if tokens_data:
        print(f"\nНайдено {len(tokens_data)} токенов в WB_TOKENS_JSON.")
        print("Хотите импортировать их в БД? (y/n): ", end="")
        
        if input().strip().lower() == 'y':
            db = SessionLocal()
            try:
                # Создаём дефолтного пользователя
                user = create_user(db, username="admin", email="admin@example.com")
                print(f"Создан пользователь: {user.username} (id={user.id})")
                
                # Импортируем токены
                for name, token in tokens_data.items():
                    wb_token = create_wb_token(db, user.id, name, token)
                    print(f"Импортирован токен: {name} (cabinet_id={wb_token.token_hash})")
                
                print(f"\nИмпорт завершён! Всего {len(tokens_data)} токенов.")
                print("Теперь можете удалить переменную WB_TOKENS_JSON из env.")
            finally:
                db.close()
    
    print("\nМиграция завершена успешно!")

if __name__ == "__main__":
    migrate()
