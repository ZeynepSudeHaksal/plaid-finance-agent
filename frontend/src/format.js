// Plaid's raw categories look like "FOOD_AND_DRINK" - display them as
// "Food And Drink" without changing the underlying value we store/match on.
export function formatCategoryLabel(raw) {
  if (!raw) return "Uncategorized";
  return raw
    .split("_")
    .map((w) => w.charAt(0) + w.slice(1).toLowerCase())
    .join(" ");
}