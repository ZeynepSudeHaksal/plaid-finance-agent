"""
Database models for the finance agent.

We store Plaid data locally so the agent's tools query a fast local
SQLite store instead of hitting the Plaid API on every chat message.
"""
import os
from datetime import datetime

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text, Column, String, Float, DateTime, Boolean, Integer, Text, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker

# Load .env here, not just in main.py: DATABASE_URL is read at import time,
# and main.py imports this module before it calls load_dotenv().
# (load_dotenv never overrides variables that are already set, so tests
# can point DATABASE_URL somewhere else first.)
load_dotenv()

def normalize_database_url(url: str) -> str:
    """Hosts hand out 'postgres://...' or 'postgresql://...'; SQLAlchemy needs a driver name."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


DATABASE_URL = normalize_database_url(os.getenv("DATABASE_URL", "sqlite:///./finance_agent.db"))
IS_SQLITE = DATABASE_URL.startswith("sqlite")

if IS_SQLITE:
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    # pool_pre_ping: serverless Postgres (Neon) closes idle connections when it
    # scales to zero; this transparently replaces a dead pooled connection.
    engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=300)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    """A registered account. Every other table is scoped to a user_id."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    # Ephemeral public-demo account (seeded data, no Plaid, tighter limits).
    is_demo = Column(Boolean, default=False, nullable=False)


class PlaidItem(Base):
    """A linked 'bank connection'. In Sandbox this is a fake institution."""

    __tablename__ = "plaid_items"

    item_id = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    access_token = Column(String, nullable=False)  # stored encrypted - see crypto.py
    institution_name = Column(String, nullable=True)
    # Plaid /transactions/sync cursor: where the last successful sync left
    # off, so the next sync only fetches what changed.
    sync_cursor = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Transaction(Base):
    """A single transaction pulled from Plaid and cached locally."""

    __tablename__ = "transactions"

    transaction_id = Column(String, primary_key=True)
    item_id = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # denormalized from PlaidItem, for easy filtering
    account_id = Column(String, nullable=False)
    date = Column(String, nullable=False)  # ISO format YYYY-MM-DD
    name = Column(String, nullable=False)  # merchant / description
    amount = Column(Float, nullable=False)  # positive = money out, per Plaid convention
    category = Column(String, nullable=True)  # Plaid's top-level category
    pending = Column(Boolean, default=False)


class ChatMessage(Base):
    """One turn of the agent conversation, persisted so history survives restarts."""

    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(String, nullable=False)  # "user" | "assistant"
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Budget(Base):
    """A user-set monthly budget for a spending category. One row per (user, category)."""

    __tablename__ = "budgets"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    category = Column(String, primary_key=True)
    monthly_amount = Column(Float, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ChatUsage(Base):
    """Chat messages sent per user per UTC day. Drives the daily spend caps.

    No foreign key on purpose: demo users get deleted by cleanup, but their
    counts must still add up toward the global daily cap.
    """

    __tablename__ = "chat_usage"

    user_id = Column(Integer, primary_key=True)
    day = Column(String, primary_key=True)  # YYYY-MM-DD (UTC)
    count = Column(Integer, nullable=False, default=0)


# Columns added after a table first shipped. create_all() only creates
# missing TABLES, never missing columns, so without this an existing
# database would need to be deleted whenever the schema grows. This is a
# deliberately tiny stand-in for a real migration tool (Alembic).
_ADDED_COLUMNS = [
    ("plaid_items", "sync_cursor", "VARCHAR"),
    ("users", "is_demo", "BOOLEAN NOT NULL DEFAULT FALSE"),
]


def _ensure_columns():
    inspector = inspect(engine)
    for table, column, ddl_type in _ADDED_COLUMNS:
        existing = {c["name"] for c in inspector.get_columns(table)}
        if column not in existing:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))


def init_db():
    """Create tables if they don't exist, and add any newer columns. Call once on startup."""
    Base.metadata.create_all(bind=engine)
    _ensure_columns()


def get_db():
    """FastAPI dependency: yields a DB session, closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
