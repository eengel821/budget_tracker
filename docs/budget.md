# Budget Management

This guide explains how to set up and manage your monthly budgets and how to interpret the budget vs actual comparison pages.

---

## Setting budget amounts

### From the browser

Go to `/budget/manage` or click the **Manage Budgets** button on the Budget page.

Each category is listed with an amount field. Enter your desired monthly budget and click **Save** to update it immediately. Use **Save All** at the bottom to save every category at once.

The total monthly budget is shown in the footer and updates as you make changes.

### From seed_budgets.py

For bulk updates, edit the `BUDGET_AMOUNTS` dictionary in `seed_budgets.py` in the project root:

```python
BUDGET_AMOUNTS = {
    "Groceries":   900.00,
    "Restaurants": 400.00,
    "Gas":         350.00,
    ...
}
```

Then run the seeder:

```bash
python seed_budgets.py
```

This is safe to re-run at any time — it updates existing amounts without creating duplicates.

---

## Budget vs Actual page

The **Budget** page at `/budget` shows how your actual spending compares to your budgeted amounts for the selected month.

### Summary cards

Three stat cards at the top show:

- **Total Budgeted** — sum of all category budgets
- **Total Spent** — sum of all categorized expenses for the month
- **Remaining / Over Budget** — the difference, shown in green if under budget or red if over

### Category breakdown table

Each category with a budget set is listed with:

| Column | Description |
|---|---|
| Budgeted | Your monthly budget for this category |
| Spent | Actual spending this month |
| Remaining | Budget minus spent — negative means over budget |
| Progress | Visual bar showing percentage of budget used |

### Progress bar colors

| Color | Meaning |
|---|---|
| Green | Under 80% of budget used |
| Yellow | Between 80% and 100% of budget used |
| Red | Over budget |

### Selecting a month

Use the month selector in the top right to view any month that has transaction data.

---

## Category breakdown page

The **Categories** page at `/categories` shows a doughnut chart and table breaking down spending by category for the selected month.

This page is useful for understanding where your money is going at a high level, without comparing against budget targets.

---

## Tips

- Categories with a budget of $0.00 are hidden from the budget comparison page but still appear in the category breakdown
- Only transactions with a negative amount (expenses) count toward spending totals — income and credits are excluded
- Uncategorized transactions do not appear in any budget or category totals — categorize them first from the Review queue for accurate reporting
