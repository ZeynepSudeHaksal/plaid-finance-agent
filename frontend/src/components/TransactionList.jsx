import { useEffect, useState } from "react";
import { api } from "../api";

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

  if (loading) return <p className="hint">Loading transactions...</p>;
  if (error) return <p className="error">Error: {error}</p>;
  if (transactions.length === 0) return <p className="hint">No transactions synced yet.</p>;

  return (
    <div className="transaction-list">
      <h3>Recent transactions</h3>
      <table>
        <thead>
          <tr>
            <th>Date</th>
            <th>Merchant</th>
            <th>Category</th>
            <th>Amount</th>
          </tr>
        </thead>
        <tbody>
          {transactions.map((t) => (
            <tr key={`${t.date}-${t.name}-${t.amount}`}>
              <td>{t.date}</td>
              <td>{t.name}</td>
              <td>{t.category ?? "—"}</td>
              <td className={t.amount > 0 ? "amount-out" : "amount-in"}>
                {t.amount > 0 ? "-" : "+"}${Math.abs(t.amount).toFixed(2)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
