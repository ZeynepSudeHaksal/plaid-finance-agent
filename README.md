# Plaid Finance Agent

An AI agent that answers questions about your real spending data. It connects
to a bank account via Plaid, pulls actual transactions, and uses an LLM with
tool-calling to analyze them — categorizing spending, flagging unusual
transactions, forecasting next month, and comparing time periods — all
grounded in real numbers, not guesses.

## Why this exists

Most "finance chatbot" demos either use fake canned data or just wrap an LLM
with no real data access. This project does neither: it's a genuine Plaid
integration (Sandbox environment, but the same API calls as production) feeding
a tool-calling agent that has to actually query the data to answer anything.

## Architecture

```
┌─────────────┐      ┌──────────────┐      ┌─────────────┐
│   React UI   │ ───▶ │   FastAPI     │ ───▶ │    Plaid     │
│  (frontend)  │ ◀─── │   backend     │ ◀─── │  Sandbox API │
└─────────────┘      └──────┬───────┘      └─────────────┘
                             │
                      ┌──────▼───────┐
                      │   SQLite      │
                      │ (transactions)│
                      └──────┬───────┘
                             │
                      ┌──────▼───────┐
                      │  Claude API   │
                      │ (tool-calling │
                      │    agent)     │
                      └──────────────┘
```

**Flow:** User connects a bank via Plaid Link → transactions sync into a
local SQLite store → user asks a question in the chat UI → Claude decides
which tool(s) to call (e.g. `categorize_spending`, `detect_anomalies`) →
tools query SQLite → Claude synthesizes a natural-language answer from the
real results.

## Tech stack

- **Backend:** FastAPI, SQLAlchemy + SQLite, Plaid Python SDK, Anthropic SDK
- **Frontend:** React + Vite, `react-plaid-link`
- **Agent:** Claude (Sonnet), using native tool-use / function calling

## Features

- Real bank account linking via Plaid Link (Sandbox)
- Local transaction sync and storage
- Chat-based agent with 6 tools:
  - `get_transactions` — raw filtered transaction lookup
  - `categorize_spending` — totals by category
  - `detect_anomalies` — flags unusually large transactions (z-score based)
  - `calculate_budget_status` — spend vs. a stated budget
  - `forecast_next_month` — naive baseline projection from monthly history
  - `compare_periods` — spend comparison across two date ranges
- React chat UI + a transaction table view

## Quick start

You need two terminals running at once — backend on port 8000, frontend on
port 5173.

**Backend:**
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in your Plaid + Anthropic keys
uvicorn main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

Then open `http://localhost:5173`, connect a (fake) bank using Plaid
Sandbox's test login (`user_good` / `pass_good`), and start asking questions.

Full setup details, including how to get Plaid and Anthropic API keys, are
in [`backend/README.md`](backend/README.md) and
[`frontend/README.md`](frontend/README.md).

## Known limitations

- No conversation memory — each chat message is handled independently, with
  no context from previous turns
- No auth / multi-user support — single demo user, no session persistence
  across page refreshes
- `forecast_next_month` uses a naive historical average, not a real time
  series model
- Sandbox data only — swapping to Plaid Production would need minimal code
  changes but real bank approval

## Roadmap / possible next steps

- [ ] Multi-turn conversation memory in the chat endpoint
- [ ] Spending charts on the dashboard (category breakdown, trend line)
- [ ] Budget-setting UI (currently only queryable via chat)
- [ ] Proactive alerts (e.g. "you're on track to overspend on dining")
