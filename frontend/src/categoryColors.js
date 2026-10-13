// A small, deliberately muted palette assigned to category names as they
// appear — shared by the transaction ledger's color bars and the "this
// month by category" chart, so the same category always reads as the same
// color everywhere in the app (color follows the entity, not which
// component happens to render it).
const CATEGORY_COLORS = [
  "#0f5257", "#7a3030", "#8a6d1f", "#3b5b8c", "#2c6e49", "#6b4e8c",
  "#a65c2e", "#44707a",
];

const assigned = new Map();

export function colorForCategory(category) {
  const key = category || "Uncategorized";
  if (!assigned.has(key)) {
    assigned.set(key, CATEGORY_COLORS[assigned.size % CATEGORY_COLORS.length]);
  }
  return assigned.get(key);
}
