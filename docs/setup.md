# Setup & Installation

This guide walks through setting up Budget Tracker on a Windows 11 machine from scratch.

## Prerequisites

### Python

Download and install Python from [python.org](https://python.org/downloads). During installation:

- Check **"Add python.exe to PATH"** — this is critical, do not skip it
- Click **"Install Now"**
- If prompted to "Disable path length limit" at the end, click it

Verify the installation worked by opening Command Prompt and running:

```bash
python --version
pip --version
```

Both should print version numbers without errors.

### Git

Download and install Git from [git-scm.com/download/win](https://git-scm.com/download/win). Default options throughout are fine.

### VS Code (recommended)

Download from [code.visualstudio.com](https://code.visualstudio.com). Install the **Python** extension from Microsoft inside VS Code for autocomplete and virtual environment support.

---

## Project setup

### 1. Clone the repository

```bash
git clone https://github.com/yourusername/budget-tracker.git
cd budget_tracker
```

### 2. Create a virtual environment

```bash
python -m venv venv
venv\Scripts\activate
```

You'll know the virtual environment is active when you see `(venv)` at the start of your terminal prompt. You'll need to run `venv\Scripts\activate` each time you open a new terminal session.

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Create required folders

```bash
mkdir data
mkdir backups
type nul > backups\.gitkeep
type nul > csv_imports\.gitkeep
```

### 5. Initialize the database

```bash
python -c "import sys; sys.path.insert(0, 'src'); from database import init_db; init_db(); print('Done')"
```

You should see `Done` and a `budget.db` file will appear in the `data/` folder.

### 6. Seed categories and budgets

```bash
python seed_categories.py
python seed_budgets.py
```

### 7. Start the application

```bash
cd src
uvicorn main:app --reload
```

Navigate to `http://127.0.0.1:8000` in your browser. You should see the dashboard.

---

## Daily workflow

Every time you want to work with the app:

```bash
cd budget_tracker
venv\Scripts\activate
cd src
uvicorn main:app --reload
```

To stop the app press `Ctrl + C` in the terminal.

---

## Project structure

```
budget_tracker/
    src/                        ← application source code
        main.py                 ← FastAPI app and all routes
        models.py               ← SQLAlchemy database models
        database.py             ← database connection and session
        base.py                 ← SQLAlchemy declarative base
        categorizer.py          ← auto-categorization engine
        import_transactions.py  ← CSV importer
        templates/              ← Jinja2 HTML templates
        static/                 ← CSS and static assets
    tests/                      ← pytest test suite
    docs/                       ← documentation source (Markdown)
    site/                       ← built documentation HTML (gitignored)
    data/                       ← SQLite database (gitignored)
    backups/                    ← database backups (gitignored)
    csv_imports/                ← drop CSV files here (gitignored)
    categories.json             ← category list
    keywords.json               ← keyword-to-category mappings
    formats.json                ← bank CSV format definitions
    seed_categories.py          ← category database seeder
    seed_budgets.py             ← budget amounts seeder
    backup_db.py                ← database backup utility
    mkdocs.yml                  ← documentation configuration
    requirements.txt            ← Python dependencies
```

---

## Running tests

```bash
cd budget_tracker
pytest tests/ -v
```

---

## Updating dependencies

After installing new packages, update `requirements.txt`:

```bash
pip freeze > requirements.txt
```

---

## Setting up VS Code

After opening the project folder in VS Code:

1. Press `Ctrl + Shift + P` and type **Python: Select Interpreter**
2. Select the interpreter that shows `venv` in the path
3. The status bar at the bottom left should show the Python version with `venv`

To run tests inside VS Code:

1. Press `Ctrl + Shift + P` and run **Python: Configure Tests**
2. Select **pytest** and point it at the `tests/` folder
3. A Testing panel will appear in the left sidebar
