# Backup & Restore

Budget Tracker includes a backup utility that protects your transaction data. This guide covers how backups work, how to create them manually, and how to restore from a backup if something goes wrong.

---

## How backups work

Backups are created automatically in two situations:

1. **Every time the app starts** — a backup is created when uvicorn starts up, but only if no backup has been made in the last 60 seconds (to prevent multiple backups during uvicorn's reload process)
2. **Every time you run the CSV importer** — a backup is created before any new transactions are imported

Backups are stored as timestamped `.db` files in the `backups/` folder:

```
backups/
    budget_20260201_083045.db
    budget_20260202_091230.db
    budget_20260301_120000.db
```

The most recent **30 backups** are kept automatically. Older backups are pruned when new ones are created.

---

## Creating a manual backup

Run this from the project root at any time:

```bash
python backup_db.py
```

Output:
```
Backup created: budget_20260301_143022.db
Size: 524,288 bytes

Total backups: 12 / 30
```

This is recommended before any significant operation such as bulk re-categorization or making database schema changes.

---

## Listing existing backups

```bash
python backup_db.py --list
```

Output:
```
Existing backups in C:\...\budget_tracker\backups:

   1. budget_20260301_143022.db  |     524,288 bytes  |  2026-03-01 14:30:22
   2. budget_20260228_091500.db  |     512,000 bytes  |  2026-02-28 09:15:00
   3. budget_20260227_083012.db  |     498,688 bytes  |  2026-02-27 08:30:12

Total: 3 backups
```

Backups are listed newest first.

---

## Restoring from a backup

If something goes wrong — accidental deletion, bad import, or corrupt data — you can restore from any backup:

```bash
python backup_db.py --restore budget_20260228_091500.db
```

Output:
```
Safety backup created: budget_20260301_150000_pre_restore.db
Restored: budget_20260228_091500.db → C:\...\budget_tracker\data\budget.db
Restart uvicorn to use the restored database.
```

!!! warning
    Always restart uvicorn after restoring a backup. The running app will still have the old database loaded in memory until it is restarted.

### Safety backup before restore

Every restore operation automatically creates a safety backup of your current database before overwriting it. This means you can always undo a restore if needed — just restore the `_pre_restore.db` file.

---

## Backup configuration

Two settings at the top of `backup_db.py` can be adjusted:

```python
MAX_BACKUPS = 30   # number of backups to keep
```

Increase `MAX_BACKUPS` if you want to keep more history. Each backup is roughly the same size as your database file.

---

## What is not backed up

The backup only covers `budget.db` — the database file containing your transactions, categories, and budget amounts. It does not back up:

- `keywords.json` — commit this to Git to keep it safe
- `categories.json` — commit this to Git to keep it safe
- `formats.json` — commit this to Git to keep it safe
- CSV import files in `csv_imports/` — keep originals from your bank

---

## Recommended backup habits

- Run `python backup_db.py` before any major operation
- Commit your JSON configuration files (`keywords.json`, `categories.json`, `formats.json`) to Git regularly
- Periodically copy the `backups/` folder to an external drive or cloud storage for offsite protection
