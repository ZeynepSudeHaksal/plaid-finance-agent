"""
Tool functions the agent can call. Each one queries the local
`transactions` table (populated by Plaid sync) and returns plain
JSON-serializable data - no LLM calls happen in here, this is just
the "hands" the agent uses.

Every function takes `user_id` and filters by it - this is NOT part of
the tool's LLM-facing schema (the model never sees or chooses it); the
agent loop injects it automatically so one user's data is never visible
to another's conversation.

ONE EXCEPTION: get_market_outlook doesn't touch the database at all -
it calls a second, separately-deployed project of mine (a volatility
regime + price direction ML service: github.com/ZeynepSudeHaksal/
spy-volatility-predictor) over HTTP instead. db/user_id are still
accepted, purely so it fits _execute_tool's uniform dispatch signature
(agent.py always calls every tool as fn(db=db, user_id=user_id,
**tool_input)) - it doesn't use either.
"""
import os
from collections import defaultdict
from datetime import datetime
from statistics import mean, stdev

import httpx
from sqlalchemy.orm import Session

from models import Transaction, Budget

MARKET_API_BASE = os.getenv(
    "MARKET_API_BASE", "https://financial-predictor-api.onrender.com/api"
)


def get_transactions(db: Session, user_id: int, start_date: str = None, end_date: str = None, category: str = None) -> dict:
    """Return raw transactions, optionally filtered by date range and/or category."""
    query = db.query(Transaction).filter(Transaction.user_id == user_id)
    if start_date:
        query = query.filter(Transaction.date >= start_date)
    if end_date:
        query = query.filter(Transaction.date <= end_date)
    if category:
        query = query.filter(Transaction.category == category)

    results = query.order_by(Transaction.date.desc()).all()
    return {
        "count": len(results),
        "transactions": [
            {"date": t.date, "name": t.name, "amount": t.amount, "category": t.category}
            for t in results
        ],
    }


def categorize_spending(db: Session, user_id: int, start_date: str = None, end_date: str = None) -> dict:
    """Sum spending by category over an optional date range."""
    query = db.query(Transaction).filter(Transaction.user_id == user_id, Transaction.amount > 0)
    if start_date:
        query = query.filter(Transaction.date >= start_date)
    if end_date:
        query = query.filter(Transaction.date <= end_date)

    totals = defaultdict(float)
    for t in query.all():
        totals[t.category or "Uncategorized"] += t.amount

    return {
        "by_category": {k: round(v, 2) for k, v in sorted(totals.items(), key=lambda x: -x[1])},
        "total": round(sum(totals.values()), 2),
    }


def detect_anomalies(db: Session, user_id: int, std_dev_threshold: float = 2.0) -> dict:
    """
    Flag transactions that are unusually large relative to the typical
    transaction size within their own category (simple z-score outlier
    detection - good enough for a portfolio project, not a fraud engine).
    """
    all_txns = db.query(Transaction).filter(Transaction.user_id == user_id, Transaction.amount > 0).all()

    by_category = defaultdict(list)
    for t in all_txns:
        by_category[t.category or "Uncategorized"].append(t)

    anomalies = []
    for category, txns in by_category.items():
        amounts = [t.amount for t in txns]
        if len(amounts) < 3:
            continue  # not enough data in this category to judge "unusual"
        avg = mean(amounts)
        sd = stdev(amounts)
        if sd == 0:
            continue
        for t in txns:
            z_score = (t.amount - avg) / sd
            if z_score >= std_dev_threshold:
                anomalies.append(
                    {
                        "date": t.date,
                        "name": t.name,
                        "amount": t.amount,
                        "category": category,
                        "typical_amount_in_category": round(avg, 2),
                    }
                )

    anomalies.sort(key=lambda a: a["date"], reverse=True)
    return {"anomalies": anomalies, "count": len(anomalies)}


def calculate_budget_status(db: Session, user_id: int, category: str, budget_amount: float = None, start_date: str = None, end_date: str = None) -> dict:
    """
    Compare actual spending in a category against a budget figure. If
    budget_amount isn't given, looks up a stored budget for that
    category (set via the budget UI or a prior chat message).
    """
    used_stored_budget = False
    if budget_amount is None:
        stored = db.query(Budget).filter(Budget.user_id == user_id, Budget.category == category).first()
        if stored is None:
            return {
                "category": category,
                "error": f"No budget amount given and no stored budget found for '{category}'. "
                "Ask the user for a budget amount, or tell them to set one.",
            }
        budget_amount = stored.monthly_amount
        used_stored_budget = True

    query = db.query(Transaction).filter(
        Transaction.user_id == user_id, Transaction.category == category, Transaction.amount > 0
    )
    if start_date:
        query = query.filter(Transaction.date >= start_date)
    if end_date:
        query = query.filter(Transaction.date <= end_date)

    spent = sum(t.amount for t in query.all())
    remaining = budget_amount - spent

    return {
        "category": category,
        "budget": budget_amount,
        "budget_source": "stored" if used_stored_budget else "given_in_message",
        "spent": round(spent, 2),
        "remaining": round(remaining, 2),
        "percent_used": round((spent / budget_amount) * 100, 1) if budget_amount else None,
        "over_budget": spent > budget_amount,
    }


def get_budgets(db: Session, user_id: int) -> dict:
    """Return all budgets the user currently has set."""
    budgets = db.query(Budget).filter(Budget.user_id == user_id).all()
    return {
        "budgets": [{"category": b.category, "monthly_amount": b.monthly_amount} for b in budgets],
        "count": len(budgets),
    }


def forecast_next_month(db: Session, user_id: int) -> dict:
    """
    Very simple forecast: average total monthly spend over however many
    months of data exist, projected forward one month. Not a real time
    series model - a clearly-labeled naive baseline is honest and is
    enough to demonstrate the concept.
    """
    all_txns = db.query(Transaction).filter(Transaction.user_id == user_id, Transaction.amount > 0).all()
    if not all_txns:
        return {"forecast": None, "note": "No transaction data available."}

    monthly_totals = defaultdict(float)
    for t in all_txns:
        month_key = t.date[:7]  # "YYYY-MM"
        monthly_totals[month_key] += t.amount

    months = sorted(monthly_totals.keys())
    totals = [monthly_totals[m] for m in months]

    forecast = mean(totals)
    return {
        "months_of_data": months,
        "monthly_totals": {m: round(monthly_totals[m], 2) for m in months},
        "forecast_next_month": round(forecast, 2),
        "method": "average of past months (naive baseline)",
    }


def compare_periods(db: Session, user_id: int, period_a_start: str, period_a_end: str, period_b_start: str, period_b_end: str) -> dict:
    """Compare total spending between two date ranges, e.g. this month vs last month."""

    def total_for(start, end):
        txns = (
            db.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.date >= start,
                Transaction.date <= end,
                Transaction.amount > 0,
            )
            .all()
        )
        return sum(t.amount for t in txns)

    total_a = total_for(period_a_start, period_a_end)
    total_b = total_for(period_b_start, period_b_end)
    change = total_a - total_b
    pct_change = (change / total_b * 100) if total_b else None

    return {
        "period_a": {"start": period_a_start, "end": period_a_end, "total": round(total_a, 2)},
        "period_b": {"start": period_b_start, "end": period_b_end, "total": round(total_b, 2)},
        "change": round(change, 2),
        "percent_change": round(pct_change, 1) if pct_change is not None else None,
    }


def get_market_outlook(db: Session, user_id: int, ticker: str = "SPY") -> dict:
    """
    Fetches the current volatility-regime and price-direction outlook for
    a major index/sector ETF from a separately-deployed ML service (see
    module docstring). General market context, not derived from this
    user's own transactions at all.

    Deliberately honest about which half of that is trustworthy: the
    volatility model has a real, walk-forward-validated edge (ROC-AUC
    0.59-0.66 across tickers); the direction model, at this horizon,
    does not (ROC-AUC ~0.51, indistinguishable from random). The "note"
    field says so explicitly, and the system prompt tells the agent to
    pass that caveat on rather than quietly presenting a coin-flip as a
    forecast.
    """
    ticker = ticker.upper()
    try:
        with httpx.Client(timeout=10.0) as client:
            vol = client.get(
                f"{MARKET_API_BASE}/volatility/predict/latest", params={"ticker": ticker}
            ).json()
            direction = client.get(
                f"{MARKET_API_BASE}/direction/predict/latest", params={"ticker": ticker}
            ).json()
    except httpx.HTTPError as e:
        return {"error": f"Market Analytics API unreachable: {e}"}

    # The basket this points at can change independently of this repo (it's
    # a separately-deployed project) -- so this never hardcodes which
    # tickers are supported. An unrecognized ticker comes back from the
    # API with regime/direction/probability all null and a non-null
    # "note" explaining why (see spy-volatility-predictor's app.py).
    # Surface that plainly instead of silently returning an "outlook"
    # that's actually all nulls, which would read to the LLM like "no
    # volatility today" rather than "this ticker isn't tracked."
    if vol.get("regime") is None and vol.get("note"):
        return {"ticker": ticker, "error": vol["note"]}
    if direction.get("direction") is None and direction.get("note"):
        return {"ticker": ticker, "error": direction["note"]}

    return {
        "ticker": ticker,
        "volatility_regime": {
            "expected": vol.get("regime"),
            "probability": vol.get("probability"),
            "as_of": vol.get("date"),
        },
        "price_direction_5d": {
            "expected": direction.get("direction"),
            "probability": direction.get("probability"),
            "always_up_baseline": direction.get("always_up_baseline"),
            "as_of": direction.get("date"),
        },
        "source": "spy-volatility-predictor (separately-deployed XGBoost models, "
        "walk-forward backtested)",
        "note": (
            "Volatility regime has a validated edge over its naive baseline "
            "(ROC-AUC 0.59-0.66, consistent across tickers) and is reasonable to "
            "mention as a risk signal. Price direction at a 5-day horizon does "
            "NOT have a validated edge (ROC-AUC ~0.51, statistically indistinguishable "
            "from random) -- present it only as informational, never as a reason "
            "to change spending or investing behavior."
        ),
    }


# --- Tool schemas for the LLM (Anthropic tool-use format) ---
# These describe only the arguments the MODEL supplies - user_id is
# never part of this schema; the agent loop injects it separately so
# the LLM can't (and doesn't need to) touch it.

TOOL_SCHEMAS = [
    {
        "name": "get_transactions",
        "description": "Get a list of raw transactions, optionally filtered by date range (YYYY-MM-DD) and/or category.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "YYYY-MM-DD, inclusive"},
                "end_date": {"type": "string", "description": "YYYY-MM-DD, inclusive"},
                "category": {"type": "string", "description": "Exact category name to filter by"},
            },
        },
    },
    {
        "name": "categorize_spending",
        "description": "Get total spending broken down by category over an optional date range. Use this for 'how much did I spend on X' questions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "YYYY-MM-DD, inclusive"},
                "end_date": {"type": "string", "description": "YYYY-MM-DD, inclusive"},
            },
        },
    },
    {
        "name": "detect_anomalies",
        "description": "Find transactions that are unusually large compared to typical spending in their category. Use this for 'anything weird/unusual in my spending' questions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "std_dev_threshold": {
                    "type": "number",
                    "description": "How many standard deviations above average counts as 'unusual'. Default 2.0.",
                },
            },
        },
    },
    {
        "name": "calculate_budget_status",
        "description": "Compare actual spending in a category against a budget. If budget_amount is omitted, uses a stored budget for that category if one exists.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string"},
                "budget_amount": {"type": "number", "description": "Omit to use the user's stored budget for this category, if any."},
                "start_date": {"type": "string", "description": "YYYY-MM-DD, inclusive"},
                "end_date": {"type": "string", "description": "YYYY-MM-DD, inclusive"},
            },
            "required": ["category"],
        },
    },
    {
        "name": "get_budgets",
        "description": "List all budgets the user currently has set. Use for 'what budgets do I have' type questions.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "forecast_next_month",
        "description": "Project next month's total spending based on historical monthly averages. Use for 'how much will I spend next month' type questions.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "compare_periods",
        "description": "Compare total spending between two date ranges, e.g. this month vs last month.",
        "input_schema": {
            "type": "object",
            "properties": {
                "period_a_start": {"type": "string"},
                "period_a_end": {"type": "string"},
                "period_b_start": {"type": "string"},
                "period_b_end": {"type": "string"},
            },
            "required": ["period_a_start", "period_a_end", "period_b_start", "period_b_end"],
        },
    },
    {
        "name": "get_market_outlook",
        "description": "Get the current broad-market outlook (volatility regime and short-term "
        "price direction) for a major index/sector ETF, from a separately-deployed ML "
        "forecasting service. NOT derived from the user's own transactions -- use this "
        "when they ask about market conditions, volatility, or whether it's a good/bad "
        "time to spend or invest. The result's 'note' field says which half of this is "
        "statistically validated and which isn't -- always pass that caveat on to the "
        "user rather than presenting the direction figure as reliable advice.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Ticker symbol, e.g. SPY, QQQ, IWM, DIA, XLF, GLD, or TLT. "
                    "Defaults to SPY (broad market) if omitted. This list isn't exhaustive and "
                    "can change, since the market API is a separately-deployed, independently "
                    "evolving project -- if a ticker isn't tracked, the tool result's 'error' "
                    "field will say so plainly; don't refuse to try a ticker just because it's "
                    "not in this example list.",
                },
            },
        },
    },
]

# Maps tool name -> actual Python function, so the agent loop can
# dispatch a tool call by name without a big if/elif chain.
TOOL_FUNCTIONS = {
    "get_transactions": get_transactions,
    "categorize_spending": categorize_spending,
    "detect_anomalies": detect_anomalies,
    "calculate_budget_status": calculate_budget_status,
    "get_budgets": get_budgets,
    "forecast_next_month": forecast_next_month,
    "compare_periods": compare_periods,
    "get_market_outlook": get_market_outlook,
}