# Categorization Guide

Budget Tracker automatically suggests and assigns categories to imported transactions using two strategies. This guide explains how the system works and how to get the most out of it.

---

## How auto-categorization works

When you click **Auto-categorize All** on the review page, the categorization engine processes every uncategorized transaction in two steps:

### Step 1 — Keyword matching

The engine checks the transaction description against every entry in `keywords.json`. If the description contains a matching keyword the corresponding category is assigned immediately.

For example if `keywords.json` contains:
```json
{ "keyword": "STARBUCKS", "category": "Coffee Shops", "match_type": "contains" }
```

Then any transaction with "STARBUCKS" anywhere in the description will be assigned to **Coffee Shops**.

Keyword matching is case-insensitive — `starbucks`, `STARBUCKS`, and `Starbucks` all match.

### Step 2 — History matching

If no keyword match is found, the engine looks at previously categorized transactions with the same description. If at least **3 previous transactions** share the same description and **80% or more** of them have the same category, that category is auto-assigned.

This means the system gets smarter over time — the more transactions you manually categorize, the better the auto-assignment becomes for future imports.

---

## The review queue

Any transaction that couldn't be auto-categorized appears in the **Review** queue at `/review`.

Each row shows:
- The transaction date, description, account, and amount
- A category dropdown pre-selected with the best suggestion if one exists (marked with ★)
- A **✓** button to confirm and save the category

Transactions disappear from the queue as you categorize them. The navbar shows a badge with the count of uncategorized transactions so you always know how many are waiting.

---

## Overriding a category

Auto-assigned categories aren't permanent — you can change any transaction's category at any time from the **Transactions** page at `/transactions`.

Click the category badge on any row to open an inline dropdown, select the correct category, and it saves immediately.

You can also use the **⋮ actions menu** on each row and select **Change Category**.

---

## Confidence thresholds

The history matching uses two configurable thresholds defined at the top of `src/categorizer.py`:

```python
HISTORY_CONFIDENCE_THRESHOLD = 0.8   # 80% of history must agree
HISTORY_MIN_MATCHES = 3               # minimum 3 previous transactions needed
```

If you find the auto-categorization is too aggressive or too conservative you can adjust these values. Lowering `HISTORY_CONFIDENCE_THRESHOLD` will auto-assign more transactions but with less certainty. Raising `HISTORY_MIN_MATCHES` requires more history before auto-assigning.

---

## Tips for better auto-categorization

- **Categorize consistently** — always use the same category for the same merchant. The history matcher looks for consistency, so mixed categorizations reduce confidence.
- **Add keywords for frequent merchants** — if you see the same merchant appearing repeatedly in the review queue, add it to `keywords.json` so future imports catch it automatically. See the [Adding Keywords & Categories](keywords.md) guide.
- **Run auto-categorize after every import** — click **Auto-categorize All** immediately after importing a new CSV to process as many transactions as possible before manual review.
