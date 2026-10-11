# Plaid Finance Agent

![CI](https://github.com/YOUR_USERNAME/plaid-finance-agent/actions/workflows/ci.yml/badge.svg)

A multi-user web app where an LLM agent answers questions about your real
spending. It links to a bank account through Plaid, syncs actual transactions,
and lets you ask things like *"how much did I spend on food last month?"* or
*"anything unusual in my spending?"*. The agent answers by calling tools that
query your data, so figures come from the database rather than from the model's
imagination.

## Try it

**Live demo:** _add your Render URL here_ - click **Try the demo** for a pre-loaded
account (no sign-up, no bank connection). Chat is rate-limited and capped per day
to keep the public deployment's API costs bounded; see [DEPLOY.md](DEPLOY.md).

## Why it's built this way

- **Tool-calling instead of stuffing transactions into the prompt.** The model
  picks a tool (`categorize_spending`, `detect_anomalies`, ...) and the backend
  runs it against the user's data. That scales past what fits in a context
  window, costs less per question, and keeps numbers verifiable.
- **Dashboard alerts are deterministic, not LLM-generated.** Budget overruns and
  unusual transactions use plain code (threshold and z-score checks): cheap,
  instant, testable, and they can't hallucinate.
- **The model never controls whose data it touches.** `user_id` is injected by the
  backend into every tool call and isn't part of the schema the model sees. If a
  model tried to pass one anyway, the call fails instead of leaking data (this
  is covered by a test).

## Architecture

```
React (Vite)  ──▶  FastAPI  ──▶  Plaid (Sandbox)
                     │
                     ├──▶  SQLite locally / Postgres in production (users, items, transactions, budgets, chat)
                     └──▶  Claude API (tool-calling agent)
```

## Features

- Email/password accounts with JWT sessions; every table is scoped to a user
- Bank linking via Plaid Link (Sandbox) with **incremental sync**: a saved cursor
  means each sync fetches only what changed, including modified and removed
  transactions
- Chat agent with persistent, per-user conversation history and 7 tools:
  `get_transactions`, `categorize_spending`, `detect_anomalies`,
  `calculate_budget_status`, `get_budgets`, `forecast_next_month`, `compare_periods`
- Budgets with progress bars, plus proactive alerts for overspending and
  unusual transactions
- Spending charts: this month by category, and a monthly trend

## Security notes

- Passwords are hashed with bcrypt; login returns the same error for a wrong
  password and an unknown email
- Plaid access tokens are **encrypted at rest** (Fernet). This protects the
  database file, not a fully compromised server; production would use a managed
  KMS with key rotation
- The server refuses to start if `JWT_SECRET` or `ENCRYPTION_KEY` is missing

## Quick start

Two terminals: backend on port 8000, frontend on port 5173.

**Backend**
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # then fill it in (see below)
uvicorn main:app --reload --port 8000
```

In `.env` you need your Plaid Sandbox keys and an Anthropic API key, plus two
secrets you generate yourself:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"                                    # JWT_SECRET
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"   # ENCRYPTION_KEY
```

**Frontend**
```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173, create an account, and link a Sandbox bank using
`user_good` / `pass_good`.

Backend details: [`backend/README.md`](backend/README.md) ·
frontend details: [`frontend/README.md`](frontend/README.md)

## Tests

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

The suite covers the tool functions, auth and cross-user data isolation (every
protected endpoint rejects anonymous requests; one user can't read or change
another's data), incremental sync (cursor, pagination, modified/removed,
resuming after a failure), token encryption, the schema migration, and the agent
loop, using a scripted fake Anthropic client so no API calls or cost are
involved. CI runs the backend tests and a frontend build on every push.

## Known limitations

- Sandbox data only; Production would need Plaid approval
- No password reset, email verification, or token revocation
- No rate limiting on `/chat` or `/auth/login`
- CORS is restricted to `CORS_ORIGINS`; the JWT lives in `localStorage` (simple, but
  exposed to XSS - httpOnly cookies would be the hardening step)
- SQLite (local) or Postgres (production) with a small hand-rolled add-column migration; a larger deployment should
  use Alembic
- Spending totals count every positive transaction, including transfers and loan
  payments, which can inflate "spending"
- `forecast_next_month` is a naive average, not a time-series model
- The agent's answers are not yet evaluated systematically (see roadmap)

## Roadmap

- [ ] Deploy with a seeded demo account
- [ ] Agent evals: a fixed question set scored on tool selection and answer correctness
- [ ] Rate limiting and per-user daily message caps
- [ ] Streaming responses
- [ ] Chat actions that change state (e.g. "set my dining budget to $200"), with confirmation
- [ ] Exclude transfers from spending totals
