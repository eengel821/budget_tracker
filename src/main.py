"""
main.py - FastAPI application with HTML frontend and API endpoints.

Serves Jinja2 HTML templates for the browser interface and JSON endpoints
for the review queue's JavaScript category assignment.
"""

import csv
import io
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Optional
import sys

from fastapi import FastAPI, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
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
from import_transactions import import_csv, load_formats, load_exclude_keywords


# ── App setup ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
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

class CategoryRename(BaseModel):
    name: str

class TransactionPatch(BaseModel):
    description: Optional[str] = None
    notes: Optional[str] = None


# ── Helper functions ─────────────────────────────────────────────────────────

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
    """Return the total number of uncategorized non-excluded transactions."""
    return db.query(Transaction).filter(
        Transaction.category_id.is_(None),
        Transaction.excluded == False,
    ).count()


def get_monthly_spending(db: Session, year: int, month: int):
    """
    Return aggregated spending per category for a given month.
    Sums ALL transaction amounts for non-income categories (debits and credits).
    Refunds/credits in expense categories reduce the net total correctly.
    Excludes income categories and excluded transactions.
    """
    return db.query(
        Category.name.label("category_name"),
        Category.monthly_budget.label("monthly_budget"),
        func.sum(Transaction.amount).label("total"),
    ).join(Transaction, Transaction.category_id == Category.id)     .filter(
        extract("year",  Transaction.date) == year,
        extract("month", Transaction.date) == month,
        Transaction.excluded == False,
        Category.is_income == False,
    ).group_by(Category.id).order_by(func.sum(Transaction.amount)).all()


def get_monthly_income(db: Session, year: int, month: int):
    """
    Return aggregated income per category for a given month.
    Only counts positive transactions in is_income categories.
    """
    return db.query(
        Category.name.label("category_name"),
        Category.monthly_budget.label("monthly_budget"),
        func.sum(Transaction.amount).label("total"),
    ).join(Transaction, Transaction.category_id == Category.id)     .filter(
        extract("year",  Transaction.date) == year,
        extract("month", Transaction.date) == month,
        Transaction.amount > 0,
        Transaction.excluded == False,
        Category.is_income == True,
    ).group_by(Category.id).order_by(func.sum(Transaction.amount).desc()).all()


def get_total_expenses(db: Session, year: int, month: int) -> float:
    """
    Total expenses for a month: sum of ALL transactions in non-income
    categories plus uncategorized transactions (excluded never counted).
    Returns a negative number representing net outflow.
    """
    categorized = db.query(func.sum(Transaction.amount))        .join(Category, Transaction.category_id == Category.id)        .filter(
            extract("year",  Transaction.date) == year,
            extract("month", Transaction.date) == month,
            Transaction.excluded == False,
            Category.is_income == False,
        ).scalar() or 0

    uncategorized = db.query(func.sum(Transaction.amount))        .filter(
            extract("year",  Transaction.date) == year,
            extract("month", Transaction.date) == month,
            Transaction.excluded == False,
            Transaction.category_id.is_(None),
        ).scalar() or 0

    return categorized + uncategorized


def get_total_income(db: Session, year: int, month: int) -> float:
    """
    Total income for a month: sum of positive transactions in
    is_income categories only. Excluded transactions never counted.
    """
    return db.query(func.sum(Transaction.amount))        .join(Category, Transaction.category_id == Category.id)        .filter(
            extract("year",  Transaction.date) == year,
            extract("month", Transaction.date) == month,
            Transaction.amount > 0,
            Transaction.excluded == False,
            Category.is_income == True,
        ).scalar() or 0


# ── Frontend routes ──────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db), month: Optional[str] = None):
    """Render the dashboard with monthly summary stats and charts."""
    available_months = get_available_months(db)
    selected_month = month or (available_months[-1]["value"] if available_months else get_current_month_str())
    year, mo = parse_month(selected_month)

    spending        = get_monthly_spending(db, year, mo)
    total_spent     = get_total_expenses(db, year, mo)
    total_income    = get_total_income(db, year, mo)
    total_budgeted  = db.query(func.sum(Category.monthly_budget))        .filter(Category.is_income == False)        .scalar() or 0
    total_remaining = total_budgeted - abs(total_spent)
    net_total       = total_income + total_spent  # total_spent is negative

    category_labels = [row.category_name for row in spending]
    category_spent  = [abs(row.total)     for row in spending]
    category_budget = [row.monthly_budget or 0 for row in spending]

    top_categories = [
        {"category": row.category_name, "spent": row.total}
        for row in sorted(spending, key=lambda r: r.total)[:5]
    ]

    recent_transactions = db.query(Transaction)        .filter(
            extract("year",  Transaction.date) == year,
            extract("month", Transaction.date) == mo,
            Transaction.excluded == False,
        ).order_by(Transaction.date.desc()).limit(10).all()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "active_page": "dashboard",
        "available_months": available_months,
        "selected_month": selected_month,
        "current_month_label": get_month_label(selected_month),
        "total_spent": total_spent,
        "total_income": total_income,
        "total_budgeted": total_budgeted,
        "total_remaining": total_remaining,
        "net_total": net_total,
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
    show_excluded: Optional[str] = None,
    keyword: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    """Render the transaction list with optional filters."""
    show_excluded_param = show_excluded
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
    if keyword:
        query = query.filter(Transaction.description.ilike(f"%{keyword}%"))
    if date_from:
        query = query.filter(Transaction.date >= date_from)
    if date_to:
        query = query.filter(Transaction.date <= date_to)

    show_excluded = show_excluded_param == "1"
    if not show_excluded:
        query = query.filter(Transaction.excluded == False)

    transactions = query.order_by(Transaction.date.desc()).all()

    # Expenses: all transactions in non-income or uncategorized
    # Income: only positive transactions in is_income categories
    income_cat_ids = {
        c.id for c in db.query(Category).filter(Category.is_income == True).all()
    }
    total_spent = sum(
        t.amount for t in transactions
        if t.category_id is None or t.category_id not in income_cat_ids
    )
    total_income = sum(
        t.amount for t in transactions
        if t.amount > 0 and t.category_id in income_cat_ids
    )
    net_total = total_income + total_spent  # total_spent is negative

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
        "selected_keyword": keyword or "",
        "selected_date_from": date_from or "",
        "selected_date_to": date_to or "",
        "show_excluded": show_excluded,
        "total_count": len(transactions),
        "total_spent": total_spent,
        "total_income": total_income,
        "net_total": net_total,
        "uncategorized_count": get_uncategorized_count(db),
    })


@app.get("/transactions/download")
def download_transactions(
    db: Session = Depends(get_db),
    month: Optional[str] = None,
    account_id: Optional[str] = None,
    category_id: Optional[str] = None,
    keyword: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    """Download the current filtered transaction view as a CSV file."""
    query = db.query(Transaction).filter(Transaction.excluded == False)

    if month:
        year, mo = parse_month(month)
        query = query.filter(
            extract("year",  Transaction.date) == year,
            extract("month", Transaction.date) == mo,
        )
    if account_id:
        query = query.filter(Transaction.account_id == int(account_id))
    if category_id == "none":
        query = query.filter(Transaction.category_id.is_(None))
    elif category_id:
        query = query.filter(Transaction.category_id == int(category_id))
    if keyword:
        query = query.filter(Transaction.description.ilike(f"%{keyword}%"))
    if date_from:
        query = query.filter(Transaction.date >= date_from)
    if date_to:
        query = query.filter(Transaction.date <= date_to)

    transactions = query.order_by(Transaction.date.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Description", "Category", "Account", "Debit", "Credit", "Notes"])
    for t in transactions:
        debit  = f"{abs(t.amount):.2f}" if t.amount < 0 else ""
        credit = f"{t.amount:.2f}"      if t.amount > 0 else ""
        writer.writerow([
            t.date,
            t.description,
            t.category.name if t.category else "",
            t.account.name  if t.account  else "",
            debit,
            credit,
            t.notes or "",
        ])

    output.seek(0)
    filename = f"transactions_{month or 'all'}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.get("/review", response_class=HTMLResponse)
def review_page(request: Request, db: Session = Depends(get_db), message: Optional[str] = None):
    """Render the uncategorized transaction review queue."""
    transactions = db.query(Transaction)\
        .filter(
            Transaction.category_id.is_(None),
            Transaction.excluded == False,
        )\
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
    selected_month = (month or available_months[-1]["value"]) if available_months else get_current_month_str()
    year, mo = parse_month(selected_month)

    spending = get_monthly_spending(db, year, mo)
    income   = get_monthly_income(db, year, mo)

    spent_by_cat  = {row.category_name: row.total for row in spending}
    income_by_cat = {row.category_name: row.total for row in income}

    all_categories = db.query(Category).order_by(Category.name).all()

    expense_rows = []
    income_rows  = []

    for cat in all_categories:
        budgeted = cat.monthly_budget or 0
        if cat.is_income:
            actual = income_by_cat.get(cat.name, 0)
        else:
            net    = spent_by_cat.get(cat.name, 0)
            actual = -net if net < 0 else 0
        if budgeted == 0 and actual == 0:
            continue
        pct_used  = (actual / budgeted * 100) if budgeted > 0 else None
        remaining = budgeted - actual
        row = {
            "id":        cat.id,
            "category":  cat.name,
            "budgeted":  budgeted,
            "spent":     actual,
            "remaining": remaining,
            "pct_used":  pct_used,
        }
        if cat.is_income:
            income_rows.append(row)
        else:
            expense_rows.append(row)

    # Unassigned bucket — uncategorized non-excluded expense transactions
    unassigned_txns = db.query(Transaction).filter(
        extract("year",  Transaction.date) == year,
        extract("month", Transaction.date) == mo,
        Transaction.category_id.is_(None),
        Transaction.excluded == False,
    ).all()
    unassigned_total = abs(sum(t.amount for t in unassigned_txns if t.amount < 0))
    if unassigned_total > 0:
        expense_rows.append({
            "id":        None,
            "category":  "Unassigned",
            "budgeted":  0,
            "spent":     unassigned_total,
            "remaining": -unassigned_total,
            "pct_used":  None,
        })

    # Split expense_rows into monthly (budget > 0) and savings (budget == 0)
    monthly_rows = [r for r in expense_rows if r["category"] != "Unassigned" and r["budgeted"] > 0]
    savings_rows_base = [r for r in expense_rows if r["category"] != "Unassigned" and r["budgeted"] == 0]

    # For savings: always show ALL non-income zero-budget categories
    all_savings_cats = db.query(Category)        .filter(Category.is_income == False, Category.monthly_budget == 0)        .order_by(Category.name).all()
    savings_spent_map = {r["category"]: r["spent"] for r in savings_rows_base}
    savings_rows = []
    for cat in all_savings_cats:
        spent = savings_spent_map.get(cat.name, 0)
        savings_rows.append({
            "id":       cat.id,
            "category": cat.name,
            "budgeted": 0,
            "spent":    spent,
        })

    # Unassigned goes into monthly group
    unassigned = next((r for r in expense_rows if r["category"] == "Unassigned"), None)
    if unassigned:
        monthly_rows.append(unassigned)

    total_budgeted      = db.query(func.sum(Category.monthly_budget)).filter(Category.is_income == False).scalar() or 0
    total_income        = get_total_income(db, year, mo)

    # Use row sums so footer totals always match section subtotals
    monthly_total_spent = sum(r["spent"] for r in monthly_rows)
    savings_total_spent = sum(r["spent"] for r in savings_rows)
    total_spent         = monthly_total_spent + savings_total_spent
    total_remaining     = total_budgeted - total_spent  # budgeted minus all actual spending
    net_total           = total_income - total_spent

    # Chart data — monthly uses green/red, savings uses orange (no budget bar)
    monthly_labels  = [r["category"] for r in monthly_rows]
    monthly_budgets = [r["budgeted"]  for r in monthly_rows]
    monthly_spent   = [r["spent"]     for r in monthly_rows]
    savings_labels  = [r["category"]  for r in savings_rows if r["spent"] > 0]
    savings_spent   = [r["spent"]     for r in savings_rows if r["spent"] > 0]

    return templates.TemplateResponse("budget.html", {
        "request": request,
        "active_page": "budget",
        "available_months": available_months,
        "selected_month": selected_month,
        "current_month_label": get_month_label(selected_month),
        "monthly_rows":         monthly_rows,
        "savings_rows":         savings_rows,
        "income_rows":          income_rows,
        "monthly_labels":       monthly_labels,
        "monthly_budgets":      monthly_budgets,
        "monthly_spent":        monthly_spent,
        "savings_labels":       savings_labels,
        "savings_spent":        savings_spent,
        "income_labels":        [r["category"] for r in income_rows],
        "income_budgets":       [r["budgeted"]  for r in income_rows],
        "income_spent":         [r["spent"]     for r in income_rows],
        "total_budgeted":       total_budgeted,
        "total_spent":          total_spent,
        "total_remaining":      total_remaining,
        "total_income":         total_income,
        "net_total":            net_total,
        "monthly_total_spent":  monthly_total_spent,
        "savings_total_spent":  savings_total_spent,
        "uncategorized_count":  get_uncategorized_count(db),
    })


@app.get("/budget/manage", response_class=HTMLResponse)
def budget_manage_page(
    request: Request,
    db: Session = Depends(get_db),
    message: Optional[str] = None,
):
    """Render the budget management page for editing category budget amounts."""
    categories = db.query(Category).order_by(Category.name).all()
    total_budgeted_expenses = sum(c.monthly_budget or 0 for c in categories if not c.is_income)
    total_budgeted_income   = sum(c.monthly_budget or 0 for c in categories if c.is_income)
    return templates.TemplateResponse("budget_manage.html", {
        "request": request,
        "active_page": "budget",
        "categories": categories,
        "total_budgeted_expenses": total_budgeted_expenses,
        "total_budgeted_income":   total_budgeted_income,
        "uncategorized_count": get_uncategorized_count(db),
        "message": message,
    })


@app.get("/categories", response_class=HTMLResponse)
def categories_page(request: Request, db: Session = Depends(get_db), month: Optional[str] = None):
    """Render the category breakdown page with doughnut chart."""
    available_months = get_available_months(db)
    selected_month = month or (available_months[-1]["value"] if available_months else get_current_month_str())
    year, mo = parse_month(selected_month)

    spending     = get_monthly_spending(db, year, mo)
    spent_by_cat = {row.category_name: row.total for row in spending}
    total_spent  = sum(row.total for row in spending)

    # All non-income categories — include zero-spend ones in the table
    all_expense_cats = db.query(Category)        .filter(Category.is_income == False)        .order_by(Category.name).all()

    category_rows = []
    for cat in all_expense_cats:
        net   = spent_by_cat.get(cat.name, 0)
        spent = -net if net < 0 else 0
        pct   = (spent / abs(total_spent) * 100) if total_spent else 0
        category_rows.append({"category": cat.name, "spent": spent, "pct": pct})

    # Chart only includes categories with actual spending
    chart_rows = [r for r in category_rows if r["spent"] > 0]

    return templates.TemplateResponse("categories.html", {
        "request": request,
        "active_page": "categories",
        "available_months": available_months,
        "selected_month": selected_month,
        "current_month_label": get_month_label(selected_month),
        "category_rows": category_rows,
        "category_labels": [r["category"] for r in chart_rows],
        "category_values": [r["spent"]    for r in chart_rows],
        "total_spent": abs(total_spent),
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


@app.post("/api/import")
async def import_transactions_endpoint(
    file: UploadFile = File(...),
    bank: str = Form(...),
    db: Session = Depends(get_db),
):
    """
    Accept a CSV file upload and import transactions for the given bank.
    Returns a JSON summary: imported, auto_excluded, duplicates_skipped, skipped.
    """
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported")

    # Load formats from project root
    formats_path = src_path.parent / "formats.json"
    if not formats_path.exists():
        raise HTTPException(status_code=500, detail="formats.json not found on server")

    import json, tempfile, os
    with open(formats_path) as f:
        formats = json.load(f)

    if bank not in formats:
        raise HTTPException(status_code=400, detail=f"Unknown bank '{bank}'. Available: {', '.join(formats.keys())}")

    # Write upload to a temp file so import_csv can read it
    contents = await file.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        tmp.write(contents)
        tmp_path = Path(tmp.name)

    try:
        fmt         = formats[bank]
        exclude_kws = load_exclude_keywords()

        import csv as csvlib
        from datetime import datetime as dt

        def parse_amount_inline(row):
            if fmt["amount_col"]:
                return float(row[fmt["amount_col"]])
            else:
                debit  = row[fmt["debit_col"]].strip()
                credit = row[fmt["credit_col"]].strip()
                if debit:  return -abs(float(debit))
                if credit: return  abs(float(credit))
                return 0.0

        def parse_date_inline(row):
            return dt.strptime(row[fmt["date_col"]].strip(), fmt["date_format"]).date()

        # Get or create account
        from models import Account
        account = db.query(Account).filter(Account.name == bank).first()
        if not account:
            account = Account(name=bank, type="imported")
            db.add(account)
            db.commit()
            db.refresh(account)

        imported = skipped = auto_excluded = duplicates_skipped = 0

        with open(tmp_path, newline="", encoding="utf-8-sig") as csvfile:
            reader = csvlib.DictReader(csvfile)
            reader.fieldnames = [f.strip().strip('"') for f in reader.fieldnames]

            for row in reader:
                row = {k: v.strip().strip('"') for k, v in row.items()}
                if not row.get(fmt["date_col"], "").strip():
                    skipped += 1
                    continue
                try:
                    txn_date   = parse_date_inline(row)
                    amount     = parse_amount_inline(row)
                    desc       = row[fmt["description_col"]].strip()
                    cat_note   = row.get(fmt.get("category_col") or "", "").strip()
                except (ValueError, KeyError):
                    skipped += 1
                    continue

                # Duplicate check
                exists = db.query(Transaction).filter(
                    Transaction.date        == txn_date,
                    Transaction.amount      == amount,
                    Transaction.description == desc,
                ).first()
                if exists:
                    duplicates_skipped += 1
                    continue

                txn = Transaction(
                    date        = txn_date,
                    amount      = amount,
                    description = desc,
                    notes       = cat_note,
                    account_id  = account.id,
                )
                if any(kw in desc.upper() for kw in exclude_kws):
                    txn.excluded  = True
                    auto_excluded += 1

                db.add(txn)
                imported += 1

        db.commit()

    finally:
        os.unlink(tmp_path)

    uncategorized = get_uncategorized_count(db)

    return {
        "imported":           imported,
        "auto_excluded":      auto_excluded,
        "duplicates_skipped": duplicates_skipped,
        "skipped":            skipped,
        "uncategorized_count": uncategorized,
    }


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


@app.put("/api/categories/{category_id}/name")
def rename_category(
    category_id: int,
    body: CategoryRename,
    db: Session = Depends(get_db),
):
    """Rename a category. Returns 409 if the new name already exists."""
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    existing = db.query(Category).filter(
        Category.name == body.name,
        Category.id != category_id,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Category '{body.name}' already exists")

    old_name = category.name
    category.name = body.name
    db.commit()

    return {
        "message": f"Category renamed from '{old_name}' to '{body.name}'",
        "category_id": category_id,
        "name": category.name,
    }


@app.put("/api/categories/{category_id}/is_income")
def toggle_category_is_income(
    category_id: int,
    db: Session = Depends(get_db),
):
    """Toggle the is_income flag on a category."""
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    category.is_income = not category.is_income
    db.commit()
    return {
        "category_id": category_id,
        "is_income": category.is_income,
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


# ── Documentation ────────────────────────────────────────────────────────────
# Docs are hosted on GitHub Pages at:
# https://eengel821.github.io/budget_tracker/
# The GitHub Actions workflow in .github/workflows/docs.yml deploys
# automatically whenever docs/ or mkdocs.yml changes are pushed to main.


# ── Exclude / unexclude transactions ─────────────────────────────────────────

@app.put("/api/transactions/{transaction_id}/exclude")
def set_transaction_excluded(
    transaction_id: int,
    db: Session = Depends(get_db),
):
    """
    Mark a transaction as excluded from reports and budget calculations.
    Excluded transactions are hidden on the transactions page by default
    but can still be viewed using the 'show excluded' toggle.
    """
    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    transaction.excluded = True
    db.commit()
    return {"message": "Transaction excluded", "transaction_id": transaction_id}


@app.put("/api/transactions/{transaction_id}/unexclude")
def set_transaction_unexcluded(
    transaction_id: int,
    db: Session = Depends(get_db),
):
    """Re-include a previously excluded transaction in reports."""
    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    transaction.excluded = False
    db.commit()
    return {"message": "Transaction unexcluded", "transaction_id": transaction_id}