import { useEffect, useState } from "react";
import { api } from "../api";
import { formatCategoryLabel } from "../format";

function currentMonthRange() {
  const now = new Date();
  const start = new Date(now.getFullYear(), now.getMonth(), 1);
  const iso = (d) => d.toISOString().slice(0, 10);
  return { start: iso(start), end: iso(now) };
}

export default function BudgetPanel() {
  const [budgets, setBudgets] = useState([]);
  const [spending, setSpending] = useState({});
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [category, setCategory] = useState("");
  const [amount, setAmount] = useState("");
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const { start, end } = currentMonthRange();
      const [budgetList, spendingSummary, categoryList] = await Promise.all([
        api.getBudgets(),
        api.spendingByCategory(start, end),
        api.getCategories(),
      ]);
      setBudgets(budgetList);
      setSpending(spendingSummary.by_category || {});
      setCategories(categoryList.categories || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    const trimmedCategory = category.trim();
    const parsedAmount = parseFloat(amount);
    if (!trimmedCategory || Number.isNaN(parsedAmount) || parsedAmount <= 0) return;

    setSaving(true);
    try {
      await api.setBudget(trimmedCategory, parsedAmount);
      setCategory("");
      setAmount("");
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (cat) => {
    try {
      await api.deleteBudget(cat);
      await load();
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <section className="budget-panel">
      <h3>Budgets this month</h3>

      {loading ? (
        <p className="hint">Loading budgets…</p>
      ) : budgets.length === 0 ? (
        <p className="hint">No budgets set yet — add one below.</p>
      ) : (
        <div className="budget-list">
          {budgets.map((b) => {
            const spent = spending[b.category] || 0;
            const pct = Math.min(100, Math.round((spent / b.monthly_amount) * 100));
            const over = spent > b.monthly_amount;
            return (
              <div className="budget-row" key={b.category}>
                <div className="budget-row-top">
                  <span className="budget-category">{formatCategoryLabel(b.category)}</span>
                  <span className={`budget-figures ${over ? "over" : ""}`}>
                    ${spent.toFixed(2)} <span className="of">of</span> ${b.monthly_amount.toFixed(2)}
                  </span>
                  <button className="ghost-button" onClick={() => handleDelete(b.category)}>
                    remove
                  </button>
                </div>
                <div className="budget-bar">
                  <div
                    className={`budget-bar-fill ${over ? "over" : ""}`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}

      {error && <p className="error">Error: {error}</p>}

      <form className="budget-form" onSubmit={handleSubmit}>
        <select value={category} onChange={(e) => setCategory(e.target.value)} disabled={saving}>
          <option value="">Choose a category…</option>
          {categories.map((c) => (
            <option key={c} value={c}>
              {formatCategoryLabel(c)}
            </option>
          ))}
        </select>
        <input
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          placeholder="Monthly $"
          inputMode="decimal"
          disabled={saving}
        />
        <button type="submit" disabled={saving || !category || !amount}>
          {saving ? "Saving…" : "Set budget"}
        </button>
      </form>
    </section>
  );
}