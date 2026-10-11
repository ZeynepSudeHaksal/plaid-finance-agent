import time

import jwt
import pytest

import auth
from models import Budget, ChatMessage

PASSWORD = "correct-horse-battery"


# --- Authentication ---------------------------------------------------------

PROTECTED_ENDPOINTS = [
    ("GET", "/transactions", None),
    ("GET", "/categories", None),
    ("GET", "/budgets", None),
    ("GET", "/alerts", None),
    ("GET", "/link/status", None),
    ("GET", "/spending/by-category", None),
    ("GET", "/spending/timeseries", None),
    ("POST", "/link/token", None),
    ("POST", "/transactions/sync", None),
    ("POST", "/chat", {"message": "hello"}),
    ("POST", "/chat/reset", None),
    ("POST", "/budgets", {"category": "FOOD_AND_DRINK", "monthly_amount": 100}),
    ("DELETE", "/budgets/FOOD_AND_DRINK", None),
]


@pytest.mark.parametrize("method,path,body", PROTECTED_ENDPOINTS)
def test_protected_endpoints_reject_anonymous_requests(client, method, path, body):
    resp = client.request(method, path, json=body)
    assert resp.status_code == 401, f"{method} {path} returned {resp.status_code}"


def test_health_is_public(client):
    assert client.get("/health").status_code == 200


def test_signup_then_login(client):
    signup = client.post("/auth/signup", json={"email": "alice@gmail.com", "password": PASSWORD})
    assert signup.status_code == 200
    assert signup.json()["access_token"]

    login = client.post("/auth/login", json={"email": "alice@gmail.com", "password": PASSWORD})
    assert login.status_code == 200
    assert login.json()["email"] == "alice@gmail.com"


def test_wrong_password_is_rejected(client):
    client.post("/auth/signup", json={"email": "alice@gmail.com", "password": PASSWORD})

    resp = client.post("/auth/login", json={"email": "alice@gmail.com", "password": "wrong-password-123"})

    assert resp.status_code == 401


def test_unknown_email_gets_the_same_error_as_a_wrong_password(client):
    client.post("/auth/signup", json={"email": "alice@gmail.com", "password": PASSWORD})

    wrong_password = client.post("/auth/login", json={"email": "alice@gmail.com", "password": "wrong-password-123"})
    unknown_email = client.post("/auth/login", json={"email": "nobody@gmail.com", "password": PASSWORD})

    # Same status and message, so the endpoint can't be used to discover which emails exist.
    assert unknown_email.status_code == wrong_password.status_code == 401
    assert unknown_email.json() == wrong_password.json()


def test_duplicate_signup_is_rejected(client):
    client.post("/auth/signup", json={"email": "alice@gmail.com", "password": PASSWORD})

    resp = client.post("/auth/signup", json={"email": "alice@gmail.com", "password": PASSWORD})

    assert resp.status_code == 400


def test_short_password_is_rejected(client):
    resp = client.post("/auth/signup", json={"email": "alice@gmail.com", "password": "short"})

    assert resp.status_code == 400


def test_passwords_are_stored_hashed(client, db):
    from models import User

    client.post("/auth/signup", json={"email": "alice@gmail.com", "password": PASSWORD})

    stored = db.query(User).filter(User.email == "alice@gmail.com").one().password_hash
    assert PASSWORD not in stored
    assert stored.startswith("$2")  # bcrypt


def test_garbage_token_is_rejected(client):
    resp = client.get("/transactions", headers={"Authorization": "Bearer not-a-real-token"})

    assert resp.status_code == 401


def test_expired_token_is_rejected(client, register):
    _, user_id = register("alice@gmail.com")
    expired = jwt.encode({"sub": str(user_id), "exp": int(time.time()) - 60}, auth.SECRET_KEY, algorithm=auth.ALGORITHM)

    resp = client.get("/transactions", headers={"Authorization": f"Bearer {expired}"})

    assert resp.status_code == 401


def test_token_signed_with_a_different_secret_is_rejected(client, register):
    _, user_id = register("alice@gmail.com")
    forged = jwt.encode({"sub": str(user_id), "exp": int(time.time()) + 600}, "some-other-secret", algorithm="HS256")

    resp = client.get("/transactions", headers={"Authorization": f"Bearer {forged}"})

    assert resp.status_code == 401


# --- Isolation: one account can never see or change another's data ------------

def test_users_only_see_their_own_transactions(client, register, add_txn):
    alice_headers, alice_id = register("alice@gmail.com")
    bob_headers, _ = register("bob@gmail.com")
    add_txn(alice_id, "2026-09-01", 25.00, "FOOD_AND_DRINK", name="Alice's lunch")

    assert len(client.get("/transactions", headers=alice_headers).json()) == 1
    assert client.get("/transactions", headers=bob_headers).json() == []
    assert client.get("/categories", headers=bob_headers).json()["categories"] == []
    assert client.get("/spending/by-category", headers=bob_headers).json()["total"] == 0
    assert client.get("/spending/timeseries", headers=bob_headers).json()["points"] == []


def test_users_have_separate_budgets_even_for_the_same_category(client, register):
    alice_headers, _ = register("alice@gmail.com")
    bob_headers, _ = register("bob@gmail.com")

    client.post("/budgets", json={"category": "FOOD_AND_DRINK", "monthly_amount": 100}, headers=alice_headers)
    client.post("/budgets", json={"category": "FOOD_AND_DRINK", "monthly_amount": 999}, headers=bob_headers)

    assert client.get("/budgets", headers=alice_headers).json() == [{"category": "FOOD_AND_DRINK", "monthly_amount": 100.0}]
    assert client.get("/budgets", headers=bob_headers).json() == [{"category": "FOOD_AND_DRINK", "monthly_amount": 999.0}]


def test_a_user_cannot_delete_someone_elses_budget(client, register, db):
    alice_headers, alice_id = register("alice@gmail.com")
    bob_headers, _ = register("bob@gmail.com")
    client.post("/budgets", json={"category": "FOOD_AND_DRINK", "monthly_amount": 100}, headers=alice_headers)

    resp = client.delete("/budgets/FOOD_AND_DRINK", headers=bob_headers)

    assert resp.status_code == 404
    assert db.query(Budget).filter(Budget.user_id == alice_id).count() == 1


def test_resetting_chat_only_clears_your_own_history(client, register, db):
    alice_headers, alice_id = register("alice@gmail.com")
    bob_headers, bob_id = register("bob@gmail.com")
    db.add(ChatMessage(user_id=alice_id, role="user", content="alice question"))
    db.add(ChatMessage(user_id=bob_id, role="user", content="bob question"))
    db.commit()

    assert client.post("/chat/reset", headers=bob_headers).status_code == 200

    db.expire_all()
    assert db.query(ChatMessage).filter(ChatMessage.user_id == bob_id).count() == 0
    assert db.query(ChatMessage).filter(ChatMessage.user_id == alice_id).count() == 1


def test_alerts_only_reflect_your_own_budgets(client, register, add_txn):
    alice_headers, alice_id = register("alice@gmail.com")
    bob_headers, _ = register("bob@gmail.com")
    from datetime import date

    today = date.today().isoformat()
    add_txn(alice_id, today, 500.00, "FOOD_AND_DRINK")
    client.post("/budgets", json={"category": "FOOD_AND_DRINK", "monthly_amount": 100}, headers=alice_headers)

    alice_alerts = client.get("/alerts", headers=alice_headers).json()["alerts"]
    bob_alerts = client.get("/alerts", headers=bob_headers).json()["alerts"]

    assert any(a["severity"] == "over" for a in alice_alerts)
    assert bob_alerts == []


def test_link_status_is_per_user(client, register, db):
    from models import PlaidItem

    alice_headers, alice_id = register("alice@gmail.com")
    bob_headers, _ = register("bob@gmail.com")
    db.add(PlaidItem(item_id="item-a", user_id=alice_id, access_token="x"))
    db.commit()

    assert client.get("/link/status", headers=alice_headers).json() == {"linked": True, "is_demo": False}
    assert client.get("/link/status", headers=bob_headers).json() == {"linked": False, "is_demo": False}
