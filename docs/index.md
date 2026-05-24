# Budget Tracker

A personal finance tracking application built with Python, FastAPI, SQLite, and Bootstrap 5. Runs locally on your machine — your data never leaves your computer.

---

## What it does

- **Import transactions** from CSV exports from Chase, Capital One, BECU, Discover, and ETrade
- **Auto-categorize** using keyword rules, transaction history, and a machine learning model that improves over time
- **Review and confirm** suggested categories before they're saved — you stay in control
- **Track spending vs budget** by category for any month, with credit/refund handling and budget month overrides
- **Savings jar tracking** — allocate savings transactions across named jars and track balances
- **Split transactions** across multiple categories when a single charge covers more than one budget line
- **Visualize spending** with trend charts and category breakdowns
- **Automatic backups** on every startup

---

## Quick start

1. Follow the [Setup & Installation](setup.md) guide to get the app running
2. Export a CSV from your bank and follow the [Importing Transactions](importing.md) guide
3. Review and confirm suggested categories in the [Review Queue](review.md)
4. Set your monthly budget amounts from the Budget page
5. See how you're tracking against your budget on the [Budget Page](budget.md)

---

## Application pages

| Page | URL | Description |
|---|---|---|
| Dashboard | `/` | Monthly summary, stat tiles, and savings overview |
| Transactions | `/transactions` | Full transaction list with filters and inline editing |
| Review Queue | `/review` | Confirm or correct categorization suggestions |
| Budget | `/budget` | Budget vs actual spending comparison by month |
| Savings | `/savings` | Savings account ledger and jar allocation |
| Categories | `/categories` | Spending trend charts by category |
| Manage Budgets | `/budget/manage` | Set monthly budget amounts per category |
| API Docs | `/docs` | Auto-generated FastAPI interactive API documentation |

---

## Tech stack

| Component | Technology |
|---|---|
| Web framework | FastAPI |
| Database | SQLite via SQLAlchemy |
| Templating | Jinja2 |
| UI | Bootstrap 5.3, Bootstrap Icons |
| Charts | Chart.js 4.4 |
| ML categorization | scikit-learn (TF-IDF + Logistic Regression) |
| Migrations | Alembic |
| Tests | pytest (93% coverage, 374 tests) |
| Docs | MkDocs Material |
