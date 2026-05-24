# Importing Transactions

Transactions are imported from your bank's CSV export directly through the browser. The importer supports Chase, Capital One, BECU, Discover, and ETrade (savings).

---

## Exporting from your bank

### Chase

1. Log in to [chase.com](https://chase.com)
2. Select the account
3. Click **Download account activity**
4. Select **CSV** format and choose your date range
5. Save the file

### Capital One

1. Log in to [capitalone.com](https://capitalone.com)
2. Select your account
3. Click **Download transactions** → **CSV**
4. Save the file

### BECU

1. Log in to [becu.org](https://becu.org)
2. Select your account → **Export** → **CSV**
3. Save the file

### Discover

1. Log in to [discover.com](https://discover.com)
2. Go to **Manage** → **Download Center**
3. Select date range and **CSV** format
4. Save the file

### ETrade (savings account)

ETrade CSV exports are used for the savings account ledger, imported separately via the Savings page.

---

## Running the importer

### From the Transactions page

1. Go to the **Transactions** page (`/transactions`)
2. Click the **Import CSV** button (top right)
3. Select your bank from the dropdown
4. Drag and drop your CSV file onto the drop zone, or click to browse
5. Click **Import**

The importer shows a result summary when complete:

| Field | Description |
|---|---|
| Imported | New transactions added |
| Auto-excluded | Transactions matching exclusion keywords (e.g. card payments) |
| Duplicates skipped | Already in the database |
| Skipped | Rows that couldn't be parsed |

After import, the categorization engine runs automatically and pre-fills suggestions for the review queue.

### From the Savings page

Savings account transactions are imported separately:

1. Go to the **Savings** page (`/savings`)
2. Click **Import CSV**
3. Select your savings bank (ETrade or BECU)
4. Select your file and click **Import**

---

## Auto-exclusion

Certain transactions are automatically excluded from reports on import — things like credit card payments and internal transfers that would double-count spending. These are defined in `exclude_keywords.json`:

```json
{
    "exclude_keywords": ["DISCOVER PAYMENT", "CHASE CREDIT", "TRANSFER TO"]
}
```

Auto-excluded transactions are hidden from the transactions page by default but can be viewed using the **Show Excluded** toggle. They appear in the review queue with a distinct flag so you can confirm the exclusion.

---

## After importing

After importing, go to the **Review Queue** (`/review`) to confirm the category suggestions. The engine pre-fills suggestions using keyword rules, transaction history, and ML predictions — most transactions will already have a suggested category waiting for your confirmation.

See the [Review Queue](review.md) guide for details on the confirmation workflow.

---

## Duplicate detection

Duplicates are detected by matching on date + amount + description. If you import the same CSV twice, duplicate rows are skipped automatically — no manual intervention needed.

---

## Adding a new bank format

Add a new entry to `formats.json` in the project root:

```json
"newbank": {
    "date_col": "Date",
    "description_col": "Description",
    "category_col": null,
    "amount_col": "Amount",
    "debit_col": null,
    "credit_col": null,
    "date_format": "%m/%d/%Y"
}
```

For banks with split debit/credit columns (like BECU), set `amount_col` to `null` and fill in `debit_col` and `credit_col` instead. No code changes are needed — the importer reads `formats.json` automatically.
