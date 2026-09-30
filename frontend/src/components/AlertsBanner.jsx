import { useEffect, useState } from "react";
import { api } from "../api";

export default function AlertsBanner() {
  const [alerts, setAlerts] = useState([]);
  const [dismissed, setDismissed] = useState(() => new Set());
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .getAlerts()
      .then((res) => setAlerts(res.alerts || []))
      .catch(() => setAlerts([])) // alerts are a nice-to-have - fail quietly
      .finally(() => setLoading(false));
  }, []);

  const visible = alerts.filter((a) => !dismissed.has(a.id));

  if (loading || visible.length === 0) return null;

  const dismiss = (id) => setDismissed((prev) => new Set(prev).add(id));

  return (
    <section className="alerts">
      {visible.map((a) => (
        <div key={a.id} className={`alert-row ${a.severity}`}>
          <span className="bar" />
          <span className="alert-message">{a.message}</span>
          <button className="ghost-button" onClick={() => dismiss(a.id)}>
            dismiss
          </button>
        </div>
      ))}
    </section>
  );
}