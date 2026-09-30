"""
Database models for the finance agent.

We store Plaid data locally so the agent's tools query a fast local
SQLite store instead of hitting the Plaid API on every chat message.
"""
import os
from datetime import datetime

from sqlalchemy import create_engine, Column, String, Float, DateTime, Boolean, Integer, Text, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./finance_agent.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    """A registered account. Every other table is scoped to a user_id."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class PlaidItem(Base):
    """A linked 'bank connection'. In Sandbox this is a fake institution."""

    __tablename__ = "plaid_items"

    item_id = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    access_token = Column(String, nullable=False)
    institution_name = Column(String, nullable=True)
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


def init_db():
    """Create tables if they don't exist. Call this once on startup."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency: yields a DB session, closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()