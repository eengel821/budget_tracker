# Review Queue

The Review Queue (`/review`) is where you confirm or correct category suggestions before they're saved. Every transaction that comes in through the importer lands here until you confirm it.

---

## How it works

The categorization engine pre-fills a suggested category for each transaction using three strategies in order:

1. **Keyword rules** — if the description matches a rule in `keywords.json`, the category is suggested immediately
2. **Transaction history** — if you've categorized the same merchant consistently before, that category is suggested
3. **ML model** — a TF-IDF + Logistic Regression model trained on your confirmed transactions predicts a category and shows a confidence score

Nothing is saved until you confirm. You stay in control.

---

## Reading the queue

Each row shows:

| Column | Description |
|---|---|
| Checkbox | Select for bulk actions |
| Date | Transaction date |
| Description | Merchant or transaction description |
| Account | Source bank account |
| Amount | Green = credit/income, red = expense |
| Source | Where the suggestion came from (see badges below) |
| Category | Dropdown pre-filled with the suggestion |
| ✓ / 👁 | Confirm or exclude buttons |

### Source badges

| Badge | Meaning |
|---|---|
| 🔑 Keyword | Matched a keyword rule — high confidence |
| ⏱ History | Matched past transaction history — high confidence |
| ML 84% | ML model prediction with confidence score |
| ML 62% | Low confidence — verify carefully before confirming |

Rows with keyword or history matches, and ML predictions above 75% confidence, are **pre-ticked** — ready to confirm in one click.

---

## Confirming suggestions

### Single row

Click the green **✓** button on any row to confirm that row's current dropdown selection. The row fades out and disappears from the queue.

The ✓ button is:

- **Grey/disabled** — no category selected yet
- **Green/enabled** — a category is selected and ready to confirm

### Confirm all pre-selected

Click **Confirm All Pre-selected** (top right) to confirm every pre-ticked row at once using each row's current dropdown value. This is the fastest path for a clean import — scan the queue, fix any wrong suggestions, then click once.

### Bulk actions bar

When you tick checkboxes, a bulk action bar appears above the table:

- **Confirm Selected** — confirms each checked row using its own dropdown value
- **Override all dropdown + → button** — pick one category and apply it to all checked rows at once
- **Exclude** — marks all checked rows as excluded from reports
- **Clear** — deselects everything

---

## Correcting a wrong suggestion

Just change the dropdown to the correct category. The ✓ button activates immediately. Click it to confirm your correction — the ML model retrains in the background so it learns from the correction for future imports.

---

## Excluding transactions

Some transactions shouldn't count toward your budget — credit card payments, internal transfers, reimbursements you've already accounted for elsewhere. Click the **👁** button on any row to exclude it from reports.

Excluded transactions can be viewed on the Transactions page using the **Show Excluded** toggle and can be restored at any time.

---

## Re-running suggestions

If you added new keyword rules or want to re-run the ML model after confirming more transactions, click **Re-run Suggestions** (top right). This runs the full categorization engine again on any transactions that don't yet have a suggestion.

---

## Navbar badge

The **Review** link in the navbar shows a yellow badge with the count of transactions waiting for confirmation. It updates automatically as you work through the queue and disappears when the queue is empty.
