# Setup & Installation

This guide walks through setting up Budget Tracker on a Windows machine from scratch.

---

## Prerequisites

### Python 3.12+

Download from [python.org](https://python.org/downloads). During installation:

- Check **"Add python.exe to PATH"** — critical, do not skip
- Click **"Install Now"**
- If prompted to disable path length limit at the end, click it

Verify:

```bash
python --version
pip --version
```

Both should print version numbers without errors.

### Git

Download from [git-scm.com/download/win](https://git-scm.com/download/win). Default options throughout are fine.

---

## Project setup

### 1. Clone the repository

```bash
git clone https://github.com/eengel821/budget_tracker.git
cd budget_tracker
```

### 2. Create a virtual environment

```bash
python -m venv venv
venv\Scripts\activate
```

You'll see `(venv)` at the start of your prompt when it's active. You need to run this each time you open a new terminal.

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

This includes `scikit-learn` and `joblib` for the ML categorization engine.

### 4. Initialize the database

```bash
alembic upgrade head
```

This creates the database at `data/budget.db` and applies all migrations. Run this once on first setup and again any time you pull new changes that include migrations.

### 5. Set up configuration files

Copy the example config files and customize them:

```bash
copy keywords.example.json keywords.json
copy categories.example.json categories.json
copy exclude_keywords.example.json exclude_keywords.json
```

- **`keywords.json`** — keyword-to-category rules for auto-categorization
- **`categories.json`** — initial category seed list
- **`exclude_keywords.json`** — keywords that trigger auto-exclusion (e.g. credit card payments)

### 6. Seed initial categories and budgets

```bash
python scripts\seed_categories.py
python scripts\seed_budgets.py
```

### 7. Start the application

Double-click `start.bat` in the project root, or run manually:

```bash
venv\Scripts\activate
cd src
uvicorn main:app --host 127.0.0.1 --port 8000
```

Navigate to `http://127.0.0.1:8000`. The app automatically creates a backup of your database on each startup.

---

## Daily use

Double-click `start.bat` from the project root (or a desktop shortcut to it). It activates the virtual environment, opens Chrome to the app, and starts the server. Press `Ctrl+C` in the terminal window to stop.

---

## Project structure

```
budget_tracker/
  src/
    main.py                  ← app entry point, router registration
    models.py                ← SQLAlchemy ORM models
    database.py              ← database connection and session
    categorizer.py           ← auto-categorization engine (keyword + ML)
    schemas.py               ← Pydantic request models
    routers/
      pages.py               ← HTML page routes
      transactions.py        ← transaction CRUD API
      categories.py          ← category management API
      savings.py             ← savings jars API
      imports.py             ← CSV import and categorize-all
    services/
      aggregations.py        ← DB aggregation helpers
      budget.py              ← budget page data
    static/
      style.css
      js/                    ← per-page JavaScript files
    templates/               ← Jinja2 HTML templates
  tests/                     ← pytest test suite (374 tests)
  scripts/
    backup_db.py             ← database backup utility
    seed_categories.py       ← category seeder
    seed_budgets.py          ← budget amounts seeder
  alembic/                   ← database migration history
  docs/                      ← documentation source
  data/                      ← SQLite database (gitignored)
  backups/                   ← automatic backups (gitignored)
  csv_imports/               ← drop CSV files here (gitignored)
  keywords.json              ← keyword rules (gitignored, use .example.json as template)
  formats.json               ← bank CSV format definitions
  requirements.txt
  start.bat                  ← one-click launcher
```

---

## Running tests

```bash
pytest tests/ -v
```

Tests use an in-memory SQLite database and never touch real data.

---

## Updating after pulling changes

If a pull includes new migration files:

```bash
alembic upgrade head
```

If new dependencies were added:

```bash
pip install -r requirements.txt
```
