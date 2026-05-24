# Transactions Page

The Transactions page (`/transactions`) is the full ledger of all imported and manually entered transactions. It supports filtering, inline editing, splitting, exclusion, and budget month overrides.

---

## Filters

Click the **Filters** panel to filter by:

- **Month** — last 12 months shown, newest first. Use date range for older months.
- **Date range** — start and end date for custom ranges
- **Account** — filter by source bank
- **Category** — filter by category (includes split children)
- **Description** — text search
- **Show excluded** — toggle to include excluded transactions

The filter badge on the panel header turns blue when any filter is active.

---

## Inline editing

Several fields can be edited directly in the table without opening a modal:

- **Description** — click the description text to edit inline. Press Enter to save, Escape to cancel.
- **Notes** — click the notes field ("Add note...") to add or edit a note
- **Category** — click the category badge to open an inline dropdown

---

## Transaction actions menu

Click the **⋯** button on any row to access:

- **Add / Edit Note** — add context to a transaction
- **Set Budget Month** — attribute a transaction to a different budget month (see below)
- **Split Transaction** — divide into multiple category amounts
- **Exclude from reports** — hide from budget and category totals
- **Delete** — permanently remove the transaction

---

## Splitting transactions

Split a transaction when a single charge covers multiple categories — for example a Costco run that includes both groceries and household supplies.

1. Click **⋯** → **Split Transaction**
2. The split modal shows the total amount
3. Add rows for each category and enter the amount for each
4. The remainder bar shows how much is left to allocate — must reach $0 to save
5. Click **Save Split**

Split children appear as indented rows under the parent. Click the parent row's chevron to expand or collapse them. To undo a split, click **⋯** → **Remove Split**.

---

## Budget month override

When a transaction arrives in the wrong month for budget purposes — for example a reimbursement that lands in May but covers April expenses:

1. Click **⋯** → **Set Budget Month**
2. Pick the month it should count toward on the budget page
3. Click **Save**

A blue badge appears in the date cell (e.g. `Apr 2026`). The transaction's real date is unchanged — only the budget page uses the override.

For split transactions, the override propagates automatically to all children.

Click **Clear Override** to revert to the real date.

---

## Excluding transactions

Excluded transactions are hidden from budget totals and the default transaction view. Common reasons to exclude:

- Credit card payments (avoid double-counting)
- Internal transfers between accounts
- Reimbursements already tracked elsewhere

Click **⋯** → **Exclude from reports**, or use the bulk exclude action in the review queue.

To view excluded transactions, enable **Show Excluded** in the filters. To restore one, click **⋯** → **Un-exclude**.

---

## Sorting

Click any column header to sort. Click again to reverse. The sort icon shows the current direction.

---

## Bulk export

Use the **Export CSV** button to download the currently filtered transaction list as a CSV file.
