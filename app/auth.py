"""
Auth module — session-based authentication with bcrypt passwords.
Uses starlette SessionMiddleware (signed cookie).
"""
import hashlib
import time
from collections import defaultdict
from datetime import datetime

from fastapi import Request, HTTPException, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, UserCabinetAccess
from app.crud import get_user_by_username

# ---- PASSWORD HASHING ----
import bcrypt


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ---- RATE LIMITING ----
_login_attempts: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT_MAX = 5
RATE_LIMIT_WINDOW = 300  # 5 minutes


def check_rate_limit(ip: str) -> bool:
    now = time.time()
    _login_attempts[ip] = [t for t in _login_attempts[ip] if now - t < RATE_LIMIT_WINDOW]
    return len(_login_attempts[ip]) < RATE_LIMIT_MAX


def record_failed_login(ip: str):
    _login_attempts[ip].append(time.time())


def clear_rate_limit(ip: str):
    _login_attempts.pop(ip, None)


# ---- SESSION HELPERS ----
SESSION_KEY_USER_ID = "user_id"
SESSION_KEY_IS_ADMIN = "is_admin"


def get_session_user_id(request: Request) -> int | None:
    return request.session.get(SESSION_KEY_USER_ID)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    uid = get_session_user_id(request)
    if not uid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = db.query(User).filter(User.id == uid).first()
    if not user or not user.is_active:
        request.session.clear()
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


def login_required(request: Request, db: Session = Depends(get_db)) -> User:
    """Dependency: redirects to /login if not authenticated."""
    uid = get_session_user_id(request)
    if not uid:
        raise HTTPException(status_code=307, headers={"Location": "/login"})
    user = db.query(User).filter(User.id == uid).first()
    if not user or not user.is_active:
        request.session.clear()
        raise HTTPException(status_code=307, headers={"Location": "/login"})
    return user


def admin_required(request: Request, db: Session = Depends(get_db)) -> User:
    """Dependency: requires admin."""
    user = login_required(request, db)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# ---- CABINET ACCESS ----
def get_user_cabinet_ids(user: User, db: Session) -> list[str] | None:
    """
    Returns list of allowed cabinet_ids for user, or None if access_all.
    Admin always gets None (all cabinets).
    """
    if user.is_admin:
        return None
    rows = db.query(UserCabinetAccess).filter(UserCabinetAccess.user_id == user.id).all()
    if not rows:
        return []
    if any(r.access_all for r in rows):
        return None
    return [r.cabinet_id for r in rows]
