# Development Notes

Technical reference for the Budget Tracker codebase.

---

## Architecture overview

Budget Tracker is a server-rendered web application. FastAPI handles routing and serves HTML via Jinja2 templates. JavaScript handles inline editing, modals, and API calls without full page reloads. There is no frontend build step — Bootstrap, Chart.js, and HTMX are loaded from CDN.

```
Browser → FastAPI routers → Services → SQLAlchemy → SQLite
                ↓
         Jinja2 templates → HTML response
```

---

## Project structure

```
src/
  main.py               ← app entry point, router registration, lifespan hook
  models.py             ← SQLAlchemy ORM models
  database.py           ← engine, session, init_db()
  base.py               ← SQLAlchemy declarative base
  categorizer.py        ← categorization engine (keyword + history + ML)
  schemas.py            ← Pydantic request models
  deps.py               ← shared template instance and src_path
  import_transactions.py ← CSV parsing helpers
  routers/
    pages.py            ← all HTML page routes
    transactions.py     ← transaction CRUD API
    categories.py       ← category management API
    savings.py          ← savings jars API
    imports.py          ← CSV import + suggest-all route
  services/
    aggregations.py     ← DB aggregation helpers (spending, income, jars)
    budget.py           ← budget page data construction
  static/
    style.css
    js/                 ← per-page JS (transactions.js, savings.js, etc.)
  templates/            ← Jinja2 HTML templates
scripts/
  backup_db.py          ← database backup utility
  seed_categories.py    ← category seeder
  seed_budgets.py       ← budget amounts seeder
tests/                  ← pytest test suite (374 tests, 93% coverage)
alembic/                ← migration history
```

---

## Database schema

### Key models

**Transaction** — core model with all budget-related fields:

| Column | Type | Notes |
|---|---|---|
| id | Integer | PK |
| date | Date | Real transaction date |
| amount | Float | Negative = expense, positive = income/credit |
| description | String | Merchant/transaction description |
| notes | String | User-added notes (nullable) |
| excluded | Boolean | Hidden from budget totals |
| is_split | Boolean | Parent of a split transaction |
| parent_id | Integer | FK to self — set on split children |
| account_id | Integer | FK to accounts |
| category_id | Integer | FK to categories — null = uncategorized |
| budget_month | Date | Budget attribution override (nullable) |
| suggested_category_id | Integer | Pre-filled suggestion (nullable) |
| suggestion_confidence | Float | ML confidence 0–1 (nullable) |
| suggestion_source | String | "keyword", "history", or "ml" (nullable) |

**Category** — budget categories:

| Column | Type | Notes |
|---|---|---|
| monthly_budget | Float | 0 = zero-budget / savings jar |
| is_income | Boolean | Income categories excluded from expense totals |
| is_savings | Boolean | Appears as savings jar on Savings page |

---

## Categorization engine

`src/categorizer.py` provides two public functions:

**`suggest_category(transaction, db)`** — returns `(category_id, confidence, source)` without writing to the database. Called at import time to pre-fill the review queue.

**`confirm_category(transaction, category_id, db)`** — assigns the confirmed category, clears suggestion columns, and triggers background ML retraining.

Three strategies in order:

1. **Keyword matching** — `match_by_keywords()` with specificity ordering, normalization, and negative keyword support
2. **History matching** — `match_by_history()` requires ≥3 examples and ≥80% agreement
3. **ML model** — `CategorizationModel` using TF-IDF + Logistic Regression, serialized to `data/categorizer_model.pkl`

The ML model retrains in a background thread after each confirmation so responses stay fast.

See [Categorization Algorithm](categorization.md) for the full technical writeup.

---

## Budget month override

The `budget_month` column on Transaction enables accrual-style attribution. All four spending aggregation functions in `services/aggregations.py` use a SQLAlchemy CASE expression:

```python
effective_date = case(
    (Transaction.budget_month != None, Transaction.budget_month),
    else_=Transaction.date,
)
```

This means `COALESCE(budget_month, date)` is used for all month filtering on the budget page. The transactions page always uses the real date.

---

## Sign conventions

- Expense amounts are **negative** (debits)
- Income amounts are **positive** (credits)
- `get_total_expenses()` returns a **negative** float
- Budget page uses `abs()` for display; template context carries signed values
- Split children are `excluded=True`, `parent_id` set; parents are `is_split=True`

---

## Migrations

Database schema changes use Alembic. All migrations use the SQLite-safe pattern — no FK constraints in `op.add_column()`, with defensive `PRAGMA table_info` checks:

```python
def upgrade() -> None:
    conn = op.get_bind()
    existing = [row[1] for row in conn.execute(sa.text("PRAGMA table_info(transactions)"))]
    if "new_column" not in existing:
        op.add_column("transactions", sa.Column("new_column", sa.String(), nullable=True))
```

To apply migrations: `alembic upgrade head`
To check current version: `alembic current`

---

## Testing

```bash
pytest tests/ -v
pytest tests/ --cov=src --cov-report=term-missing
```

Tests use `StaticPool` in-memory SQLite. The `conftest.py` provides `db` (raw session) and `client` (FastAPI TestClient) fixtures. Route tests that do delete+insert use `db.expire_all()` after mutations.

Key fixture notes:

- Mock `routers.imports.load_exclude_keywords` (not `main.load_exclude_keywords`)
- `categorizer.load_keywords` is mocked via `patch("categorizer.load_keywords", return_value=...)`

---

## CI/CD

- **GitHub Actions** — runs tests on every push and PR (`.github/workflows/tests.yml`)
- **GitLab CI** — lint + test with 90% coverage gate (`.gitlab-ci.yml`)
- **GitHub Pages** — MkDocs docs deployed via `.github/workflows/docs.yml`

---

## Adding a new page

1. Create a template in `src/templates/` extending `base.html`
2. Add a route in `src/routers/pages.py`
3. Add a nav link in `src/templates/base.html`
4. Create `src/static/js/yourpage.js` for any page-specific JS
5. Add a docs page in `docs/` and update `mkdocs.yml`

---

## Key dependencies

| Package | Purpose |
|---|---|
| `fastapi` | Web framework and API |
| `uvicorn` | ASGI server |
| `sqlalchemy` | ORM and database abstraction |
| `alembic` | Database migrations |
| `jinja2` | HTML templating |
| `scikit-learn` | ML categorization model |
| `joblib` | Model serialization |
| `scipy` | Sparse matrix support for TF-IDF |
| `python-multipart` | Form/file upload parsing |
| `pydantic` | Request/response validation |
| `pytest` / `pytest-cov` | Test runner and coverage |
