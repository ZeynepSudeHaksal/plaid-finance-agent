import pytest
from cryptography.fernet import Fernet
from sqlalchemy import inspect, text

import crypto
import models
from models import PlaidItem


# --- Token encryption (unit) --------------------------------------------------

def test_round_trip_and_ciphertext_differs_from_plaintext():
    stored = crypto.encrypt_token("access-sandbox-abc123")

    assert stored.startswith("enc:")
    assert "access-sandbox-abc123" not in stored
    assert crypto.decrypt_token(stored) == "access-sandbox-abc123"


def test_encrypting_twice_gives_different_ciphertexts():
    assert crypto.encrypt_token("same") != crypto.encrypt_token("same")


def test_legacy_plaintext_passes_through():
    assert crypto.decrypt_token("access-sandbox-legacy") == "access-sandbox-legacy"
    assert not crypto.is_encrypted("access-sandbox-legacy")


def test_decrypting_with_the_wrong_key_fails_loudly(monkeypatch):
    stored = crypto.encrypt_token("secret")
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())

    with pytest.raises(RuntimeError, match="Re-link"):
        crypto.decrypt_token(stored)


def test_missing_key_gives_a_clear_error(monkeypatch):
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)

    with pytest.raises(RuntimeError, match="ENCRYPTION_KEY"):
        crypto.encrypt_token("x")


def test_malformed_key_gives_a_clear_error(monkeypatch):
    monkeypatch.setenv("ENCRYPTION_KEY", "not-a-real-key")

    with pytest.raises(RuntimeError, match="valid Fernet key"):
        crypto.encrypt_token("x")


# --- Through the real API -------------------------------------------------------

def test_link_exchange_stores_the_token_encrypted(client, register, db, monkeypatch):
    import plaid_client

    monkeypatch.setattr(
        plaid_client,
        "exchange_public_token",
        lambda public_token: {"access_token": "access-sandbox-xyz", "item_id": "item-1"},
    )
    headers, user_id = register("alice@gmail.com")

    resp = client.post("/link/exchange", json={"public_token": "public-sandbox-1"}, headers=headers)

    assert resp.status_code == 200
    stored = db.query(PlaidItem).filter_by(item_id="item-1").one()
    assert stored.user_id == user_id
    assert stored.access_token != "access-sandbox-xyz"
    assert "access-sandbox-xyz" not in stored.access_token
    assert crypto.decrypt_token(stored.access_token) == "access-sandbox-xyz"


def test_link_exchange_without_an_encryption_key_is_a_readable_error(client, register, monkeypatch):
    import plaid_client

    monkeypatch.setattr(
        plaid_client, "exchange_public_token", lambda public_token: {"access_token": "t", "item_id": "item-1"}
    )
    headers, _ = register("alice@gmail.com")
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)

    resp = client.post("/link/exchange", json={"public_token": "public-sandbox-1"}, headers=headers)

    assert resp.status_code == 500
    assert "ENCRYPTION_KEY" in resp.json()["detail"]


# --- Schema migration ------------------------------------------------------------

def test_init_db_adds_missing_columns_to_an_existing_database():
    """An older database (no sync_cursor column) is upgraded in place - no need to delete it."""
    models.Base.metadata.tables["plaid_items"].drop(models.engine)
    with models.engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE plaid_items ("
                "item_id VARCHAR PRIMARY KEY, user_id INTEGER, access_token VARCHAR NOT NULL, "
                "institution_name VARCHAR, created_at DATETIME)"
            )
        )
        conn.execute(text("INSERT INTO plaid_items (item_id, user_id, access_token) VALUES ('old', 1, 'tok')"))
    before = {c["name"] for c in inspect(models.engine).get_columns("plaid_items")}
    assert "sync_cursor" not in before

    models.init_db()

    after = {c["name"] for c in inspect(models.engine).get_columns("plaid_items")}
    assert "sync_cursor" in after
    with models.engine.begin() as conn:  # existing rows survive the upgrade
        assert conn.execute(text("SELECT access_token FROM plaid_items WHERE item_id='old'")).scalar() == "tok"


def test_init_db_is_safe_to_run_repeatedly():
    models.init_db()
    models.init_db()  # second run must not fail trying to re-add the column
