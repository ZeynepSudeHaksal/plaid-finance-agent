# Finance Agent — Backend (Plaid integration)

This is step 1: get real (Sandbox) transaction data flowing into a local
database. The agent/chat layer comes next, once this works.

## 1. Get Plaid Sandbox keys

1. Sign up free at https://dashboard.plaid.com
2. Team Settings → Keys → copy your **Sandbox** `client_id` and `secret`
3. Copy `.env.example` to `.env` and fill them in:

```bash
cp .env.example .env
# then edit .env with your real values
```

## 2. Install & run

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Check it's alive: http://localhost:8000/health

## 3. Link a (fake) bank account

Plaid Link needs a tiny frontend to open — for now, test it with Plaid's
hosted quickstart or a minimal HTML page (I'll build the real React
frontend next). The flow is:

1. `POST /link/token` → returns a `link_token`
2. Open Plaid Link in the browser with that token (this is the widget
   where the user picks a bank)
3. In Sandbox, pick any institution (e.g. "Chase") and log in with:
   - username: `user_good`
   - password: `pass_good`
4. Link returns a `public_token` to your frontend
5. `POST /link/exchange` with that `public_token` → we save the real
   `access_token` server-side
6. `POST /transactions/sync` → pulls transactions into the local DB
7. `GET /transactions` → confirms data is there

## What's real here

- Every API call goes to Plaid's actual servers (Sandbox environment)
- Transaction data is Plaid's realistic simulated data — merchant names,
  categories, amounts — not data we made up
- The integration code (link token → public token → access token →
  sync) is identical to what you'd ship against Plaid Production

## Next steps

- [ ] Minimal frontend: "Connect a bank" button using `react-plaid-link`
- [ ] Agent tool functions that query the `transactions` table
- [ ] LLM tool-calling loop (Claude API) wired to those tools
- [ ] Chat UI