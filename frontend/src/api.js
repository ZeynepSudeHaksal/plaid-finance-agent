const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

async function request(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${path} failed (${res.status}): ${text}`);
  }
  return res.json();
}

export const api = {
  getLinkToken: () => request("/link/token", { method: "POST" }),

  exchangeToken: (public_token, institution_name) =>
    request("/link/exchange", {
      method: "POST",
      body: JSON.stringify({ public_token, institution_name }),
    }),

  syncTransactions: () => request("/transactions/sync", { method: "POST" }),

  getTransactions: (limit = 50) => request(`/transactions?limit=${limit}`),

  // Not built yet on the backend — wired up here so the UI is ready
  // once the agent chat endpoint exists.
  sendChatMessage: (message) =>
    request("/chat", {
      method: "POST",
      body: JSON.stringify({ message }),
    }),
};
