"""
Authentication: password hashing (bcrypt) and JWT-based sessions.

Flow: /auth/signup or /auth/login returns a JWT. The frontend sends it
back as `Authorization: Bearer <token>` on every request. get_current_user
verifies it and loads the User row, so every other endpoint can scope
its queries to that user.
"""
import os
from datetime import datetime, timedelta

import bcrypt
import jwt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, Header
from sqlalchemy.orm import Session

from models import get_db, User

# Load .env here rather than relying on main.py having done it first -
# this module reads JWT_SECRET at import time, so import order matters.
load_dotenv()

SECRET_KEY = os.getenv("JWT_SECRET")
ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 7


def _require_secret():
    if not SECRET_KEY:
        raise RuntimeError(
            "JWT_SECRET is not set in .env. Generate one with: "
            "python3 -c \"import secrets; print(secrets.token_hex(32))\""
        )


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


def create_token(user_id: int) -> str:
    _require_secret()
    payload = {"sub": str(user_id), "exp": datetime.utcnow() + timedelta(days=TOKEN_EXPIRE_DAYS)}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(authorization: str = Header(None), db: Session = Depends(get_db)) -> User:
    """FastAPI dependency: extracts and verifies the bearer token, returns the User row."""
    _require_secret()

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = authorization[len("Bearer "):]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload["sub"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired, please log in again")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid authentication token")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user