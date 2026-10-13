import { useState } from "react";

// A single month-range control, shared by the category chart and the
// budget panel below it, so "October 2026" always means the same thing
// in both places at once rather than each section picking its own
// range independently.
export function useMonthRange() {
  const now = new Date();
  const [cursor, setCursor] = useState(new Date(now.getFullYear(), now.getMonth(), 1));

  const isCurrentMonth =
    cursor.getFullYear() === now.getFullYear() && cursor.getMonth() === now.getMonth();

  const start = cursor;
  const end = isCurrentMonth ? now : new Date(cursor.getFullYear(), cursor.getMonth() + 1, 0);
  const iso = (d) => d.toISOString().slice(0, 10);

  return {
    label: cursor.toLocaleDateString(undefined, { month: "long", year: "numeric" }),
    start: iso(start),
    end: iso(end),
    isCurrentMonth,
    goPrevious: () => setCursor((c) => new Date(c.getFullYear(), c.getMonth() - 1, 1)),
    goNext: () => setCursor((c) => new Date(c.getFullYear(), c.getMonth() + 1, 1)),
  };
}

export default function MonthPicker({ range }) {
  return (
    <div className="month-picker">
      <button
        type="button"
        className="month-picker-arrow"
        onClick={range.goPrevious}
        aria-label="Previous month"
      >
        ‹
      </button>
      <span className="month-picker-label">{range.label}</span>
      <button
        type="button"
        className="month-picker-arrow"
        onClick={range.goNext}
        disabled={range.isCurrentMonth}
        aria-label="Next month"
      >
        ›
      </button>
    </div>
  );
}
