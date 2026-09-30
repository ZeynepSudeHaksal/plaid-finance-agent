"""
FastAPI backend for the finance agent - Plaid integration layer.

Flow:
  1. Frontend calls POST /link/token          -> gets a link_token
  2. Frontend opens Plaid Link with it, user picks a (sandbox) bank
  3. Plaid Link returns a public_token to the frontend
  4. Frontend calls POST /link/exchange        -> we store the access_token
  5. Frontend calls POST /transactions/sync    -> we pull + cache transactions

Agent chat endpoints come in a later step, once real data is flowing.
"""
import os
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from models import init_db, get_db, PlaidItem, Transaction, ChatMessage, Budget
import plaid_client
import agent
from agent_tools import categorize_spending

load_dotenv()

app = FastAPI(title="Finance Agent API")

app.add_middleware(
    CORSMiddleware,
    # Wide open for local development only — tighten this before any real deployment.
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()


# A single hardcoded demo user for now - fine for a portfolio project.
DEMO_USER_ID = "demo-user"

# Conversation history lives in the chat_messages table now - persists
# across server restarts. Still a single global conversation (no
# auth/sessions yet); a real multi-user app would key this by user id.
MAX_HISTORY_TURNS = 12  # keep context from growing unbounded over a long session


def _load_history(db: Session) -> list:
    """Load recent chat history from the DB as plain {role, content} dicts."""
    rows = (
        db.query(ChatMessage)
        .order_by(ChatMessage.id.desc())
        .limit(MAX_HISTORY_TURNS * 2)
        .all()
    )
    rows.reverse()  # back to chronological order
    return [{"role": r.role, "content": r.content} for r in rows]


def _save_turn(db: Session, user_message: str, reply: str):
    """Persist one user/assistant turn to the DB."""
    db.add(ChatMessage(role="user", content=user_message))
    db.add(ChatMessage(role="assistant", content=reply))
    db.commit()


class ExchangeRequest(BaseModel):
    public_token: str
    institution_name: Optional[str] = None


class ChatRequest(BaseModel):
    message: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/link/token")
def get_link_token():
    """Frontend calls this to get a token that opens Plaid Link."""
    try:
        link_token = plaid_client.create_link_token(DEMO_USER_ID)
        return {"link_token": link_token}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/link/exchange")
def exchange_token(req: ExchangeRequest, db: Session = Depends(get_db)):
    """
    Frontend calls this once the user finishes linking a bank in Plaid
    Link. We exchange the public_token for a permanent access_token and
    save it so we can pull transactions later.
    """
    try:
        result = plaid_client.exchange_public_token(req.public_token)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    item = PlaidItem(
        item_id=result["item_id"],
        access_token=result["access_token"],
        institution_name=req.institution_name,
    )
    db.merge(item)  # merge = insert or update
    db.commit()

    return {"item_id": result["item_id"], "status": "linked"}


@app.post("/transactions/sync")
def sync_all_transactions(db: Session = Depends(get_db)):
    """
    Pull the latest transactions for every linked item and upsert them
    into the local store. Call this after linking, and periodically to
    refresh.
    """
    items = db.query(PlaidItem).all()
    if not items:
        raise HTTPException(status_code=400, detail="No linked accounts yet. Call /link/token and /link/exchange first.")

    total_added = 0
    for item in items:
        cursor = None
        has_more = True
        while has_more:
            result = plaid_client.sync_transactions(item.access_token, cursor)

            for txn in result["added"]:
                db.merge(
                    Transaction(
                        transaction_id=txn.transaction_id,
                        item_id=item.item_id,
                        account_id=txn.account_id,
                        date=str(txn.date),
                        name=txn.name,
                        amount=txn.amount,
                        category=txn.personal_finance_category.primary if txn.personal_finance_category else None,
                        pending=txn.pending,
                    )
                )
                total_added += 1

            for txn in result["removed"]:
                existing = db.query(Transaction).filter_by(transaction_id=txn.transaction_id).first()
                if existing:
                    db.delete(existing)

            cursor = result["next_cursor"]
            has_more = result["has_more"]

        db.commit()

    return {"synced_items": len(items), "transactions_added": total_added}


@app.get("/transactions")
def list_transactions(db: Session = Depends(get_db), limit: int = 50):
    """Quick endpoint to sanity-check what's in the local store."""
    txns = db.query(Transaction).order_by(Transaction.date.desc()).limit(limit).all()
    return [
        {
            "date": t.date,
            "name": t.name,
            "amount": t.amount,
            "category": t.category,
            "pending": t.pending,
        }
        for t in txns
    ]


@app.post("/chat")
def chat(req: ChatRequest, db: Session = Depends(get_db)):
    """
    The agent endpoint. Runs the user's message through Claude with
    tool-calling access to the local transaction data, using persisted
    conversation history so follow-up questions work across requests
    (and survive a server restart).
    """
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message cannot be empty")

    history = _load_history(db)

    try:
        reply, _ = agent.run_agent(db, req.message, history)
    except RuntimeError as e:
        # e.g. missing ANTHROPIC_API_KEY
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent error: {e}")

    _save_turn(db, req.message, reply)
    return {"reply": reply}


@app.post("/chat/reset")
def reset_chat(db: Session = Depends(get_db)):
    """Clear all conversation history - used by the UI's 'New conversation' button."""
    db.query(ChatMessage).delete()
    db.commit()
    return {"status": "reset"}


class BudgetRequest(BaseModel):
    category: str
    monthly_amount: float


@app.get("/budgets")
def list_budgets(db: Session = Depends(get_db)):
    """List all stored budgets."""
    budgets = db.query(Budget).all()
    return [{"category": b.category, "monthly_amount": b.monthly_amount} for b in budgets]


@app.post("/budgets")
def set_budget(req: BudgetRequest, db: Session = Depends(get_db)):
    """Create or update the budget for a category (upsert by category)."""
    budget = Budget(category=req.category, monthly_amount=req.monthly_amount)
    db.merge(budget)
    db.commit()
    return {"category": req.category, "monthly_amount": req.monthly_amount}


@app.get("/categories")
def list_categories(db: Session = Depends(get_db)):
    """
    Distinct categories actually present in the synced transactions, so
    the frontend can offer a dropdown instead of free text - Plaid's raw
    category strings (e.g. FOOD_AND_DRINK) don't match what the agent
    displays in friendly prose, so free-text budget entry was error-prone.
    """
    rows = db.query(Transaction.category).distinct().all()
    categories = sorted({r[0] for r in rows if r[0]})
    return {"categories": categories}


@app.get("/spending/by-category")
def spending_by_category(db: Session = Depends(get_db), start_date: Optional[str] = None, end_date: Optional[str] = None):
    """
    Plain (non-agent) spending totals by category, for the budget UI's
    progress bars. Reuses the same tool function the chat agent calls -
    no LLM round trip needed for a straightforward data fetch like this.
    """
    return categorize_spending(db=db, start_date=start_date, end_date=end_date)


@app.delete("/budgets/{category}")
def delete_budget(category: str, db: Session = Depends(get_db)):
    """Remove a category's budget."""
    existing = db.query(Budget).filter(Budget.category == category).first()
    if not existing:
        raise HTTPException(status_code=404, detail=f"No budget set for '{category}'")
    db.delete(existing)
    db.commit()
    return {"status": "deleted", "category": category}