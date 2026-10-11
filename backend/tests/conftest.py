"""
Shared test setup.

IMPORTANT: the environment is configured *before* any app module is
imported, because models.py / auth.py read settings at import time. Tests run
against a throwaway SQLite file and fake secrets - they never touch your real
finance_agent.db or your real .env values (python-dotenv doesn't override
variables that are already set).
"""
import itertools
import os
import tempfile

from cryptography.fernet import Fernet

_tmpdir = tempfile.mkdtemp(prefix="finance-agent-tests-")
# CI sets TEST_DATABASE_URL to run the same suite against a real Postgres.
os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL") or f"sqlite:///{_tmpdir}/test.db"
os.environ["JWT_SECRET"] = "test-jwt-secret-not-a-real-secret"
os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ["ANTHROPIC_API_KEY"] = "test-anthropic-key"

import pytest  # noqa: E402

from models import Base, engine, SessionLocal, User, Transaction  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    """Every test starts from empty tables."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture(autouse=True)
def clean_limits(monkeypatch):
    """Rate-limit counters live in memory; reset them so tests can't affect each other."""
    import limits

    limits.reset_rate_limits()
    for name in ("CHAT_DAILY_LIMIT_USER", "CHAT_DAILY_LIMIT_DEMO", "CHAT_DAILY_LIMIT_GLOBAL",
                 "MAX_MESSAGE_CHARS", "AUTH_RATE_PER_MINUTE", "DEMO_RATE_PER_HOUR"):
        monkeypatch.delenv(name, raising=False)
    yield
    limits.reset_rate_limits()


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def make_user(db):
    def _make(email="user@gmail.com"):
        user = User(email=email, password_hash="not-a-real-hash")
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    return _make


@pytest.fixture
def add_txn(db):
    """Insert a transaction. Plaid convention: positive amount = money out, negative = money in."""
    counter = itertools.count(1)

    def _add(user_id, date, amount, category="FOOD_AND_DRINK", name="Shop", pending=False):
        txn = Transaction(
            transaction_id=f"txn-{next(counter)}",
            item_id="item-1",
            user_id=user_id,
            account_id="acct-1",
            date=date,
            name=name,
            amount=amount,
            category=category,
            pending=pending,
        )
        db.add(txn)
        db.commit()
        return txn

    return _add


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from main import app

    return TestClient(app)


@pytest.fixture
def register(client, db):
    """Sign a user up through the real API. Returns (auth_headers, user_id)."""

    def _register(email):
        resp = client.post("/auth/signup", json={"email": email, "password": "correct-horse-battery"})
        assert resp.status_code == 200, resp.text
        token = resp.json()["access_token"]
        user = db.query(User).filter(User.email == email).one()
        return {"Authorization": f"Bearer {token}"}, user.id

    return _register
