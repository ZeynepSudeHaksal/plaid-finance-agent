from types import SimpleNamespace

import pytest

from crypto import decrypt_token, encrypt_token, is_encrypted
from models import PlaidItem, Transaction
from sync_service import sync_item


def plaid_txn(txn_id, amount=10.0, date="2026-09-01", category="FOOD_AND_DRINK", pending=False, name="Shop"):
    """A stand-in for a Plaid transaction object (only the fields our code reads)."""
    return SimpleNamespace(
        transaction_id=txn_id,
        account_id="acct-1",
        date=date,
        name=name,
        amount=amount,
        personal_finance_category=SimpleNamespace(primary=category) if category else None,
        pending=pending,
    )


def page(added=(), modified=(), removed=(), next_cursor="cursor-1", has_more=False):
    return {
        "added": list(added),
        "modified": list(modified),
        "removed": [SimpleNamespace(transaction_id=t) for t in removed],
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


class FakePlaid:
    """Replaces the Plaid API call: returns queued pages and records how it was called."""

    def __init__(self, *pages):
        self.pages = list(pages)
        self.calls = []  # (access_token, cursor) for each request

    def __call__(self, access_token, cursor):
        self.calls.append((access_token, cursor))
        return self.pages.pop(0)  # raises IndexError if the code asks for more pages than expected


@pytest.fixture
def item(db, make_user):
    user = make_user()
    row = PlaidItem(item_id="item-1", user_id=user.id, access_token=encrypt_token("access-secret"))
    db.add(row)
    db.commit()
    return row


def test_first_sync_starts_from_no_cursor_and_saves_the_new_one(db, item):
    fake = FakePlaid(page(added=[plaid_txn("t1"), plaid_txn("t2")], next_cursor="cursor-A"))

    counts = sync_item(db, item, fetch_page=fake)

    assert counts == {"added": 2, "modified": 0, "removed": 0}
    assert fake.calls[0][1] is None
    db.refresh(item)
    assert item.sync_cursor == "cursor-A"
    assert db.query(Transaction).count() == 2


def test_next_sync_resumes_from_the_saved_cursor(db, item):
    sync_item(db, item, fetch_page=FakePlaid(page(added=[plaid_txn("t1")], next_cursor="cursor-A")))

    second = FakePlaid(page(added=[plaid_txn("t2")], next_cursor="cursor-B"))
    sync_item(db, item, fetch_page=second)

    assert second.calls[0][1] == "cursor-A"  # not None - it does NOT re-download everything
    assert db.query(Transaction).count() == 2


def test_pagination_follows_the_cursor_chain(db, item):
    fake = FakePlaid(
        page(added=[plaid_txn("t1")], next_cursor="c1", has_more=True),
        page(added=[plaid_txn("t2")], next_cursor="c2", has_more=True),
        page(added=[plaid_txn("t3")], next_cursor="c3", has_more=False),
    )

    counts = sync_item(db, item, fetch_page=fake)

    assert [c[1] for c in fake.calls] == [None, "c1", "c2"]
    assert counts["added"] == 3
    db.refresh(item)
    assert item.sync_cursor == "c3"


def test_modified_transactions_update_existing_rows(db, item):
    sync_item(db, item, fetch_page=FakePlaid(page(added=[plaid_txn("t1", amount=10.0, pending=True)])))

    counts = sync_item(db, item, fetch_page=FakePlaid(page(modified=[plaid_txn("t1", amount=12.5, pending=False)], next_cursor="c2")))

    assert counts["modified"] == 1
    row = db.query(Transaction).filter_by(transaction_id="t1").one()
    db.refresh(row)
    assert row.amount == 12.5
    assert row.pending is False
    assert db.query(Transaction).count() == 1  # updated in place, not duplicated


def test_removed_transactions_are_deleted(db, item):
    sync_item(db, item, fetch_page=FakePlaid(page(added=[plaid_txn("t1"), plaid_txn("t2")])))

    counts = sync_item(db, item, fetch_page=FakePlaid(page(removed=["t1"], next_cursor="c2")))

    assert counts["removed"] == 1
    assert [t.transaction_id for t in db.query(Transaction).all()] == ["t2"]


def test_a_removal_cannot_touch_another_users_transactions(db, item, make_user, add_txn):
    other = make_user("other@gmail.com")
    victim = add_txn(other.id, "2026-09-01", 10.0)  # belongs to a different account

    sync_item(db, item, fetch_page=FakePlaid(page(removed=[victim.transaction_id])))

    assert db.query(Transaction).filter_by(transaction_id=victim.transaction_id).count() == 1


def test_synced_rows_belong_to_the_items_owner(db, item):
    sync_item(db, item, fetch_page=FakePlaid(page(added=[plaid_txn("t1")])))

    assert db.query(Transaction).one().user_id == item.user_id


def test_category_is_optional(db, item):
    sync_item(db, item, fetch_page=FakePlaid(page(added=[plaid_txn("t1", category=None)])))

    assert db.query(Transaction).one().category is None


def test_plaid_is_called_with_the_decrypted_token(db, item):
    fake = FakePlaid(page())

    sync_item(db, item, fetch_page=fake)

    assert fake.calls[0][0] == "access-secret"
    assert is_encrypted(item.access_token)  # still encrypted at rest


def test_legacy_plaintext_tokens_still_work_and_get_encrypted(db, make_user):
    user = make_user()
    legacy = PlaidItem(item_id="old-item", user_id=user.id, access_token="access-legacy-plaintext")
    db.add(legacy)
    db.commit()
    fake = FakePlaid(page())

    sync_item(db, legacy, fetch_page=fake)

    assert fake.calls[0][0] == "access-legacy-plaintext"
    db.refresh(legacy)
    assert is_encrypted(legacy.access_token)
    assert decrypt_token(legacy.access_token) == "access-legacy-plaintext"


def test_a_failure_mid_sync_keeps_progress_and_resumes_from_it(db, item):
    class FailsOnSecondPage:
        def __init__(self):
            self.calls = 0

        def __call__(self, access_token, cursor):
            self.calls += 1
            if self.calls == 1:
                return page(added=[plaid_txn("t1")], next_cursor="c1", has_more=True)
            raise ConnectionError("plaid went away")

    with pytest.raises(ConnectionError):
        sync_item(db, item, fetch_page=FailsOnSecondPage())

    # Page one was saved together with its cursor, so nothing is lost or skipped...
    db.refresh(item)
    assert item.sync_cursor == "c1"
    assert db.query(Transaction).filter_by(transaction_id="t1").count() == 1

    # ...and the retry picks up exactly where it stopped.
    retry = FakePlaid(page(added=[plaid_txn("t2")], next_cursor="c2"))
    sync_item(db, item, fetch_page=retry)
    assert retry.calls[0][1] == "c1"
    assert db.query(Transaction).count() == 2
