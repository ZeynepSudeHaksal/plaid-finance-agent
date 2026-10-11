"""
Demo-account support: creates a throwaway user with realistic seeded data so
a visitor can try the whole app (charts, budgets, alerts, chat) in one click,
without Plaid or signing up.

Transactions are generated relative to today (about 3 months back) so the
dashboard always looks current. Amounts follow Plaid's convention: positive =
money out, negative = money in. A couple of deliberately odd transactions are
included so the "anything unusual?" question has something to find.
"""
import random
import secrets
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from auth import hash_password
from models import Budget, ChatMessage, Transaction, User

DEMO_RETENTION_HOURS = 24

# (merchant, category, low, high)
_EVERYDAY = [
    ("Whole Foods Market", "FOOD_AND_DRINK", 28, 95),
    ("Trader Joe's", "FOOD_AND_DRINK", 22, 70),
    ("Starbucks", "FOOD_AND_DRINK", 4, 9),
    ("Chipotle", "FOOD_AND_DRINK", 11, 19),
    ("Uber Eats", "FOOD_AND_DRINK", 18, 42),
    ("Uber", "TRANSPORTATION", 8, 32),
    ("Shell", "TRANSPORTATION", 30, 58),
    ("Amazon", "GENERAL_MERCHANDISE", 12, 85),
    ("Target", "GENERAL_MERCHANDISE", 15, 90),
    ("AMC Theatres", "ENTERTAINMENT", 14, 32),
]

_MONTHLY = [
    # (merchant, category, amount, day_of_month)
    ("Brookline Apartments - Rent", "RENT_AND_UTILITIES", 1850.00, 1),
    ("Con Edison", "RENT_AND_UTILITIES", 96.40, 8),
    ("Verizon", "RENT_AND_UTILITIES", 72.00, 12),
    ("Netflix", "ENTERTAINMENT", 15.49, 15),
    ("Spotify", "ENTERTAINMENT", 11.99, 17),
    ("Equinox", "PERSONAL_CARE", 40.00, 5),
]

DEMO_BUDGETS = {
    "FOOD_AND_DRINK": 450.0,
    "TRANSPORTATION": 150.0,
    "ENTERTAINMENT": 80.0,
}


def seed_demo_data(db: Session, user_id: int, rng: random.Random = None, today: date = None):
    rng = rng or random.Random()
    today = today or date.today()
    start = today - timedelta(days=90)
    prefix = f"demo-{user_id}"
    n = 0

    def add(day: date, name: str, category: str, amount: float):
        nonlocal n
        n += 1
        db.add(Transaction(
            transaction_id=f"{prefix}-{n}",
            item_id=f"{prefix}-item",
            user_id=user_id,
            account_id=f"{prefix}-checking",
            date=day.isoformat(),
            name=name,
            amount=round(amount, 2),
            category=category,
            pending=False,
        ))

    day = start
    while day <= today:
        # ~1.3 everyday purchases per day on average
        for _ in range(rng.choice([0, 1, 1, 1, 2, 3])):
            merchant, category, low, high = rng.choice(_EVERYDAY)
            add(day, merchant, category, rng.uniform(low, high))

        for merchant, category, amount, dom in _MONTHLY:
            if day.day == dom:
                add(day, merchant, category, amount)

        if day.day in (1, 15):
            add(day, "Acme Corp Payroll", "INCOME", -2450.00)

        day += timedelta(days=1)

    # Planted outliers: what "anything unusual?" should surface.
    add(today - timedelta(days=9), "Best Buy - 4K Monitor", "GENERAL_MERCHANDISE", 689.99)
    add(today - timedelta(days=22), "Delta Air Lines", "TRAVEL", 412.30)

    for category, amount in DEMO_BUDGETS.items():
        db.add(Budget(user_id=user_id, category=category, monthly_amount=amount))

    db.commit()


def cleanup_old_demo_users(db: Session):
    """Delete demo accounts (and their data) older than the retention window."""
    cutoff = datetime.utcnow() - timedelta(hours=DEMO_RETENTION_HOURS)
    old_ids = [
        row[0]
        for row in db.query(User.id).filter(User.is_demo.is_(True), User.created_at < cutoff).all()
    ]
    if not old_ids:
        return 0
    db.query(Transaction).filter(Transaction.user_id.in_(old_ids)).delete(synchronize_session=False)
    db.query(Budget).filter(Budget.user_id.in_(old_ids)).delete(synchronize_session=False)
    db.query(ChatMessage).filter(ChatMessage.user_id.in_(old_ids)).delete(synchronize_session=False)
    db.query(User).filter(User.id.in_(old_ids)).delete(synchronize_session=False)
    db.commit()
    return len(old_ids)


def create_demo_user(db: Session) -> User:
    """Create a fresh seeded demo user. The password is random and never shown - demo sessions are token-only."""
    cleanup_old_demo_users(db)

    user = User(
        email=f"demo-{secrets.token_hex(6)}@demo.local",
        password_hash=hash_password(secrets.token_urlsafe(24)),
        is_demo=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    seed_demo_data(db, user.id)
    return user
