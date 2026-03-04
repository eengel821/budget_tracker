# Budget Tracker

A personal budget tracking application built with Python, FastAPI, SQLite, and SQLAlchemy.

## TODO Task List
- [X] Automatically exclude CC pmt transactions
- [ ] change color of the exclude payments option from yellow to something easier to read
- [ ] verify with a new import for all of february. make sure i don't get dupes and nothing gets missed
- [ ] add a text based keyword filter on the transactions page
- [ ] more testing and doc strings
- [ ] github testing pipelines
- [ ] deployment?

## What it does

Budget Tracker allows you to:

- **Import transactions** from CSV exports from Chase, Capital One, BECU, and Discover
- **Auto-categorize transactions** using keyword matching and history-based learning
- **Review and manually categorize** any transactions the auto-categorizer couldn't match
- **Track spending vs budget** by category for any month
- **Visualize spending** with charts and category breakdowns
- **Manage categories and budgets** directly from the browser

## Quick start

1. Follow the [Setup & Installation](setup.md) guide to get the app running
2. Export a CSV from your bank and follow the [CSV Import Guide](importing.md)
3. Run auto-categorization and review uncategorized transactions using the [Categorization Guide](categories.md)
4. Set your monthly budget amounts following the [Budget Management](budget.md) guide

## Application pages

| Page | URL | Description |
|---|---|---|
| Dashboard | `/` | Monthly summary, charts, and recent transactions |
| Transactions | `/transactions` | Full transaction list with filters and inline editing |
| Review Queue | `/review` | Uncategorized transactions awaiting categorization |
| Budget | `/budget` | Budget vs actual spending comparison |
| Categories | `/categories` | Spending breakdown by category with doughnut chart |
| Manage Budgets | `/budget/manage` | Set and update monthly budget amounts |
| API Docs | `/docs` | Auto-generated FastAPI interactive API documentation |

## Tech stack

- **Python 3.12+**
- **FastAPI** — web framework and API
- **SQLAlchemy** — database ORM
- **SQLite** — local database
- **Jinja2** — HTML templating
- **Bootstrap 5** — UI styling
- **Chart.js** — charts and visualizations
- **pytest** — testing
