# Development Notes

Technical reference for the Budget Tracker codebase. Useful when returning to the project after time away or when extending the app.

---

## Architecture overview

Budget Tracker is a server-rendered web application. FastAPI handles all routing and serves HTML pages using Jinja2 templates. A small amount of JavaScript handles inline editing and HTMX-style interactions without full page reloads.

```
Browser → FastAPI → SQLAlchemy → SQLite
              ↓
          Jinja2 templates → HTML response
```

There is no separate frontend build step — Bootstrap, Chart.js, and HTMX are all loaded from CDN links in `base.html`.

---

## Database schema

### accounts

| Column | Type | Description |
|---|---|---|
| id | Integer | Primary key |
| name | String | Bank name (e.g. "Chase") |
| type | String | Account type (e.g. "checking") |

### categories

| Column | Type | Description |
|---|---|---|
| id | Integer | Primary key |
| name | String | Category name (e.g. "Groceries") |
| monthly_budget | Float | Monthly budget amount in dollars |

### transactions

| Column | Type | Description |
|---|---|---|
| id | Integer | Primary key |
| date | Date | Transaction date |
| amount | Float | Amount — negative for expenses, positive for income |
| description | String | Merchant or transaction description |
| notes | String | User-added notes (nullable) |
| account_id | Integer | Foreign key to accounts |
| category_id | Integer | Foreign key to categories (nullable = uncategorized) |

---

## Key files

### src/main.py

All FastAPI routes live here. Organized into three sections:

- **Frontend routes** — return HTML responses via Jinja2 templates
- **API routes** — return JSON responses, called by JavaScript in the browser
- **Helper functions** — shared utilities like `get_available_months()`, `get_monthly_spending()`

### src/models.py

SQLAlchemy ORM models for `Account`, `Category`, and `Transaction`. Relationships are defined here so that `transaction.category` and `transaction.account` work as expected in templates.

### src/database.py

Database connection setup. Uses an absolute path derived from `__file__` so the database is always found at `data/budget.db` regardless of where scripts are run from:

```python
DB_PATH = Path(__file__).resolve().parent.parent / "data" / "budget.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"
```

### src/categorizer.py

Two-strategy auto-categorization engine:

1. `match_by_keywords()` — checks description against `keywords.json`
2. `match_by_history()` — analyzes previous categorizations for the same description

Configurable thresholds:
```python
HISTORY_CONFIDENCE_THRESHOLD = 0.8  # 80% of history must agree
HISTORY_MIN_MATCHES = 3             # minimum 3 previous transactions needed
```

### src/import_transactions.py

CSV importer supporting Chase, Capital One, BECU, and Discover. Bank format definitions are read from `formats.json`. Key functions:

- `parse_amount()` — normalizes amounts to negative (expense) or positive (income)
- `parse_date()` — handles multiple date formats across banks
- `is_duplicate()` — checks for existing transactions by date + amount + description
- `import_csv()` — main orchestration with duplicate handling

---

## Adding a new page

1. Create a new template in `src/templates/` extending `base.html`
2. Add a route function in `src/main.py` decorated with `@app.get("/your-path", response_class=HTMLResponse)`
3. Add a nav link in `src/templates/base.html`

---

## Adding a new API endpoint

Add a new function in `src/main.py` with the appropriate decorator:

```python
@app.get("/api/your-endpoint")
def your_endpoint(db: Session = Depends(get_db)):
    ...
    return {"key": "value"}
```

All API endpoints are documented automatically at `/docs` (FastAPI's Swagger UI).

---

## Running the test suite

```bash
cd budget_tracker
pytest tests/ -v
```

Tests use an in-memory SQLite database so they never touch real data. Test fixtures are defined in `tests/conftest.py`.

### Test files

| File | What it tests |
|---|---|
| `test_formats.py` | Validates `formats.json` structure |
| `test_parsing.py` | Amount and date parsing for all bank formats |
| `test_duplicate.py` | Duplicate detection logic |
| `test_import.py` | End-to-end CSV imports for all banks |
| `test_categorizer.py` | Keyword and history matching |

---

## CI/CD

GitHub Actions runs the test suite automatically on every push to non-main branches and on pull requests to main. Configuration is in `.github/workflows/tests.yml`.

---

## Known limitations

- **No user authentication** — the app is designed for single-user local use only. Do not expose it to the internet without adding authentication.
- **Split transactions** — planned but not yet implemented. The actions menu shows it as disabled.
- **No pagination** — the transactions page loads all matching transactions at once. This may become slow with very large datasets.
- **SQLite only** — the app uses SQLite which is appropriate for local single-user use. Migrating to PostgreSQL would require updating `DATABASE_URL` in `database.py` and installing `psycopg2`.

---

## Dependency versions

Key packages and their roles:

| Package | Purpose |
|---|---|
| `fastapi` | Web framework and API |
| `uvicorn` | ASGI server |
| `sqlalchemy` | ORM and database abstraction |
| `jinja2` | HTML templating |
| `python-multipart` | Form data parsing |
| `pydantic` | Request/response validation |
| `pytest` | Test runner |
