# Backup & Restore

Budget Tracker automatically backs up your database on every startup. This guide covers how backups work, how to manage them, and how to restore if something goes wrong.

---

## Automatic backups

A backup is created every time the app starts — when you double-click `start.bat` or run uvicorn manually. Backups are stored as timestamped `.db` files in the `backups/` folder:

```
backups/
    budget_20260401_083045.db
    budget_20260402_091230.db
    budget_20260501_120000.db
```

The most recent **30 backups** are kept. Older ones are pruned automatically when new ones are created.

---

## Manual backup

Run from the project root at any time:

```bash
python scripts\backup_db.py
```

Recommended before any major operation — bulk re-categorization, schema changes, or experimenting with data.

---

## Listing backups

```bash
python scripts\backup_db.py --list
```

Output:
```
Existing backups in C:\...\budget_tracker\backups:

   1. budget_20260501_120000.db  |     98,304 bytes  |  2026-05-01 12:00:00
   2. budget_20260430_083000.db  |     95,232 bytes  |  2026-04-30 08:30:00
   ...
```

---

## Restoring a backup

```bash
python scripts\backup_db.py --restore budget_20260430_083000.db
```

Output:
```
Safety backup created: budget_20260501_130000_pre_restore.db
Restored: budget_20260430_083000.db → C:\...\budget_tracker\data\budget.db
Restart uvicorn to use the restored database.
```

!!! warning
    Always restart the app after restoring. The running server still has the old database loaded in memory until it restarts.

### Safety backup

Every restore automatically creates a safety backup of the current database first — named with `_pre_restore` in the filename. This means you can always undo a restore by restoring that file.

---

## Configuration

At the top of `scripts/backup_db.py`:

```python
MAX_BACKUPS = 30   # how many backups to keep
```

Increase this if you want more history. Each backup is roughly the same size as your database file (typically 100–500 KB).

---

## What is not backed up

The backup only covers `data/budget.db`. It does not cover:

- `keywords.json` — track this in Git
- `categories.json` — track this in Git  
- `exclude_keywords.json` — track this in Git
- `formats.json` — already committed to Git
- CSV files in `csv_imports/` — keep originals from your bank

---

## Recommended habits

- The automatic startup backup covers day-to-day protection
- Run a manual backup before any large import or bulk edit
- Periodically copy the `backups/` folder to an external drive or cloud storage
- Commit your JSON config files to Git after making keyword or category changes
