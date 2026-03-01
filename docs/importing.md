# CSV Import Guide

Budget Tracker supports importing transactions from four banks. Each bank exports CSVs in a slightly different format — the importer handles all of them automatically.

---

## Exporting from your bank

### Chase

1. Log in to [chase.com](https://chase.com)
2. Select the account you want to export
3. Click **Download account activity**
4. Select **CSV** as the format and choose your date range
5. Save the file

Chase CSV format:
```
Transaction Date,Post Date,Description,Category,Type,Amount,Memo
02/18/2026,02/20/2026,SDOT PAYBYPHONE PARKING,Travel,Sale,-7.00,
```

### Capital One

1. Log in to [capitalone.com](https://capitalone.com)
2. Select your account
3. Click **Download transactions**
4. Select **CSV** format
5. Save the file

Capital One CSV format:
```
Transaction Date,Posted Date,Card No.,Description,Category,Debit,Credit
2026-02-20,2026-02-21,2717,TST* PEACE OF MIND BRE,Dining,15.92,
```

### BECU

1. Log in to [becu.org](https://becu.org)
2. Select your account
3. Click **Export** or **Download**
4. Select **CSV** format
5. Save the file

BECU CSV format:
```
"Date","No.","Description","Debit","Credit"
"1/30/2026","","Deposit - Online Banking Transfer","","30"
```

### Discover

1. Log in to [discover.com](https://discover.com)
2. Go to **Manage** → **Download Center**
3. Select your date range and **CSV** format
4. Save the file

Discover CSV format:
```
Trans. Date,Post Date,Description,Amount,Category
01/18/2026,01/18/2026,DIRECTPAY FULL BALANCE,-500.00,Payments and Credits
```

---

## Running the importer

### 1. Place your CSV file in the import folder

Copy your exported CSV file into the `csv_imports/` folder in the project root.

### 2. Run the importer

From the project root with your virtual environment active:

```bash
python src/import_transactions.py
```

### Interactive mode

Running with no arguments shows available files and prompts you:

```
Available CSV files in C:\...\budget_tracker\csv_imports:
  1. chase_feb2026.csv
  2. becu_jan2026.csv

Available banks: chase, capitalone, becu, discover

Enter filename to import: chase_feb2026.csv
Enter bank name: chase
```

### Direct mode

Pass the filename and bank name directly:

```bash
python src/import_transactions.py chase_feb2026.csv chase
python src/import_transactions.py becu_jan2026.csv becu
python src/import_transactions.py capitalone_feb2026.csv capitalone
python src/import_transactions.py discover_jan2026.csv discover
```

---

## Handling duplicates

If a transaction already exists in the database with the same date, amount, and description, you will be prompted:

```
Duplicate found:
  Date:        2026-02-18
  Description: SDOT PAYBYPHONE PARKING
  Amount:      -7.00
  Action? (y=import, n=skip, ia=import all, sa=skip all):
```

| Option | Action |
|---|---|
| `y` | Import this duplicate |
| `n` | Skip this duplicate |
| `ia` | Import all remaining duplicates without prompting |
| `sa` | Skip all remaining duplicates without prompting |

---

## After importing

Once the import completes you will see a summary:

```
--- Import Complete: chase_feb2026.csv ---
  Imported:           47
  Duplicates skipped: 3
  Rows skipped:       1
```

After importing, go to the **Review** page at `/review` in the browser and click **Auto-categorize All** to let the system categorize as many transactions as possible automatically. Any that can't be matched will remain in the review queue for manual categorization.

---

## Adding a new bank format

If you need to import from a bank not currently supported, add a new entry to `formats.json` in the project root:

```json
{
    "keyword": "newbank",
    "date_col": "Date",
    "description_col": "Description",
    "category_col": "Category",
    "amount_col": "Amount",
    "debit_col": null,
    "credit_col": null,
    "date_format": "%m/%d/%Y"
}
```

No code changes are needed — the importer reads `formats.json` automatically.

---

## Troubleshooting

**"Unknown bank format" error**
Make sure the bank name you entered exactly matches one of: `chase`, `capitalone`, `becu`, `discover`

**"File not found" error**
Make sure the CSV file is in the `csv_imports/` folder and the filename is spelled correctly.

**Rows being skipped unexpectedly**
Open the CSV file in a text editor and check for blank rows at the top or bottom, or rows with a different number of columns than the header.
