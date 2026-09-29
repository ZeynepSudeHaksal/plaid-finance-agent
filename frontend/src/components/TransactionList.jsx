import { useEffect, useState } from "react";
import { api } from "../api";

// A small, deliberately muted palette assigned to category names as they
// appear — not a generic badge system, just a way to let the eye group
// rows by category at a glance, ledger-tally-mark style.
const CATEGORY_COLORS = [
  "#0f5257", "#7a3030", "#8a6d1f", "#3b5b8c", "#2c6e49", "#6b4e8c",
];
const colorFor = (() => {
  const assigned = new Map();
  return (category) => {
    const key = category || "Uncategorized";
    if (!assigned.has(key)) {
      assigned.set(key, CATEGORY_COLORS[assigned.size % CATEGORY_COLORS.length]);
    }
    return assigned.get(key);
  };
})();

function formatDate(isoDate) {
  const d = new Date(isoDate + "T00:00:00");
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export default function TransactionList() {
  const [transactions, setTransactions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    api
      .getTransactions(20)
      .then(setTransactions)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="hint">Loading transactions…</p>;
  if (error) return <p className="error">Error: {error}</p>;
  if (transactions.length === 0) {
    return (
      <section className="transaction-list">
        <h3>Recent activity</h3>
        <p className="hint">No transactions synced yet.</p>
      </section>
    );
  }

  const total = transactions.filter((t) => t.amount > 0).reduce((sum, t) => sum + t.amount, 0);

  return (
    <section className="transaction-list">
      <h3>Recent activity</h3>
      <div className="ledger-total">
        ${total.toFixed(2)}
        <span style={{ fontFamily: "var(--font-body)", fontSize: 13, color: "var(--ink-faint)", marginLeft: 8 }}>
          across last {transactions.length} transactions
        </span>
      </div>

      <div className="ledger">
        {transactions.map((t) => (
          <div className="ledger-row" key={`${t.date}-${t.name}-${t.amount}`}>
            <span className="bar" style={{ background: colorFor(t.category) }} />
            <span className="date">{formatDate(t.date)}</span>
            <span className="merchant">
              {t.name}
              <span className="category">{t.category ?? "Uncategorized"}</span>
            </span>
            <span className={`amount ${t.amount > 0 ? "out" : "in"}`}>
              {t.amount > 0 ? "−" : "+"}${Math.abs(t.amount).toFixed(2)}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}