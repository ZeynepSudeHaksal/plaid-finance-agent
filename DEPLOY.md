# Deploying

Target setup: **Neon** (Postgres, free, doesn't expire) + **Render** (API + static frontend).

## 0. Before you start

- Rotate any API key that ever appeared in a terminal paste, chat, or commit.
- In the Anthropic console, set a **monthly spend limit** (a few dollars). This is the hard ceiling no matter what the app does.
- Generate fresh secrets:
  ```bash
  python3 -c "import secrets; print(secrets.token_hex(32))"                       # JWT_SECRET (Render can generate this)
  python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # ENCRYPTION_KEY
  ```
  Keep `ENCRYPTION_KEY` somewhere safe: losing it makes stored Plaid tokens unreadable.

## 1. Database (Neon)

1. Create a project at neon.tech, copy the connection string (`postgresql://...?sslmode=require`).
2. That string is your `DATABASE_URL`. Tables are created automatically on first start.

## 2. API + frontend (Render)

1. Push the repo to GitHub.
2. Render → New → **Blueprint** → select the repo (uses `render.yaml`).
3. Fill in the prompted env vars on `finance-agent-api`:
   `PLAID_CLIENT_ID`, `PLAID_SECRET`, `ANTHROPIC_API_KEY`, `DATABASE_URL`, `ENCRYPTION_KEY`.
4. Deploy, then note both URLs.
5. Set `CORS_ORIGINS` (API) to the frontend URL, and `VITE_API_BASE` (frontend) to the API URL. Redeploy the frontend (Vite bakes the value in at build time).

## 3. Smoke test

- `https://<api>/health` → `{"status":"ok"}`
- Open the frontend → **Try the demo** → charts load → ask a question in chat.
- Sign up with a real account → connect a Plaid sandbox bank (`user_good` / `pass_good`).

## Cost controls (env vars on the API)

| Variable | Default | Meaning |
|---|---|---|
| `CHAT_DAILY_LIMIT_USER` | 30 | chat messages per registered user per day |
| `CHAT_DAILY_LIMIT_DEMO` | 10 | chat messages per demo account per day |
| `CHAT_DAILY_LIMIT_GLOBAL` | 300 | chat messages across the whole site per day |
| `MAX_MESSAGE_CHARS` | 1000 | longest accepted chat message |
| `AUTH_RATE_PER_MINUTE` | 10 | signup/login attempts per IP per minute |
| `DEMO_RATE_PER_HOUR` | 20 | demo accounts per IP per hour |

Demo accounts and their data are deleted after 24 hours.

## Notes

- Free Render web services sleep after 15 minutes idle (~1 min cold start). The Starter plan stays awake.
- Plaid is Sandbox only - no real bank data is ever involved.
