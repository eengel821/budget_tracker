# Categories Page

The Categories page (`/categories`) shows spending trends for each category over the past 12 months, with sparkline charts in the table and a detailed chart that expands when you click a row.

---

## Category table

Each row shows:

| Column | Description |
|---|---|
| Category | Category name |
| Budget | Monthly budget amount |
| Avg Spent | Average monthly spending over the last 12 months |
| Status badge | On Track / Watch / Over / No Budget |
| Trend | Sparkline bar chart — green = under budget, yellow = 105–115%, red = over 115% |

Click any row to expand a detailed chart showing budgeted vs actual spending by month, plus an Over/Under trend line.

---

## Status badges

| Badge | Meaning |
|---|---|
| On Track | Average spending within budget |
| Watch | Average spending 105–115% of budget |
| Over | Average spending above 115% of budget |
| No Budget | No monthly budget set |

---

## Managing categories

Category management is done from the **Manage Budgets** page (`/budget/manage`):

- **Add a category** — enter a name and optional budget amount in the Add form at the bottom
- **Rename** — click the category name inline to edit it
- **Set budget** — enter an amount and click Save (or Save All to update everything at once)
- **Income flag** — toggle to mark a category as income (excluded from expense totals)
- **Savings flag** — toggle to make a category a savings jar (appears on the Savings page)

!!! warning
    Removing the savings flag from a category that has a non-zero jar balance is blocked. You must rebalance the jar to $0 first.

---

## Category naming tips

- Keep names short — they appear in chart labels, table cells, and dropdowns
- Use consistent capitalization — names are displayed exactly as entered
- Avoid special characters

---

## Deleting a category

Categories cannot be deleted from the UI if they have transactions assigned to them. To remove a category, first re-categorize or delete any transactions that use it, then remove it from the database directly or via a script.
