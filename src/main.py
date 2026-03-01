"""
main.py - FastAPI application with HTML frontend and API endpoints.

Serves Jinja2 HTML templates for the browser interface and JSON endpoints
for the review queue's JavaScript category assignment.
"""

from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Optional
import sys

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy import extract, func
from sqlalchemy.orm import Session

# Ensure src/ is on the path
src_path = Path(__file__).resolve().parent
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from database import init_db, get_db
from models import Transaction, Category, Account
from categorizer import categorize_all_uncategorized


# ── App setup ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _run_backup()
    yield

app = FastAPI(title="Budget Tracker", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=src_path / "static"), name="static")
templates = Jinja2Templates(directory=src_path / "templates")


# ── Request models ───────────────────────────────────────────────────────────

class CategoryAssignment(BaseModel):
    category_id: int

class BudgetUpdate(BaseModel):
    monthly_budget: float

class CategoryCreate(BaseModel):
    name: str
    monthly_budget: float = 0.0

class TransactionPatch(BaseModel):
    description: Optional[str] = None
    notes: Optional[str] = None


# ── Helper functions ─────────────────────────────────────────────────────────

def _run_backup():
    """
    Create a database backup on startup.
    Skips if a backup was already created within the last 60 seconds
    to prevent multiple backups when uvicorn --reload restarts workers.
    Errors are caught and logged but do not prevent the app from starting.
    """
    try:
        backup_script = src_path.parent / "backup_db.py"
        if not backup_script.exists():
            print("Warning: backup_db.py not found — skipping startup backup")
            return

        # Check if a backup was created recently
        backup_dir = src_path.parent / "backups"
        if backup_dir.exists():
            existing = sorted(backup_dir.glob("budget_*.db"))
            if existing:
                latest = existing[-1]
                age_seconds = (datetime.now() - datetime.fromtimestamp(latest.stat().st_mtime)).total_seconds()
                if age_seconds < 60:
                    return  # skip silently — backup already created recently

        import subprocess
        result = subprocess.run(
            [sys.executable, str(backup_script)],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            print(f"✓ Backup created on startup")
        else:
            print(f"Warning: Backup failed — {result.stderr.strip()}")

    except Exception as e:
        print(f"Warning: Backup error — {e}")

def get_available_months(db: Session) -> list[dict]:
    """
    Return a list of months that have transactions, formatted for dropdowns.
    Each entry has a 'value' (YYYY-MM) and a 'label' (e.g. 'February 2026').
    """
    rows = db.query(
        extract("year", Transaction.date).label("year"),
        extract("month", Transaction.date).label("month"),
    ).distinct().order_by("year", "month").all()

    months = []
    for row in rows:
        year, month = int(row.year), int(row.month)
        label = datetime(year, month, 1).strftime("%B %Y")
        months.append({"value": f"{year}-{month:02d}", "label": label})
    return months


def get_current_month_str() -> str:
    """Return the current month as a YYYY-MM string."""
    today = date.today()
    return f"{today.year}-{today.month:02d}"


def parse_month(month_str: str) -> tuple[int, int]:
    """Parse a YYYY-MM string into (year, month) integers."""
    year, month = month_str.split("-")
    return int(year), int(month)


def get_month_label(month_str: str) -> str:
    """Convert a YYYY-MM string to a human-readable label like 'February 2026'."""
    year, month = parse_month(month_str)
    return datetime(year, month, 1).strftime("%B %Y")


def get_uncategorized_count(db: Session) -> int:
    """Return the total number of uncategorized transactions."""
    return db.query(Transaction).filter(Transaction.category_id.is_(None)).count()


def get_monthly_spending(db: Session, year: int, month: int):
    """
    Return aggregated spending per category for a given month.
    Only includes transactions with a negative amount (debits).
    """
    return db.query(
        Category.name.label("category_name"),
        Category.monthly_budget.label("monthly_budget"),
        func.sum(Transaction.amount).label("total"),
    ).join(Transaction, Transaction.category_id == Category.id)\
     .filter(
        extract("year", Transaction.date) == year,
        extract("month", Transaction.date) == month,
        Transaction.amount < 0,
    ).group_by(Category.id).order_by(func.sum(Transaction.amount)).all()

# ── Frontend routes ──────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), month: Optional[str] = None):
    """Render the dashboard with monthly summary stats and charts."""
    available_months = get_available_months(db)
    selected_month = month or get_current_month_str()
    year, mo = parse_month(selected_month)

    spending = get_monthly_spending(db, year, mo)

    total_spent = sum(row.total for row in spending)
    total_budgeted = sum(row.monthly_budget or 0 for row in spending)
    total_remaining = total_budgeted - abs(total_spent)

    category_labels = [row.category_name for row in spending]
    category_spent  = [abs(row.total) for row in spending]
    category_budget = [row.monthly_budget or 0 for row in spending]

    top_categories = [
        {"category": row.category_name, "spent": row.total}
        for row in sorted(spending, key=lambda r: r.total)[:5]
    ]

    recent_transactions = db.query(Transaction)\
        .filter(
            extract("year", Transaction.date) == year,
            extract("month", Transaction.date) == mo,
        ).order_by(Transaction.date.desc()).limit(10).all()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "active_page": "dashboard",
        "available_months": available_months,
        "selected_month": selected_month,
        "current_month_label": get_month_label(selected_month),
        "total_spent": total_spent,
        "total_budgeted": total_budgeted,
        "total_remaining": total_remaining,
        "category_labels": category_labels,
        "category_spent": category_spent,
        "category_budget": category_budget,
        "top_categories": top_categories,
        "recent_transactions": recent_transactions,
        "uncategorized_count": get_uncategorized_count(db),
    })


@app.get("/transactions", response_class=HTMLResponse)
def transactions_page(
    request: Request,
    db: Session = Depends(get_db),
    month: Optional[str] = None,
    account_id: Optional[str] = None,
    category_id: Optional[str] = None,
):
    """Render the transaction list with optional filters."""
    available_months = get_available_months(db)
    accounts = db.query(Account).order_by(Account.name).all()
    categories = db.query(Category).order_by(Category.name).all()

    query = db.query(Transaction)

    if month:
        year, mo = parse_month(month)
        query = query.filter(
            extract("year", Transaction.date) == year,
            extract("month", Transaction.date) == mo,
        )
    if account_id:
        query = query.filter(Transaction.account_id == int(account_id))
    if category_id == "none":
        query = query.filter(Transaction.category_id.is_(None))
    elif category_id:
        query = query.filter(Transaction.category_id == int(category_id))

    transactions = query.order_by(Transaction.date.desc()).all()
    total_spent = sum(t.amount for t in transactions if t.amount < 0)
    total_income = sum(t.amount for t in transactions if t.amount > 0)
    net_total = total_income + total_spent

    return templates.TemplateResponse("transactions.html", {
        "request": request,
        "active_page": "transactions",
        "transactions": transactions,
        "accounts": accounts,
        "categories": categories,
        "available_months": available_months,
        "selected_month": month or "",
        "selected_account": account_id or "",
        "selected_category": category_id or "",
        "total_count": len(transactions),
        "total_spent": total_spent,
        "total_income": total_income,
        "net_total": net_total,
        "uncategorized_count": get_uncategorized_count(db),
    })


@app.get("/review", response_class=HTMLResponse)
def review_page(request: Request, db: Session = Depends(get_db), message: Optional[str] = None):
    """Render the uncategorized transaction review queue."""
    transactions = db.query(Transaction)\
        .filter(Transaction.category_id.is_(None))\
        .order_by(Transaction.date.desc()).all()

    categories = db.query(Category).order_by(Category.name).all()

    return templates.TemplateResponse("review.html", {
        "request": request,
        "active_page": "review",
        "transactions": transactions,
        "categories": categories,
        "uncategorized_count": len(transactions),
        "message": message,
    })


@app.get("/budget", response_class=HTMLResponse)
def budget_page(request: Request, db: Session = Depends(get_db), month: Optional[str] = None):
    """Render the budget vs actual comparison page."""
    available_months = get_available_months(db)
    selected_month = month or get_current_month_str()
    year, mo = parse_month(selected_month)

    spending = get_monthly_spending(db, year, mo)

    all_categories = db.query(Category)\
        .filter(Category.monthly_budget > 0)\
        .order_by(Category.name).all()

    spent_by_cat = {row.category_name: row.total for row in spending}

    budget_rows = []
    for cat in all_categories:
        spent = abs(spent_by_cat.get(cat.name, 0))
        budgeted = cat.monthly_budget or 0
        remaining = budgeted - spent
        pct_used = (spent / budgeted * 100) if budgeted > 0 else 0
        budget_rows.append({
            "category": cat.name,
            "budgeted": budgeted,
            "spent": spent,
            "remaining": remaining,
            "pct_used": pct_used,
        })

    total_budgeted = sum(r["budgeted"] for r in budget_rows)
    total_spent = sum(r["spent"] for r in budget_rows)
    total_remaining = total_budgeted - total_spent

    return templates.TemplateResponse("budget.html", {
        "request": request,
        "active_page": "budget",
        "available_months": available_months,
        "selected_month": selected_month,
        "current_month_label": get_month_label(selected_month),
        "budget_rows": budget_rows,
        "budget_labels": [r["category"] for r in budget_rows],
        "budget_amounts": [r["budgeted"] for r in budget_rows],
        "spent_amounts": [r["spent"] for r in budget_rows],
        "total_budgeted": total_budgeted,
        "total_spent": total_spent,
        "total_remaining": total_remaining,
        "uncategorized_count": get_uncategorized_count(db),
    })


@app.get("/budget/manage", response_class=HTMLResponse)
def budget_manage_page(
    request: Request,
    db: Session = Depends(get_db),
    message: Optional[str] = None,
):
    """Render the budget management page for editing category budget amounts."""
    categories = db.query(Category).order_by(Category.name).all()
    total_budgeted = sum(c.monthly_budget or 0 for c in categories)
    return templates.TemplateResponse("budget_manage.html", {
        "request": request,
        "active_page": "budget",
        "categories": categories,
        "total_budgeted": total_budgeted,
        "uncategorized_count": get_uncategorized_count(db),
        "message": message,
    })


@app.get("/categories", response_class=HTMLResponse)
def categories_page(request: Request, db: Session = Depends(get_db), month: Optional[str] = None):
    """Render the category breakdown page with doughnut chart."""
    available_months = get_available_months(db)
    selected_month = month or get_current_month_str()
    year, mo = parse_month(selected_month)

    spending = get_monthly_spending(db, year, mo)
    total_spent = sum(row.total for row in spending)

    category_rows = []
    for row in spending:
        pct = (abs(row.total) / abs(total_spent) * 100) if total_spent else 0
        category_rows.append({"category": row.category_name, "spent": row.total, "pct": pct})

    return templates.TemplateResponse("categories.html", {
        "request": request,
        "active_page": "categories",
        "available_months": available_months,
        "selected_month": selected_month,
        "current_month_label": get_month_label(selected_month),
        "category_rows": category_rows,
        "category_labels": [r["category"] for r in category_rows],
        "category_values": [abs(r["spent"]) for r in category_rows],
        "total_spent": total_spent,
        "uncategorized_count": get_uncategorized_count(db),
    })


# ── API routes ───────────────────────────────────────────────────────────────

@app.get("/api/transactions")
def get_transactions(db: Session = Depends(get_db)):
    """Return all transactions as JSON."""
    return db.query(Transaction).order_by(Transaction.date.desc()).all()


@app.get("/api/transactions/uncategorized")
def get_uncategorized(db: Session = Depends(get_db)):
    """Return all uncategorized transactions as JSON."""
    return db.query(Transaction).filter(
        Transaction.category_id.is_(None)
    ).order_by(Transaction.date.desc()).all()


@app.put("/transactions/{transaction_id}/category")
def assign_category(
    transaction_id: int,
    body: CategoryAssignment,
    db: Session = Depends(get_db),
):
    """Assign or override the category on a transaction."""
    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")

    category = db.query(Category).filter(Category.id == body.category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    transaction.category_id = body.category_id
    db.commit()

    return {
        "message": f"Category '{category.name}' assigned",
        "transaction_id": transaction_id,
        "category_id": category.id,
        "category_name": category.name,
    }


@app.patch("/api/transactions/{transaction_id}")
def patch_transaction(
    transaction_id: int,
    body: TransactionPatch,
    db: Session = Depends(get_db),
):
    """Update the description or notes on a transaction."""
    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")

    if body.description is not None:
        transaction.description = body.description
    if body.notes is not None:
        transaction.notes = body.notes

    db.commit()
    db.refresh(transaction)

    return {
        "message": "Transaction updated",
        "transaction_id": transaction_id,
        "description": transaction.description,
        "notes": transaction.notes,
    }


@app.delete("/api/transactions/{transaction_id}")
def delete_transaction(
    transaction_id: int,
    db: Session = Depends(get_db),
):
    """Permanently delete a transaction by ID."""
    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")

    db.delete(transaction)
    db.commit()

    return {"message": f"Transaction {transaction_id} deleted"}


@app.post("/categorize-all")
def categorize_all(db: Session = Depends(get_db)):
    """Run auto-categorization then redirect to review page."""
    result = categorize_all_uncategorized(db)
    message = (
        f"Auto-categorized {result['auto_assigned']} transactions. "
        f"{result['needs_review']} still need review."
    )
    return RedirectResponse(url=f"/review?message={message}", status_code=303)


@app.get("/api/categories")
def get_categories(db: Session = Depends(get_db)):
    """Return all categories as JSON."""
    return db.query(Category).order_by(Category.name).all()


@app.post("/api/categories")
def create_category(
    body: CategoryCreate,
    db: Session = Depends(get_db),
):
    """Create a new category. Returns 409 if name already exists."""
    existing = db.query(Category).filter(Category.name == body.name).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Category '{body.name}' already exists")

    category = Category(name=body.name, monthly_budget=body.monthly_budget)
    db.add(category)
    db.commit()
    db.refresh(category)

    return {
        "id": category.id,
        "name": category.name,
        "monthly_budget": category.monthly_budget,
    }


@app.put("/api/categories/{category_id}/budget")
def update_category_budget(
    category_id: int,
    body: BudgetUpdate,
    db: Session = Depends(get_db),
):
    """Update the monthly budget amount for a single category."""
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    category.monthly_budget = body.monthly_budget
    db.commit()

    return {
        "message": f"Budget updated for '{category.name}'",
        "category_id": category.id,
        "monthly_budget": category.monthly_budget,
    }
