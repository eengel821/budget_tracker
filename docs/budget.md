# Budget Page

The Budget page (`/budget`) compares your actual spending against your monthly budgets. It covers both regular expense categories and the savings section, and handles credits, refunds, and budget month overrides.

---

## Month selector

Use the dropdown in the top right to switch between months. The selector shows the most recent 12 months with the current month first. For older months use the date range filter on the Transactions page.

---

## Summary cards

Four stat tiles at the top of the page show:

- **Total Budgeted** — sum of all category monthly budgets
- **Total Spent** — net expenses for the month
- **Remaining** — budgeted minus spent
- **Total Income** — income transactions for the month

---

## Monthly Expenses table

Each category with a budget set is listed with:

| Column | Description |
|---|---|
| Category | Category name |
| Budgeted | Monthly budget amount |
| Spent | Actual spending (red) or credit received (green) |
| Remaining | Budget minus spent. Positive = under budget, negative = over |
| Progress | Visual bar and percentage |

### Progress bar colors

| Color | Threshold | Meaning |
|---|---|---|
| Green | 0 – 105% | On track |
| Yellow | 105 – 115% | Slightly over, watch this |
| Red | > 115% | Significantly over budget |

### Credit / refund handling

If a category has a net credit (e.g. a doctor's reimbursement that exceeds charges), the Spent column shows green and the Remaining column shows the full budget plus the credit amount. The progress bar shows full green with "credit received".

---

## Expenses from Savings table

Categories with no monthly budget (zero-budget categories, including savings jars) appear in a separate section below the main table. These track spending from savings allocations and transfers.

---

## Income table

Income categories (marked `is_income=True`) are shown separately at the bottom. These show earnings against any income targets you've set.

---

## Setting budgets

Click **Manage Budgets** to go to `/budget/manage` where you can:

- Set or update the monthly budget for any category
- Add new categories
- Toggle the income and savings flags
- Rename categories

Changes take effect immediately — no restart needed.

---

## Budget month override

Sometimes a transaction arrives in the wrong month — for example a savings reimbursement that lands in May but covers April expenses. You can attribute any transaction to a different budget month without changing its real date:

1. Go to the **Transactions** page
2. Find the transaction
3. Click the **⋯** menu → **Set Budget Month**
4. Pick the month it should count toward
5. Click **Save**

A small blue badge appears in the date cell showing the budget attribution (e.g. `Apr 2026`). The transaction still shows its real date everywhere else — only the budget page uses the override.

For split transactions, setting the budget month on the parent automatically propagates to all children.

To clear an override, open the same modal and click **Clear Override**.

---

## Charts

The budget page includes bar charts comparing budgeted vs actual spending across categories, making it easy to spot which categories are on track and which need attention.
