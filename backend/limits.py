"""
Abuse protection for a public deployment.

The chat box spends real Anthropic credits, so a public URL needs hard
ceilings. Three layers:

  1. Per-IP rate limits on signup / login / demo creation (in-memory,
     sliding window - fine for a single instance).
  2. Per-user and global DAILY chat-message caps, stored in the database
     (table chat_usage) so they survive restarts and redeploys.
  3. A maximum message length, so one message can't be a giant prompt.

All numbers come from environment variables (read at call time) so they can
be changed in the host dashboard without a code change.
"""
import os
import threading
import time
from collections import defaultdict, deque
from datetime import datetime

from fastapi import HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from models import ChatUsage, User


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


# --- Settings (env-driven) -----------------------------------------------------

def chat_limit_for(user: User) -> int:
    if user.is_demo:
        return _int_env("CHAT_DAILY_LIMIT_DEMO", 10)
    return _int_env("CHAT_DAILY_LIMIT_USER", 30)


def global_chat_limit() -> int:
    return _int_env("CHAT_DAILY_LIMIT_GLOBAL", 300)


def max_message_chars() -> int:
    return _int_env("MAX_MESSAGE_CHARS", 1000)


# --- Per-IP sliding-window rate limiter -----------------------------------------

_lock = threading.Lock()
_hits = defaultdict(deque)  # (bucket, ip) -> timestamps


def client_ip(request: Request) -> str:
    """Best-effort client IP. Behind a proxy (Render) the real IP is in X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_rate(bucket: str, ip: str, max_hits: int, window_seconds: int):
    now = time.monotonic()
    key = (bucket, ip)
    with _lock:
        hits = _hits[key]
        while hits and now - hits[0] > window_seconds:
            hits.popleft()
        if len(hits) >= max_hits:
            retry_after = int(window_seconds - (now - hits[0])) + 1
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Please wait a moment and try again.",
                headers={"Retry-After": str(retry_after)},
            )
        hits.append(now)


def reset_rate_limits():
    """Clear all in-memory counters (used by tests)."""
    with _lock:
        _hits.clear()


def auth_rate_limit(request: Request):
    """Dependency for /auth/signup and /auth/login: slows password guessing and mass signup."""
    _check_rate("auth", client_ip(request), _int_env("AUTH_RATE_PER_MINUTE", 10), 60)


def demo_rate_limit(request: Request):
    """Dependency for /auth/demo: each call creates a user + seed data."""
    _check_rate("demo", client_ip(request), _int_env("DEMO_RATE_PER_HOUR", 20), 3600)


# --- Daily chat quota (database-backed) -------------------------------------------

def _today() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def validate_message(message: str):
    text = message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="message cannot be empty")
    limit = max_message_chars()
    if len(text) > limit:
        raise HTTPException(status_code=400, detail=f"Message too long (max {limit} characters).")
    return text


def consume_chat_quota(db: Session, user: User) -> int:
    """Count one chat message against today's caps. Returns messages left for this user today.

    Raises 429 if either the user's own cap or the site-wide cap is used up.
    Counted BEFORE the model call, so failing requests can't be used to
    bypass the cap. (Under heavy concurrency the cap can be overshot by a
    request or two - acceptable for a spend guard.)
    """
    today = _today()

    global_used = (
        db.query(func.coalesce(func.sum(ChatUsage.count), 0)).filter(ChatUsage.day == today).scalar()
    )
    if global_used >= global_chat_limit():
        raise HTTPException(
            status_code=429,
            detail="The public demo has reached its daily chat limit. Please try again tomorrow.",
        )

    row = db.query(ChatUsage).filter(ChatUsage.user_id == user.id, ChatUsage.day == today).first()
    used = row.count if row else 0
    limit = chat_limit_for(user)
    if used >= limit:
        raise HTTPException(
            status_code=429,
            detail=f"Daily limit of {limit} messages reached. Please come back tomorrow.",
        )

    if row:
        row.count = used + 1
    else:
        db.add(ChatUsage(user_id=user.id, day=today, count=1))
    db.commit()
    return limit - (used + 1)
