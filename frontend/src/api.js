const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

const TOKEN_KEY = "finance_agent_token";
let authToken = localStorage.getItem(TOKEN_KEY) || null;
let onUnauthorized = null; // set by App.jsx so a 401 can drop the user back to the login screen

export function setAuthToken(token) {
  authToken = token;
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export function getAuthToken() {
  return authToken;
}

export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn;
}

async function request(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (authToken) headers["Authorization"] = `Bearer ${authToken}`;

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (res.status === 401) {
    setAuthToken(null);
    if (onUnauthorized) onUnauthorized();
    throw new Error("Session expired — please sign in again.");
  }

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${path} failed (${res.status}): ${text}`);
  }
  return res.json();
}

export const api = {
  signup: (email, password) =>
    request("/auth/signup", { method: "POST", body: JSON.stringify({ email, password }) }),

  login: (email, password) =>
    request("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),

  getLinkStatus: () => request("/link/status"),

  getLinkToken: () => request("/link/token", { method: "POST" }),

  exchangeToken: (public_token, institution_name) =>
    request("/link/exchange", {
      method: "POST",
      body: JSON.stringify({ public_token, institution_name }),
    }),

  syncTransactions: () => request("/transactions/sync", { method: "POST" }),

  getTransactions: (limit = 50) => request(`/transactions?limit=${limit}`),

  sendChatMessage: (message) =>
    request("/chat", {
      method: "POST",
      body: JSON.stringify({ message }),
    }),

  resetChat: () => request("/chat/reset", { method: "POST" }),

  getCategories: () => request("/categories"),

  getAlerts: () => request("/alerts"),

  getBudgets: () => request("/budgets"),

  spendingByCategory: (startDate, endDate) =>
    request(`/spending/by-category?start_date=${startDate}&end_date=${endDate}`),

  spendingTimeseries: () => request("/spending/timeseries"),

  setBudget: (category, monthly_amount) =>
    request("/budgets", {
      method: "POST",
      body: JSON.stringify({ category, monthly_amount }),
    }),

  deleteBudget: (category) =>
    request(`/budgets/${encodeURIComponent(category)}`, { method: "DELETE" }),
};