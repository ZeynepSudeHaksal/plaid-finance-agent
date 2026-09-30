# Finance Agent — Frontend

React + Vite app for the finance agent. Talks to the FastAPI backend
in `../backend`.

## Setup

```bash
npm install
npm run dev
```

Opens at http://localhost:5173. Make sure the backend is running at
http://localhost:8000 first (`uvicorn main:app --reload --port 8000`
in the backend folder).

## What's here

- `ConnectBank.jsx` — the Plaid Link flow (uses `react-plaid-link`).
  Replaces the old `link_test.html` throwaway page.
- `TransactionList.jsx` — shows synced transactions from the backend.
- `Chat.jsx` — chat UI for the agent. **Calls `POST /chat`, which
  doesn't exist on the backend yet** — that's the next build step
  (the LLM tool-calling loop). The UI will just show an error until
  then, which is expected.
- `App.jsx` — switches between the "connect a bank" screen and the
  dashboard once linked.

No auth, no persistence of the "linked" state across refreshes yet —
fine for a portfolio demo, worth flagging as a known limitation if
asked about it in an interview.