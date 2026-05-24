# Savings

The Savings page (`/savings`) tracks your savings account transactions and allocates them across named jars — budget categories marked as savings jars. Each jar represents a savings goal or fund (e.g. Emergency Fund, Property Taxes, New Car).

---

## Jar tiles

The top of the page shows a tile for each savings jar with:

- Current balance
- Percentage of total savings
- A small progress bar

Click any jar tile to open its history — a running balance chart and transaction list showing every deposit and withdrawal.

---

## Transaction ledger

The ledger lists all savings account transactions. Each row shows:

- Date, description, and amount
- Allocation status: **✓ Allocated** (green) or **⚠ Pending** (yellow)
- Which jars the transaction was allocated to and by how much

Unallocated transactions are highlighted in yellow — they need jar allocations before your jar balances are correct.

---

## Importing savings transactions

Click **Import CSV** (top right) and select your savings bank (ETrade or BECU). The importer adds new transactions and skips duplicates.

---

## Adding a transaction manually

Click **+ Add Transaction** to enter a transaction manually — useful for interest credits, manual transfers, or corrections.

After adding, the allocation modal opens automatically so you can allocate it to jars immediately.

---

## Allocating a transaction to jars

Every savings transaction needs to be allocated across jars so the jar balances stay accurate.

1. Click the **⋯** menu on an unallocated transaction → **Allocate**
2. The allocation modal shows all your jars with their current balances
3. Click a jar on the left to add it to the allocation table
4. Enter the amount for each jar
5. The balance bar shows whether allocations sum to the transaction amount
6. Click **Save Allocations**

### Default template

For recurring deposits (e.g. a regular paycheck deposit) you can save the allocation as a default template. Check **Save as default template** before saving. Next time a deposit of the same amount comes in, the template pre-fills automatically.

### Withdrawals

For withdrawal transactions, enter positive amounts — the modal automatically treats them as negative against each jar.

---

## Rebalancing jars

If jar balances drift from where you want them (e.g. after a large withdrawal that needs to come from multiple jars), click **Rebalance Jars**:

1. The modal shows current balances for all jars
2. Enter new target balances
3. The total must match the current total (the modal validates this)
4. Click **Apply Rebalance**

Rebalancing creates a $0 net transaction with the offsetting jar allocations to record the adjustment.

---

## Stat tiles

Four stat tiles show:

- **Account Balance** — total in the savings account
- **Jar Total** — sum of all jar balances (should match account balance)
- **Deposits YTD** — year-to-date deposits
- **Withdrawals YTD** — year-to-date withdrawals

If the account balance and jar total don't match, the jar total tile turns red with an "unallocated" warning.

---

## Filters

Use the filter panel to narrow the ledger by date range, description, or allocation status. Filter results preserve the hash in the URL so refreshing keeps the filter active.
