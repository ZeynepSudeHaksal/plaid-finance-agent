import { useEffect, useState } from "react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  LineChart,
  Line,
} from "recharts";
import { api } from "../api";
import { formatCategoryLabel } from "../format";
import { colorForCategory } from "../categoryColors";

function formatMonthLabel(period) {
  // "2026-08" -> "Aug"
  const [, month] = period.split("-");
  const names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return names[parseInt(month, 10) - 1] ?? period;
}

const INK = "#12161f";
const ACCENT = "#0f5257";
const LINE = "#dbdcd6";

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div
      style={{
        background: "#fbfbfa",
        border: "1px solid " + LINE,
        padding: "6px 10px",
        fontFamily: "IBM Plex Mono, monospace",
        fontSize: 12.5,
      }}
    >
      <div style={{ color: "#8a8f85", marginBottom: 2 }}>{label}</div>
      <div>${payload[0].value.toFixed(2)}</div>
    </div>
  );
}

export default function SpendingCharts({ monthRange }) {
  const [byCategory, setByCategory] = useState([]);
  const [trend, setTrend] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      api.spendingByCategory(monthRange.start, monthRange.end),
      api.spendingTimeseries(),
    ])
      .then(([categorySummary, timeseries]) => {
        const rows = Object.entries(categorySummary.by_category || {})
          .map(([category, total]) => ({
            category,
            label: formatCategoryLabel(category),
            total,
            color: colorForCategory(category),
          }))
          .sort((a, b) => b.total - a.total)
          .slice(0, 8);
        setByCategory(rows);

        setTrend((timeseries.points || []).map((p) => ({ label: formatMonthLabel(p.period), total: p.total })));
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [monthRange.start, monthRange.end]);

  if (loading) return <p className="hint">Loading charts…</p>;
  if (error) return <p className="error">Error: {error}</p>;

  return (
    <section className="spending-charts">
      <h3>By category, {monthRange.label}</h3>
      {byCategory.length === 0 ? (
        <p className="hint">No spending in {monthRange.label}.</p>
      ) : (
        <>
          <ResponsiveContainer width="100%" height={Math.max(120, byCategory.length * 34)}>
            <BarChart data={byCategory} layout="vertical" margin={{ top: 0, right: 16, bottom: 0, left: 0 }}>
              <CartesianGrid horizontal={false} stroke={LINE} />
              <XAxis type="number" tick={{ fontSize: 11, fontFamily: "IBM Plex Mono", fill: "#8a8f85" }} axisLine={{ stroke: LINE }} tickLine={false} />
              <YAxis
                type="category"
                dataKey="label"
                width={140}
                tick={{ fontSize: 12.5, fontFamily: "Inter", fill: INK }}
                axisLine={{ stroke: LINE }}
                tickLine={false}
              />
              <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgba(15,82,87,0.06)" }} />
              <Bar dataKey="total" radius={[0, 2, 2, 0]} barSize={16}>
                {byCategory.map((row) => (
                  <Cell key={row.category} fill={row.color} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <div className="category-legend">
            {byCategory.map((row) => (
              <span key={row.category} className="category-legend-item">
                <span className="swatch" style={{ background: row.color }} />
                {row.label}
              </span>
            ))}
          </div>
        </>
      )}

      <h3 style={{ marginTop: 28 }}>Monthly trend</h3>
      {trend.length < 2 ? (
        <p className="hint">Not enough months of history yet to show a trend.</p>
      ) : (
        <ResponsiveContainer width="100%" height={160}>
          <LineChart data={trend} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid vertical={false} stroke={LINE} />
            <XAxis dataKey="label" tick={{ fontSize: 11.5, fontFamily: "Inter", fill: "#8a8f85" }} axisLine={{ stroke: LINE }} tickLine={false} />
            <YAxis tick={{ fontSize: 11, fontFamily: "IBM Plex Mono", fill: "#8a8f85" }} axisLine={false} tickLine={false} width={56} />
            <Tooltip content={<ChartTooltip />} />
            <Line type="monotone" dataKey="total" stroke={ACCENT} strokeWidth={2} dot={{ r: 3, fill: ACCENT }} />
          </LineChart>
        </ResponsiveContainer>
      )}
    </section>
  );
}