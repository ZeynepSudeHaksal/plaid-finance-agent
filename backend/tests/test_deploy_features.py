"""Tests for the public-deployment features: DB URL handling, limits, demo mode, CORS."""
from datetime import datetime, timedelta

import pytest

import main
from models import Budget, ChatUsage, Transaction, User, normalize_database_url
from seed import cleanup_old_demo_users, create_demo_user

PASSWORD = "correct-horse-battery"


@pytest.fixture
def fake_agent(monkeypatch):
    """Replace the real model call so no test ever spends Anthropic credits."""
    calls = []

    def _run(db, message, user_id, history=None):
        calls.append((message, user_id))
        return "ok-reply", []

    monkeypatch.setattr(main.agent, "run_agent", _run)
    return calls


def _demo_headers(client):
    resp = client.post("/auth/demo")
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# --- Database URL ------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("postgres://u:p@host/db", "postgresql+psycopg2://u:p@host/db"),
    ("postgresql://u:p@host/db?sslmode=require", "postgresql+psycopg2://u:p@host/db?sslmode=require"),
    ("postgresql+psycopg2://u:p@host/db", "postgresql+psycopg2://u:p@host/db"),
    ("sqlite:///./x.db", "sqlite:///./x.db"),
])
def test_database_url_is_normalized(raw, expected):
    assert normalize_database_url(raw) == expected


# --- Demo mode ---------------------------------------------------------------------

def test_demo_creates_a_seeded_account(client, db):
    headers = _demo_headers(client)

    txns = client.get("/transactions?limit=500", headers=headers).json()
    assert len(txns) > 50
    assert any(t["amount"] < 0 for t in txns), "expected income rows"

    budgets = client.get("/budgets", headers=headers).json()
    assert {b["category"] for b in budgets} >= {"FOOD_AND_DRINK", "TRANSPORTATION"}

    assert client.get("/link/status", headers=headers).json() == {"linked": True, "is_demo": True}
    assert client.get("/spending/by-category", headers=headers).status_code == 200
    assert client.get("/alerts", headers=headers).status_code == 200


def test_each_demo_click_gets_its_own_isolated_account(client, db):
    h1 = _demo_headers(client)
    h2 = _demo_headers(client)

    client.post("/budgets", json={"category": "TRAVEL", "monthly_amount": 5}, headers=h1)

    cats2 = {b["category"] for b in client.get("/budgets", headers=h2).json()}
    assert "TRAVEL" not in cats2
    assert db.query(User).filter(User.is_demo.is_(True)).count() == 2


def test_demo_users_cannot_use_plaid_endpoints(client):
    headers = _demo_headers(client)

    assert client.post("/link/token", headers=headers).status_code == 403
    assert client.post("/link/exchange", json={"public_token": "x"}, headers=headers).status_code == 403
    assert client.post("/transactions/sync", headers=headers).status_code == 403


def test_old_demo_accounts_are_cleaned_up_but_real_users_are_not(client, db, register):
    register("real@gmail.com")
    old = create_demo_user(db)
    old.created_at = datetime.utcnow() - timedelta(hours=48)
    db.commit()
    old_id = old.id

    removed = cleanup_old_demo_users(db)

    assert removed == 1
    assert db.query(User).filter(User.id == old_id).first() is None
    assert db.query(Transaction).filter(Transaction.user_id == old_id).count() == 0
    assert db.query(Budget).filter(Budget.user_id == old_id).count() == 0
    assert db.query(User).filter(User.email == "real@gmail.com").count() == 1


def test_demo_creation_is_rate_limited(client, monkeypatch):
    monkeypatch.setenv("DEMO_RATE_PER_HOUR", "2")

    assert client.post("/auth/demo").status_code == 200
    assert client.post("/auth/demo").status_code == 200
    resp = client.post("/auth/demo")

    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


# --- Chat limits -------------------------------------------------------------------

def test_chat_returns_remaining_quota(client, register, fake_agent, monkeypatch):
    monkeypatch.setenv("CHAT_DAILY_LIMIT_USER", "3")
    headers, _ = register("a@gmail.com")

    body = client.post("/chat", json={"message": "hi"}, headers=headers).json()

    assert body["reply"] == "ok-reply"
    assert body["remaining_today"] == 2


def test_per_user_daily_limit(client, register, fake_agent, monkeypatch):
    monkeypatch.setenv("CHAT_DAILY_LIMIT_USER", "2")
    headers, _ = register("a@gmail.com")

    assert client.post("/chat", json={"message": "1"}, headers=headers).status_code == 200
    assert client.post("/chat", json={"message": "2"}, headers=headers).status_code == 200
    blocked = client.post("/chat", json={"message": "3"}, headers=headers)

    assert blocked.status_code == 429
    assert len(fake_agent) == 2, "the model must not be called once the cap is hit"


def test_demo_users_get_the_tighter_cap(client, fake_agent, monkeypatch):
    monkeypatch.setenv("CHAT_DAILY_LIMIT_DEMO", "1")
    monkeypatch.setenv("CHAT_DAILY_LIMIT_USER", "50")
    headers = _demo_headers(client)

    assert client.post("/chat", json={"message": "1"}, headers=headers).status_code == 200
    assert client.post("/chat", json={"message": "2"}, headers=headers).status_code == 429


def test_one_users_usage_does_not_use_up_anothers_cap(client, register, fake_agent, monkeypatch):
    monkeypatch.setenv("CHAT_DAILY_LIMIT_USER", "1")
    h1, _ = register("a@gmail.com")
    h2, _ = register("b@gmail.com")

    assert client.post("/chat", json={"message": "x"}, headers=h1).status_code == 200
    assert client.post("/chat", json={"message": "x"}, headers=h1).status_code == 429
    assert client.post("/chat", json={"message": "x"}, headers=h2).status_code == 200


def test_global_daily_cap_applies_across_users(client, register, fake_agent, monkeypatch):
    monkeypatch.setenv("CHAT_DAILY_LIMIT_GLOBAL", "2")
    h1, _ = register("a@gmail.com")
    h2, _ = register("b@gmail.com")
    h3, _ = register("c@gmail.com")

    assert client.post("/chat", json={"message": "x"}, headers=h1).status_code == 200
    assert client.post("/chat", json={"message": "x"}, headers=h2).status_code == 200
    resp = client.post("/chat", json={"message": "x"}, headers=h3)

    assert resp.status_code == 429
    assert "daily chat limit" in resp.json()["detail"]


def test_usage_from_yesterday_does_not_count_today(client, register, db, fake_agent, monkeypatch):
    monkeypatch.setenv("CHAT_DAILY_LIMIT_USER", "1")
    headers, user_id = register("a@gmail.com")
    db.add(ChatUsage(user_id=user_id, day="2000-01-01", count=99))
    db.commit()

    assert client.post("/chat", json={"message": "x"}, headers=headers).status_code == 200


def test_overlong_and_empty_messages_are_rejected_without_using_quota(client, register, db, fake_agent, monkeypatch):
    monkeypatch.setenv("MAX_MESSAGE_CHARS", "20")
    headers, user_id = register("a@gmail.com")

    assert client.post("/chat", json={"message": "x" * 21}, headers=headers).status_code == 400
    assert client.post("/chat", json={"message": "   "}, headers=headers).status_code == 400

    assert db.query(ChatUsage).filter(ChatUsage.user_id == user_id).count() == 0
    assert fake_agent == []


# --- Auth rate limiting ------------------------------------------------------------

def test_login_attempts_are_rate_limited(client, monkeypatch):
    monkeypatch.setenv("AUTH_RATE_PER_MINUTE", "3")
    client.post("/auth/signup", json={"email": "a@gmail.com", "password": PASSWORD})  # 1st hit

    codes = [
        client.post("/auth/login", json={"email": "a@gmail.com", "password": "wrong-password-1"}).status_code
        for _ in range(3)
    ]

    assert codes == [401, 401, 429]


# --- CORS --------------------------------------------------------------------------

def test_cors_origins_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com/, https://other.example.com")

    assert main._cors_origins() == ["https://app.example.com", "https://other.example.com"]


def test_cors_defaults_to_local_dev_only(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)

    origins = main._cors_origins()

    assert "*" not in origins
    assert "http://localhost:5173" in origins
