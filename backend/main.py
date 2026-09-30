"""
FastAPI backend for the finance agent.

Auth: /auth/signup and /auth/login return a JWT. Every other data
endpoint requires it (Authorization: Bearer <token>) via the
get_current_user dependency, and scopes its queries to that user's id -
so each account only ever sees its own linked bank, transactions,
budgets, and chat history.

Plaid flow (per user, once authenticated):
  1. Frontend calls POST /link/token          -> gets a link_token
  2. Frontend opens Plaid Link with it, user picks a (sandbox) bank
  3. Plaid Link returns a public_token to the frontend
  4. Frontend calls POST /link/exchange        -> we store the access_token
  5. Frontend calls POST /transactions/sync    -> we pull + cache transactions
"""
import os
from collections import defaultdict
from datetime import datetime, date
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from models import init_db, get_db, User, PlaidItem, Transaction, ChatMessage, Budget
import plaid_client
import agent
from agent_tools import categorize_spending, calculate_budget_status, detect_anomalies
from auth import hash_password, verify_password, create_token, get_current_user

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


MAX_HISTORY_TURNS = 12  # keep chat context from growing unbounded over a long session


def _load_history(db: Session, user_id: int) -> list:
    """Load recent chat history for this user as plain {role, content} dicts."""
    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.user_id == user_id)
        .order_by(ChatMessage.id.desc())
        .limit(MAX_HISTORY_TURNS * 2)
        .all()
    )
    rows.reverse()
    return [{"role": r.role, "content": r.content} for r in rows]


def _save_turn(db: Session, user_id: int, user_message: str, reply: str):
    db.add(ChatMessage(user_id=user_id, role="user", content=user_message))
    db.add(ChatMessage(user_id=user_id, role="assistant", content=reply))
    db.commit()


# --- Request/response models ------------------------------------------------

class SignupRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ExchangeRequest(BaseModel):
    public_token: str
    institution_name: Optional[str] = None


class ChatRequest(BaseModel):
    message: str


class BudgetRequest(BaseModel):
    category: str
    monthly_amount: float


# --- Health (public) ---------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


# --- Auth (public) ------------------------------------------------------------

@app.post("/auth/signup")
def signup(req: SignupRequest, db: Session = Depends(get_db)):
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    existing = db.query(User).filter(User.email == req.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="An account with this email already exists")

    user = User(email=req.email, password_hash=hash_password(req.password))
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_token(user.id)
    return {"access_token": token, "email": user.email}


@app.post("/auth/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == req.email).first()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    token = create_token(user.id)
    return {"access_token": token, "email": user.email}


# --- Plaid linking (authenticated) --------------------------------------------

@app.get("/link/status")
def link_status(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Lets the frontend know on load whether this user already has a linked bank."""
    exists = db.query(PlaidItem).filter(PlaidItem.user_id == current_user.id).first() is not None
    return {"linked": exists}


@app.post("/link/token")
def get_link_token(current_user: User = Depends(get_current_user)):
    try:
        link_token = plaid_client.create_link_token(str(current_user.id))
        return {"link_token": link_token}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/link/exchange")
def exchange_token(req: ExchangeRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        result = plaid_client.exchange_public_token(req.public_token)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    item = PlaidItem(
        item_id=result["item_id"],
        user_id=current_user.id,
        access_token=result["access_token"],
        institution_name=req.institution_name,
    )
    db.merge(item)
    db.commit()

    return {"item_id": result["item_id"], "status": "linked"}


@app.post("/transactions/sync")
def sync_all_transactions(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Pull the latest transactions for this user's linked items only."""
    items = db.query(PlaidItem).filter(PlaidItem.user_id == current_user.id).all()
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
                        user_id=current_user.id,
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
def list_transactions(current_user: User = Depends(get_current_user), db: Session = Depends(get_db), limit: int = 50):
    txns = (
        db.query(Transaction)
        .filter(Transaction.user_id == current_user.id)
        .order_by(Transaction.date.desc())
        .limit(limit)
        .all()
    )
    return [
        {"date": t.date, "name": t.name, "amount": t.amount, "category": t.category, "pending": t.pending}
        for t in txns
    ]


@app.get("/categories")
def list_categories(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Distinct categories actually present in this user's transactions, for the budget dropdown."""
    rows = db.query(Transaction.category).filter(Transaction.user_id == current_user.id).distinct().all()
    categories = sorted({r[0] for r in rows if r[0]})
    return {"categories": categories}


# --- Chat agent (authenticated) -----------------------------------------------

@app.post("/chat")
def chat(req: ChatRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="message cannot be empty")

    history = _load_history(db, current_user.id)

    try:
        reply, _ = agent.run_agent(db, req.message, current_user.id, history)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent error: {e}")

    _save_turn(db, current_user.id, req.message, reply)
    return {"reply": reply}


@app.post("/chat/reset")
def reset_chat(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(ChatMessage).filter(ChatMessage.user_id == current_user.id).delete()
    db.commit()
    return {"status": "reset"}


# --- Budgets (authenticated) ---------------------------------------------------

@app.get("/budgets")
def list_budgets(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    budgets = db.query(Budget).filter(Budget.user_id == current_user.id).all()
    return [{"category": b.category, "monthly_amount": b.monthly_amount} for b in budgets]


@app.post("/budgets")
def set_budget(req: BudgetRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    budget = Budget(user_id=current_user.id, category=req.category, monthly_amount=req.monthly_amount)
    db.merge(budget)
    db.commit()
    return {"category": req.category, "monthly_amount": req.monthly_amount}


@app.delete("/budgets/{category}")
def delete_budget(category: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    existing = db.query(Budget).filter(Budget.user_id == current_user.id, Budget.category == category).first()
    if not existing:
        raise HTTPException(status_code=404, detail=f"No budget set for '{category}'")
    db.delete(existing)
    db.commit()
    return {"status": "deleted", "category": category}


# --- Spending summaries / charts (authenticated) --------------------------------

@app.get("/spending/timeseries")
def spending_timeseries(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    txns = db.query(Transaction).filter(Transaction.user_id == current_user.id, Transaction.amount > 0).all()
    monthly = defaultdict(float)
    for t in txns:
        monthly[t.date[:7]] += t.amount

    points = [{"period": m, "total": round(total, 2)} for m, total in sorted(monthly.items())]
    return {"points": points}


@app.get("/spending/by-category")
def spending_by_category(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
):
    return categorize_spending(db=db, user_id=current_user.id, start_date=start_date, end_date=end_date)


# --- Alerts (authenticated) -----------------------------------------------------

@app.get("/alerts")
def get_alerts(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    now = date.today()
    month_start = now.replace(day=1).isoformat()
    month_end = now.isoformat()

    alerts = []

    budgets = db.query(Budget).filter(Budget.user_id == current_user.id).all()
    for b in budgets:
        status = calculate_budget_status(
            db=db, user_id=current_user.id, category=b.category, budget_amount=b.monthly_amount,
            start_date=month_start, end_date=month_end,
        )
        if status.get("over_budget"):
            alerts.append({
                "id": f"budget-over-{b.category}",
                "severity": "over",
                "message": f"Over budget on {b.category.replace('_', ' ').title()}: "
                           f"${status['spent']:.2f} spent of ${status['budget']:.2f}.",
            })
        elif status.get("percent_used", 0) >= 90:
            alerts.append({
                "id": f"budget-near-{b.category}",
                "severity": "near",
                "message": f"Nearing budget on {b.category.replace('_', ' ').title()}: "
                           f"{status['percent_used']:.0f}% used.",
            })

    anomaly_result = detect_anomalies(db=db, user_id=current_user.id)
    for a in anomaly_result.get("anomalies", [])[:3]:
        alerts.append({
            "id": f"anomaly-{a['date']}-{a['name']}",
            "severity": "info",
            "message": f"Unusual transaction: {a['name']} for ${a['amount']:.2f} "
                       f"(typical in {a['category'].replace('_', ' ').title()} is ~${a['typical_amount_in_category']:.2f}).",
        })

    severity_rank = {"over": 0, "near": 1, "info": 2}
    alerts.sort(key=lambda a: severity_rank.get(a["severity"], 9))

    return {"alerts": alerts}