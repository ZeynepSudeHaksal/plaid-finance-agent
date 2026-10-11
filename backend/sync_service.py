"""
Incremental transaction sync for one linked bank item.

Plaid's /transactions/sync is a cursor-based change feed: each response
carries added / modified / removed transactions plus a `next_cursor`. If
you save that cursor and send it next time, Plaid returns only what changed
since. Starting from scratch every time (cursor=None) re-downloads the full
history on every sync and never sees updates to existing transactions.

Design notes:
- Each page's rows and the new cursor are committed together, so a crash
  mid-sync can't advance the cursor past data that wasn't saved.
- `modified` covers things like a pending charge settling; `removed` covers
  pending charges that were replaced by their posted version.
- The Plaid call is a parameter (`fetch_page`) so tests can feed in canned
  pages instead of calling the real API.
"""
from typing import Callable, Optional

from sqlalchemy.orm import Session

import plaid_client
from crypto import decrypt_token, encrypt_token, is_encrypted
from models import PlaidItem, Transaction


def _to_row(txn, item: PlaidItem) -> Transaction:
    category = getattr(txn, "personal_finance_category", None)
    return Transaction(
        transaction_id=txn.transaction_id,
        item_id=item.item_id,
        user_id=item.user_id,
        account_id=txn.account_id,
        date=str(txn.date),
        name=txn.name,
        amount=txn.amount,
        category=category.primary if category else None,
        pending=bool(getattr(txn, "pending", False)),
    )


def sync_item(db: Session, item: PlaidItem, fetch_page: Optional[Callable] = None) -> dict:
    """Sync one item from its saved cursor. Returns counts of added/modified/removed rows."""
    fetch_page = fetch_page or plaid_client.sync_transactions

    # Upgrade a legacy plaintext token to encrypted storage the first time we touch it.
    if not is_encrypted(item.access_token):
        item.access_token = encrypt_token(item.access_token)
        db.commit()
    access_token = decrypt_token(item.access_token)

    counts = {"added": 0, "modified": 0, "removed": 0}
    cursor = item.sync_cursor
    has_more = True

    while has_more:
        page = fetch_page(access_token, cursor)

        for txn in page["added"]:
            db.merge(_to_row(txn, item))
            counts["added"] += 1

        for txn in page["modified"]:
            db.merge(_to_row(txn, item))
            counts["modified"] += 1

        for txn in page["removed"]:
            # Scoped to this user so a removal can never touch another account's rows.
            db.query(Transaction).filter(
                Transaction.transaction_id == txn.transaction_id,
                Transaction.user_id == item.user_id,
            ).delete(synchronize_session=False)
            counts["removed"] += 1

        cursor = page["next_cursor"]
        has_more = page["has_more"]
        item.sync_cursor = cursor
        db.commit()  # rows and cursor land together

    return counts