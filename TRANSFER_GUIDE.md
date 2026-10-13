# Moving Budget Tracker to Another Machine

This guide is for the GitHub commit `ded539a` and the separate archive
`budget_tracker-local-transfer-2026-10-13.zip`. The commit contains the source
code and tests. The ZIP contains local files that are intentionally not tracked
by Git, including the personal SQLite database. Treat the ZIP as sensitive
financial data.

## 1. Get the source code

On the new Windows machine, install Git and Python 3.12 or newer, then open
PowerShell in the folder where you want the project:

```powershell
git clone https://github.com/eengel821/budget_tracker.git
cd budget_tracker
git pull origin main
git log -1 --oneline
```

The latest line should include `ded539a Separate learning and budget
categories` (or a newer commit on `main`).

## 2. Restore the local files from the ZIP

Copy `budget_tracker-local-transfer-2026-10-13.zip` next to the cloned
`budget_tracker` folder. Extract the archive **into the root of the cloned
`budget_tracker` folder**, preserving the archive's directory structure. For
example, `data/budget.db` must end up at `budget_tracker\data\budget.db`, and
the backup databases must end up in `budget_tracker\backups\`.

If Windows asks whether to replace an existing file, the archive is intended
to restore the transferred local version. In particular, replace a newly
created `data\budget.db` with the database from the ZIP. Do not extract into a
new nested `budget_tracker-local-transfer-...` folder.

### Files in the archive and destinations

| ZIP path | Destination | Purpose |
| --- | --- | --- |
| `notes.txt` | Project root: `notes.txt` | Personal notes and backlog |
| `categories.json` | Project root: `categories.json` | Local category configuration |
| `exclude_keywords.json` | Project root: `exclude_keywords.json` | Local exclusion rules |
| `keywords.json` | Project root: `keywords.json` | Local categorization rules |
| `seed_budgets.py` | Project root: `seed_budgets.py` | Local budget seeding script |
| `data/budget.db` | `data\budget.db` | Current personal budget database |
| `backups/*.db` | `backups\` | Database backups; keep these as recovery copies |

The archive has these 31 database backups in `backups\`:

```text
budget_20261010_210808.db
budget_20261010_210809.db
budget_20261010_210810.db
budget_20261010_210811.db
budget_20261013_073946.db
budget_20261013_073947.db
budget_20261013_073948.db
budget_20261013_073949.db
budget_20261013_073950.db
budget_20261013_073951.db
budget_20261013_073952.db
budget_20261013_073953.db
budget_20261013_073954.db
budget_20261013_073955.db
budget_20261013_073956.db
budget_20261013_073957.db
budget_20261013_073958.db
budget_20261013_073959.db
budget_20261013_074000.db
budget_20261013_074001.db
budget_20261013_074002.db
budget_20261013_074003.db
budget_20261013_074004.db
budget_20261013_074005.db
budget_20261013_074006.db
budget_20261013_074007.db
budget_20261013_074008.db
budget_20261013_074009.db
budget_20261013_074010.db
budget_pre_split.db
pre_learning_category_20261010.db
```

The archive does not contain a CSV import file. The `csv_imports\` folder can
remain empty unless you separately need to transfer CSVs.

## 3. Install dependencies and update the database schema

From the project root in PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
alembic upgrade head
```

Run the migration after restoring `data\budget.db`. It upgrades the transferred
database to the current source-code schema, including the learning-category
column, while preserving existing transaction category labels. Keep the ZIP
and its backups until you have confirmed the app and data are working.

If PowerShell blocks activation, you can avoid activation and run the tools
directly:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\alembic.exe upgrade head
```

Do not run category or budget seed scripts against the restored database as
part of setup; it already contains the local data.

## 4. Run the tests

From the project root, with the virtual environment active:

```powershell
python -m pytest tests\ -v
```

The tests use an in-memory SQLite database, so they do not alter the transferred
`data\budget.db`. The current targeted test run on the source machine passed
104 tests; the complete suite on the new machine is the final verification.
The app's startup hook may create timestamped copies in `backups\` when tests
start the application; those are additional backups, not test failures.

## 5. Start the application

After tests pass:

```powershell
Set-Location src
..\venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000> in a browser. Stop the server with `Ctrl+C`.

## 6. Confirm the restore

- In the project root, run `git status --short --branch`; source should be up
  to date with `origin/main`. The restored JSON, notes, database, and backups
  are intentionally ignored by Git.
- Confirm the app starts and the expected accounts, categories, and
  transactions appear.
- Keep the transfer ZIP and backup databases until you are satisfied the new
  machine has the complete data.
