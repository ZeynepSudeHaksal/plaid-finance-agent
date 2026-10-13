import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { formatCategoryLabel } from "../format";
import { colorForCategory } from "../categoryColors";

const PAGE_SIZE = 20;

function formatDate(isoDate) {
  const d = new Date(isoDate + "T00:00:00");
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export default function TransactionList() {
  const [transactions, setTransactions] = useState([]);
  const [categories, setCategories] = useState([]);
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(null);

  const [search, setSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");

  useEffect(() => {
    api.getCategories().then((res) => setCategories(res.categories || [])).catch(() => {});
  }, []);

  useEffect(() => {
    const isFirstLoad = limit === PAGE_SIZE;
    if (isFirstLoad) setLoading(true);
    else setLoadingMore(true);

    api
      .getTransactions(limit)
      .then(setTransactions)
      .catch((e) => setError(e.message))
      .finally(() => {
        setLoading(false);
        setLoadingMore(false);
      });
  }, [limit]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return transactions.filter((t) => {
      const matchesSearch = !q || t.name.toLowerCase().includes(q);
      const matchesCategory = !categoryFilter || t.category === categoryFilter;
      return matchesSearch && matchesCategory;
    });
  }, [transactions, search, categoryFilter]);

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

  const total = filtered.filter((t) => t.amount > 0).reduce((sum, t) => sum + t.amount, 0);
  const isFiltered = search.trim() !== "" || categoryFilter !== "";
  // transactions.length === limit is a heuristic: the API doesn't return a
  // total count, so a full page suggests there may be more to fetch. If the
  // last page comes back short, this naturally stops offering "load more".
  const mayHaveMore = transactions.length === limit;

  return (
    <section className="transaction-list">
      <h3>Recent activity</h3>
      <div className="ledger-total">
        ${total.toFixed(2)}
        <span style={{ fontFamily: "var(--font-body)", fontSize: 13, color: "var(--ink-faint)", marginLeft: 8 }}>
          {isFiltered
            ? `across ${filtered.length} matching transaction${filtered.length === 1 ? "" : "s"}`
            : `across last ${transactions.length} transactions`}
        </span>
      </div>

      <div className="ledger-filters">
        <input
          className="ledger-search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search merchant…"
        />
        <select value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)}>
          <option value="">All categories</option>
          {categories.map((c) => (
            <option key={c} value={c}>
              {formatCategoryLabel(c)}
            </option>
          ))}
        </select>
      </div>

      {filtered.length === 0 ? (
        <p className="hint">No transactions match that search.</p>
      ) : (
        <div className="ledger">
          {filtered.map((t) => (
            <div className="ledger-row" key={`${t.date}-${t.name}-${t.amount}`}>
              <span className="bar" style={{ background: colorForCategory(t.category) }} />
              <span className="date">{formatDate(t.date)}</span>
              <span className="merchant">
                {t.name}
                <span className="category">{formatCategoryLabel(t.category)}</span>
              </span>
              <span className={`amount ${t.amount > 0 ? "out" : "in"}`}>
                {t.amount > 0 ? "−" : "+"}${Math.abs(t.amount).toFixed(2)}
              </span>
            </div>
          ))}
        </div>
      )}

      {mayHaveMore && (
        <button
          type="button"
          className="ghost-button load-more"
          onClick={() => setLimit((l) => l + PAGE_SIZE)}
          disabled={loadingMore}
        >
          {loadingMore ? "Loading…" : "Load more"}
        </button>
      )}
    </section>
  );
}
