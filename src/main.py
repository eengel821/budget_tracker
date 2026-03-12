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

JAR_COLORS = [
    "#4e73df", "#1cc88a", "#36b9cc", "#f6c23e",
    "#e74a3b", "#6f42c1", "#fd7e14", "#20c997",
    "#6610f2", "#d63384",
]

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

def get_jar_balances(db: Session) -> list[dict]:
    """
    Calculate the current balance of every savings jar (is_savings=True category)
    by summing all SavingsAllocation rows for that category.
    Returns a list of dicts with: category_id, name, balance, pct, color.
    """
    from models import SavingsAllocation
    savings_cats = db.query(Category).filter(Category.is_savings == True).order_by(Category.name).all()

    results = []
    total_positive = sum(
        db.query(func.sum(SavingsAllocation.amount))
          .filter(SavingsAllocation.category_id == cat.id)
          .scalar() or 0
        for cat in savings_cats
    )
    total_abs = abs(total_positive) if total_positive else 1

    for i, cat in enumerate(savings_cats):
        balance = db.query(func.sum(SavingsAllocation.amount))\
                    .filter(SavingsAllocation.category_id == cat.id)\
                    .scalar() or 0
        balance = round(balance, 2)
        pct = round((balance / total_abs) * 100, 1) if total_abs else 0
        results.append({
            "category_id": cat.id,
            "name":        cat.name,
            "balance":     balance,
            "pct":         max(pct, 0),
            "color":       JAR_COLORS[i % len(JAR_COLORS)],
        })
    return results

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
    selected_month   = month or (available_months[-1]["value"] if available_months else get_current_month_str())
    year, mo         = parse_month(selected_month)

    # ── Selected month stats ─────────────────────────────────────────────────
    spending        = get_monthly_spending(db, year, mo)
    total_spent     = get_total_expenses(db, year, mo)
    total_income    = get_total_income(db, year, mo)
    total_budgeted  = db.query(func.sum(Category.monthly_budget))        .filter(Category.is_income == False).scalar() or 0
    total_budgeted_income = db.query(func.sum(Category.monthly_budget))        .filter(Category.is_income == True).scalar() or 0
    total_remaining = total_budgeted - abs(total_spent)
    net_total       = total_income + total_spent  # total_spent is negative

    # ── Pie chart data for selected month ────────────────────────────────────
    # Budgeted: all non-income categories with a budget
    budget_pie_cats    = db.query(Category)        .filter(Category.is_income == False, Category.monthly_budget > 0)        .order_by(Category.name).all()
    budget_pie_labels  = [c.name for c in budget_pie_cats]
    budget_pie_values  = [c.monthly_budget for c in budget_pie_cats]

    # Actual: categories with spending this month
    spent_by_cat       = {row.category_name: abs(row.total) for row in spending if row.total < 0}
    actual_pie_labels  = [k for k, v in sorted(spent_by_cat.items(), key=lambda x: -x[1]) if v > 0]
    actual_pie_values  = [spent_by_cat[k] for k in actual_pie_labels]

    # ── Last 12 months trend data ─────────────────────────────────────────────
    trend_months = available_months[-12:]
    trend_labels         = []
    trend_inc_budgeted   = []
    trend_inc_actual     = []
    trend_exp_budgeted   = []
    trend_exp_actual     = []
    trend_net_cashflow   = []

    for m in trend_months:
        y, mo2 = parse_month(m["value"])
        exp_actual  = abs(get_total_expenses(db, y, mo2))
        inc_actual  = get_total_income(db, y, mo2)
        net_cf      = inc_actual - exp_actual
        trend_labels.append(datetime(y, mo2, 1).strftime("%b %y"))
        trend_inc_budgeted.append(round(total_budgeted_income, 2))
        trend_inc_actual.append(round(inc_actual, 2))
        trend_exp_budgeted.append(round(total_budgeted, 2))
        trend_exp_actual.append(round(exp_actual, 2))
        trend_net_cashflow.append(round(net_cf, 2))

    recent_transactions = db.query(Transaction)        .filter(
            extract("year",  Transaction.date) == year,
            extract("month", Transaction.date) == mo,
            Transaction.excluded == False,
        ).order_by(Transaction.date.desc()).limit(10).all()

    # ── Savings data ─────────────────────────────────────────────────────────
    from models import SavingsTransaction
    import calendar as cal_mod

    all_savings_txns    = db.query(SavingsTransaction).all()
    savings_balance     = round(sum(t.amount for t in all_savings_txns), 2)
    jar_balances_dash   = get_jar_balances(db)
    unallocated_count   = sum(1 for t in all_savings_txns if not t.is_allocated)

    today_d = date.today()
    savings_growth_labels   = []
    savings_growth_balances = []
    for i in range(11, -1, -1):
        total_mo = today_d.year * 12 + today_d.month - i - 1
        g_yr = total_mo // 12
        g_mo = total_mo % 12 + 1
        last_day = cal_mod.monthrange(g_yr, g_mo)[1]
        cutoff   = date(g_yr, g_mo, last_day)
        bal = round(sum(t.amount for t in all_savings_txns if t.date <= cutoff), 2)
        savings_growth_labels.append(datetime(g_yr, g_mo, 1).strftime("%b %y"))
        savings_growth_balances.append(bal)

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
        "budget_pie_labels": budget_pie_labels,
        "budget_pie_values": budget_pie_values,
        "actual_pie_labels": actual_pie_labels,
        "actual_pie_values": actual_pie_values,
        "trend_labels":       trend_labels,
        "trend_inc_budgeted": trend_inc_budgeted,
        "trend_inc_actual":   trend_inc_actual,
        "trend_exp_budgeted": trend_exp_budgeted,
        "trend_exp_actual":   trend_exp_actual,
        "trend_net_cashflow": trend_net_cashflow,
        "recent_transactions": recent_transactions,
        "uncategorized_count": get_uncategorized_count(db),
        "savings_balance":          savings_balance,
        "jar_balances_dash":        jar_balances_dash,
        "unallocated_count":        unallocated_count,
        "savings_growth_labels":    savings_growth_labels,
        "savings_growth_balances":  savings_growth_balances,
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
def categories_page(request: Request, db: Session = Depends(get_db)):
    """Render the category analysis page with per-category trend charts."""
    available_months = get_available_months(db)
    last_12 = available_months[-12:]

    # All non-income categories
    all_expense_cats = db.query(Category)        .filter(Category.is_income == False)        .order_by(Category.name).all()

    total_budgeted_mo = sum(c.monthly_budget for c in all_expense_cats)
    total_cat_count   = len(all_expense_cats)

    # Build per-category spend history across last 12 months
    month_labels = []
    for m in last_12:
        y2, mo2 = parse_month(m["value"])
        month_labels.append(datetime(y2, mo2, 1).strftime("%b %y"))

    cat_rows = []
    for cat in all_expense_cats:
        monthly_spent = []
        for m in last_12:
            y2, mo2 = parse_month(m["value"])
            result = db.query(func.sum(Transaction.amount))                .filter(
                    Transaction.category_id == cat.id,
                    Transaction.excluded == False,
                    extract("year",  Transaction.date) == y2,
                    extract("month", Transaction.date) == mo2,
                )                .scalar() or 0
            monthly_spent.append(round(abs(result) if result < 0 else 0, 2))

        active = [v for v in monthly_spent if v > 0]
        avg_spent   = round(sum(active) / len(active), 2) if active else 0
        avg_budget  = cat.monthly_budget
        avg_diff    = round(avg_spent - avg_budget, 2) if avg_budget > 0 else None
        max_spent   = max(monthly_spent) if active else 0
        max_month   = month_labels[monthly_spent.index(max_spent)] if active else "—"
        active_months = len(active)

        # Over/under per month for line (None if no budget)
        over_under = [
            round(avg_budget - v, 2) if avg_budget > 0 else None
            for v in monthly_spent
        ]

        cat_rows.append({
            "id":           cat.id,
            "name":         cat.name,
            "budget":       avg_budget,
            "avg_spent":    avg_spent,
            "avg_diff":     avg_diff,
            "max_spent":    max_spent,
            "max_month":    max_month,
            "active_months": active_months,
            "monthly_spent": monthly_spent,
            "over_under":   over_under,
        })

    # Tile: most over budget (avg basis)
    budgeted_cats = [r for r in cat_rows if r["budget"] > 0]
    most_over = max(budgeted_cats, key=lambda r: r["avg_diff"] or 0) if budgeted_cats else None
    most_over_name = most_over["name"] if most_over and most_over["avg_diff"] and most_over["avg_diff"] > 0 else "None"
    most_over_amt  = most_over["avg_diff"] if most_over and most_over["avg_diff"] and most_over["avg_diff"] > 0 else 0

    # Tile: top savings draw (zero-budget category with most total spend)
    savings_cats = [r for r in cat_rows if r["budget"] == 0 and r["avg_spent"] > 0]
    top_savings = max(savings_cats, key=lambda r: r["avg_spent"]) if savings_cats else None
    top_savings_name = top_savings["name"] if top_savings else "None"
    top_savings_amt  = top_savings["avg_spent"] if top_savings else 0

    return templates.TemplateResponse("categories.html", {
        "request": request,
        "active_page": "categories",
        "total_cat_count":    total_cat_count,
        "total_budgeted_mo":  total_budgeted_mo,
        "most_over_name":     most_over_name,
        "most_over_amt":      most_over_amt,
        "top_savings_name":   top_savings_name,
        "top_savings_amt":    top_savings_amt,
        "cat_rows":           cat_rows,
        "month_labels":       month_labels,
        "uncategorized_count": get_uncategorized_count(db),
    })

@app.get("/savings", response_class=HTMLResponse)
def savings_page(
    request: Request,
    db: Session = Depends(get_db),
    keyword: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    type: Optional[str] = None,
    status: Optional[str] = None,
):
    """Render the savings account management page."""
    from models import SavingsTransaction, SavingsAllocation

    query = db.query(SavingsTransaction)

    if keyword:
        query = query.filter(SavingsTransaction.description.ilike(f"%{keyword}%"))
    if date_from:
        query = query.filter(SavingsTransaction.date >= date_from)
    if date_to:
        query = query.filter(SavingsTransaction.date <= date_to)
    if type == "deposit":
        query = query.filter(SavingsTransaction.amount > 0)
    elif type == "withdrawal":
        query = query.filter(SavingsTransaction.amount < 0)
    elif type == "interest":
        query = query.filter(SavingsTransaction.description.ilike("%interest%"))
    if status == "allocated":
        query = query.filter(SavingsTransaction.is_allocated == True)
    elif status == "unallocated":
        query = query.filter(SavingsTransaction.is_allocated == False)

    savings_transactions = query.order_by(SavingsTransaction.date.desc()).all()

    all_txns = db.query(SavingsTransaction).all()

    from datetime import date as date_type
    current_year = date_type.today().year

    deposits_ytd     = sum(t.amount for t in all_txns if t.amount > 0 and t.date.year == current_year)
    withdrawals_ytd  = abs(sum(t.amount for t in all_txns if t.amount < 0 and t.date.year == current_year))
    deposit_count    = sum(1 for t in all_txns if t.amount > 0 and t.date.year == current_year)
    withdrawal_count = sum(1 for t in all_txns if t.amount < 0 and t.date.year == current_year)
    account_balance  = round(sum(t.amount for t in all_txns), 2)

    jar_balances = get_jar_balances(db)
    jar_total    = round(sum(j["balance"] for j in jar_balances), 2)

    total_deposits    = sum(t.amount for t in savings_transactions if t.amount > 0)
    total_withdrawals = abs(sum(t.amount for t in savings_transactions if t.amount < 0))

    from models import Account as AccountModel
    savings_account = db.query(AccountModel).filter(
        AccountModel.name.ilike("%etrade%") | AccountModel.name.ilike("%savings%")
    ).first()

    return templates.TemplateResponse("savings.html", {
        "request":              request,
        "active_page":          "savings",
        "uncategorized_count":  get_uncategorized_count(db),
        "savings_transactions": savings_transactions,
        "savings_account":      savings_account,
        "jar_balances":         jar_balances,
        "account_balance":      account_balance,
        "jar_total":            jar_total,
        "deposits_ytd":         round(deposits_ytd, 2),
        "withdrawals_ytd":      round(withdrawals_ytd, 2),
        "deposit_count":        deposit_count,
        "withdrawal_count":     withdrawal_count,
        "total_deposits":       round(total_deposits, 2),
        "total_withdrawals":    round(total_withdrawals, 2),
        "selected_keyword":     keyword or "",
        "selected_date_from":   date_from or "",
        "selected_date_to":     date_to or "",
        "selected_type":        type or "",
        "selected_status":      status or "",
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

@app.put("/api/categories/{category_id}/is_savings")
def toggle_category_is_savings(
    category_id: int,
    db: Session = Depends(get_db),
):
    """Toggle the is_savings flag on a category."""
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    category.is_savings = not category.is_savings
    db.commit()
    return {
        "category_id": category_id,
        "is_savings": category.is_savings,
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

@app.post("/api/savings/transactions")
def create_savings_transaction(
    body: dict,
    db: Session = Depends(get_db),
):
    """Manually add a savings transaction."""
    from models import SavingsTransaction
    from datetime import date as date_type

    try:
        txn_date = date_type.fromisoformat(body["date"])
        amount   = float(body["amount"])
        desc     = str(body["description"]).strip()
        notes    = body.get("notes")
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid data: {e}")

    if not desc:
        raise HTTPException(status_code=400, detail="Description is required")

    txn = SavingsTransaction(
        date=txn_date, amount=amount, description=desc,
        notes=notes, is_allocated=False,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)

    return {"id": txn.id, "date": str(txn.date), "amount": txn.amount,
            "description": txn.description, "is_allocated": txn.is_allocated}

@app.delete("/api/savings/transactions/{txn_id}")
def delete_savings_transaction(txn_id: int, db: Session = Depends(get_db)):
    """Delete a savings transaction and all its allocations (cascade)."""
    from models import SavingsTransaction
    txn = db.query(SavingsTransaction).filter(SavingsTransaction.id == txn_id).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    db.delete(txn)
    db.commit()
    return {"message": f"Savings transaction {txn_id} deleted"}

@app.get("/api/savings/jars/{category_id}/history")
def get_jar_history(category_id: int, db: Session = Depends(get_db)):
    """
    Return full history for a single savings jar (category).
    Includes running balance, stats, and monthly chart data.
    """
    from models import SavingsAllocation, SavingsTransaction
    from datetime import date as date_type
    import calendar
    from datetime import datetime

    cat = db.query(Category).filter(Category.id == category_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")

    allocs = (
        db.query(SavingsAllocation)
          .join(SavingsTransaction, SavingsAllocation.savings_transaction_id == SavingsTransaction.id)
          .filter(SavingsAllocation.category_id == category_id)
          .order_by(SavingsTransaction.date.asc())
          .all()
    )

    running = 0.0
    entries = []
    for a in allocs:
        running += a.amount
        entries.append({
            "date":            str(a.savings_transaction.date),
            "description":     a.savings_transaction.description,
            "amount":          round(a.amount, 2),
            "running_balance": round(running, 2),
        })

    current_balance  = round(running, 2)
    entries_display  = list(reversed(entries))

    current_year     = date_type.today().year
    ytd_allocs       = [a for a in allocs if a.savings_transaction.date.year == current_year]
    withdrawn_ytd    = abs(sum(a.amount for a in ytd_allocs if a.amount < 0))
    deposited_ytd    = sum(a.amount for a in ytd_allocs if a.amount > 0)
    net_ytd          = deposited_ytd - withdrawn_ytd

    deposit_months = {}
    for a in allocs:
        if a.amount > 0:
            key = (a.savings_transaction.date.year, a.savings_transaction.date.month)
            deposit_months[key] = deposit_months.get(key, 0) + a.amount
    avg_deposit = round(sum(deposit_months.values()) / len(deposit_months), 2) if deposit_months else 0.0

    today          = date_type.today()
    chart_labels   = []
    chart_balances = []
    for i in range(11, -1, -1):
        total_months = today.year * 12 + today.month - i - 1
        yr  = total_months // 12
        mo  = total_months % 12 + 1
        last_day = calendar.monthrange(yr, mo)[1]
        cutoff   = date_type(yr, mo, last_day)
        bal = sum(a.amount for a in allocs if a.savings_transaction.date <= cutoff)
        chart_labels.append(datetime(yr, mo, 1).strftime("%b %y"))
        chart_balances.append(round(bal, 2))

    return {
        "category_id":    category_id,
        "name":           cat.name,
        "balance":        current_balance,
        "avg_deposit":    avg_deposit,
        "withdrawn_ytd":  round(withdrawn_ytd, 2),
        "net_ytd":        round(net_ytd, 2),
        "chart_labels":   chart_labels,
        "chart_balances": chart_balances,
        "entries":        entries_display,
    }

@app.post("/api/savings/import")
async def import_savings_transactions(
    file: UploadFile = File(...),
    bank: str = Form(...),
    db: Session = Depends(get_db),
):
    """Import savings transactions from a CSV file."""
    from models import SavingsTransaction, Account as AccountModel
    import tempfile, os, csv as csvlib
    from datetime import datetime as dt

    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported")

    SAVINGS_FORMATS = {
        "etrade": {
            "date_col":        "TransactionDate",
            "description_col": "Description",
            "amount_col":      "Amount",
            "date_format":     "%m/%d/%y",
            "header_marker":   "TransactionDate",  # skip preamble rows until this header is found
        },
        "becu": {
            "date_col":        "Date",
            "description_col": "Description",
            "amount_col":      "Amount",
            "date_format":     "%m/%d/%Y",
            "header_marker":   None,
        },
    }

    if bank not in SAVINGS_FORMATS:
        raise HTTPException(status_code=400, detail=f"Unknown bank '{bank}' for savings import")

    fmt      = SAVINGS_FORMATS[bank]
    contents = await file.read()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        tmp.write(contents)
        tmp_path = tmp.name

    try:
        account = db.query(AccountModel).filter(AccountModel.name == bank).first()
        if not account:
            account = AccountModel(name=bank, type="savings")
            db.add(account)
            db.commit()
            db.refresh(account)

        imported = skipped = duplicates_skipped = 0

        with open(tmp_path, newline="", encoding="utf-8-sig") as csvfile:
            raw_lines = csvfile.readlines()

        # Skip preamble rows if format has a header_marker
        header_marker = fmt.get("header_marker")
        if header_marker:
            start_idx = next(
                (i for i, l in enumerate(raw_lines) if l.strip().startswith(header_marker)),
                0
            )
            raw_lines = raw_lines[start_idx:]

        # Drop blank lines
        raw_lines = [l for l in raw_lines if l.strip()]

        import io
        reader = csvlib.DictReader(io.StringIO("".join(raw_lines)))

        for row in reader:
            row = {k.strip(): v.strip().strip('"') for k, v in row.items() if k}
            if not row.get(fmt["date_col"], "").strip():
                skipped += 1
                continue
            try:
                txn_date = dt.strptime(row[fmt["date_col"]].strip(), fmt["date_format"]).date()
                amount   = float(row[fmt["amount_col"]].replace(",", "").replace("$", ""))
                desc     = row[fmt["description_col"]].strip()
            except (ValueError, KeyError):
                skipped += 1
                continue

            exists = db.query(SavingsTransaction).filter(
                SavingsTransaction.date        == txn_date,
                SavingsTransaction.amount      == amount,
                SavingsTransaction.description == desc,
            ).first()
            if exists:
                duplicates_skipped += 1
                continue

            txn = SavingsTransaction(
                date=txn_date, amount=amount, description=desc,
                is_allocated=False, account_id=account.id,
            )
            db.add(txn)
            imported += 1

        db.commit()

    finally:
        os.unlink(tmp_path)

    return {
        "imported":           imported,
        "duplicates_skipped": duplicates_skipped,
        "skipped":            skipped,
    }

@app.get("/api/savings/transactions/{txn_id}/allocations")
def get_savings_allocations(txn_id: int, db: Session = Depends(get_db)):
    """
    Return existing allocations for a transaction so the modal can pre-fill.
    Also returns all savings jars with current balances for the left panel.
    """
    from models import SavingsTransaction, SavingsAllocation

    txn = db.query(SavingsTransaction).filter(SavingsTransaction.id == txn_id).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    # Current allocations for this transaction
    existing = db.query(SavingsAllocation)\
                 .filter(SavingsAllocation.savings_transaction_id == txn_id)\
                 .all()

    allocations = [
        {"category_id": a.category_id, "amount": round(a.amount, 2)}
        for a in existing
    ]

    # All savings jars with current balances for left panel reference
    jar_balances = get_jar_balances(db)

    return {
        "txn_id":      txn_id,
        "amount":      round(txn.amount, 2),
        "description": txn.description,
        "date":        str(txn.date),
        "is_allocated": txn.is_allocated,
        "allocations": allocations,
        "jars":        jar_balances,
    }


@app.put("/api/savings/transactions/{txn_id}/allocations")
def save_savings_allocations(
    txn_id: int,
    body: dict,
    db: Session = Depends(get_db),
):
    """
    Replace all allocations for a transaction with the submitted set.
    Marks the transaction as allocated if amounts balance within $0.01.
    body expects: { "allocations": [{"category_id": int, "amount": float}, ...] }
    """
    from models import SavingsTransaction, SavingsAllocation

    txn = db.query(SavingsTransaction).filter(SavingsTransaction.id == txn_id).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    raw = body.get("allocations", [])
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="allocations must be a list")

    # Validate each item
    items = []
    for item in raw:
        try:
            cat_id = int(item["category_id"])
            amount = round(float(item["amount"]), 2)
        except (KeyError, ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Each allocation needs category_id and amount")
        if amount == 0:
            continue  # skip zero rows silently
        cat = db.query(Category).filter(Category.id == cat_id, Category.is_savings == True).first()
        if not cat:
            raise HTTPException(status_code=400, detail=f"Category {cat_id} is not a savings jar")
        items.append({"category_id": cat_id, "amount": amount})

    # Delete existing allocations for this transaction
    db.query(SavingsAllocation)\
      .filter(SavingsAllocation.savings_transaction_id == txn_id)\
      .delete()

    # Insert new allocations
    for item in items:
        alloc = SavingsAllocation(
            savings_transaction_id=txn_id,
            category_id=item["category_id"],
            amount=item["amount"],
        )
        db.add(alloc)

    # Mark allocated if total matches transaction amount within $0.01
    total_allocated = round(sum(i["amount"] for i in items), 2)
    txn.is_allocated = abs(total_allocated - round(txn.amount, 2)) < 0.01

    db.commit()

    return {
        "txn_id":       txn_id,
        "is_allocated": txn.is_allocated,
        "total_allocated": total_allocated,
        "allocations":  items,
    }


@app.get("/api/savings/templates/default")
def get_default_template(db: Session = Depends(get_db)):
    """
    Return the default allocation template items for pre-filling the deposit modal.
    If no default template exists, returns an empty list.
    """
    from models import AllocationTemplate, AllocationTemplateItem

    template = db.query(AllocationTemplate)\
                 .filter(AllocationTemplate.is_default == True)\
                 .first()

    if not template:
        return {"template_id": None, "name": None, "items": []}

    items = [
        {"category_id": item.category_id, "amount": round(item.amount, 2)}
        for item in template.items
    ]

    return {
        "template_id": template.id,
        "name":        template.name,
        "items":       items,
    }


@app.put("/api/savings/templates/default")
def save_default_template(body: dict, db: Session = Depends(get_db)):
    """
    Save or update the default allocation template.
    Replaces the existing default template entirely.
    body expects: { "name": str, "items": [{"category_id": int, "amount": float}, ...] }
    """
    from models import AllocationTemplate, AllocationTemplateItem

    name  = str(body.get("name", "Default Template")).strip() or "Default Template"
    raw   = body.get("items", [])

    items = []
    for item in raw:
        try:
            cat_id = int(item["category_id"])
            amount = round(float(item["amount"]), 2)
        except (KeyError, ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Each item needs category_id and amount")
        if amount == 0:
            continue
        items.append({"category_id": cat_id, "amount": amount})

    # Find or create the default template
    template = db.query(AllocationTemplate)\
                 .filter(AllocationTemplate.is_default == True)\
                 .first()

    if template:
        template.name = name
        # Delete existing items
        db.query(AllocationTemplateItem)\
          .filter(AllocationTemplateItem.template_id == template.id)\
          .delete()
    else:
        template = AllocationTemplate(name=name, is_default=True)
        db.add(template)
        db.flush()  # get template.id

    for item in items:
        db.add(AllocationTemplateItem(
            template_id=template.id,
            category_id=item["category_id"],
            amount=item["amount"],
        ))

    db.commit()

    return {
        "template_id": template.id,
        "name":        template.name,
        "items":       items,
    }

@app.patch("/api/savings/transactions/{txn_id}")
def edit_savings_transaction(txn_id: int, body: dict, db: Session = Depends(get_db)):
    """Edit date, description, amount, and/or notes on a savings transaction."""
    from models import SavingsTransaction
    from datetime import date as date_type

    txn = db.query(SavingsTransaction).filter(SavingsTransaction.id == txn_id).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")

    try:
        if "date" in body:
            txn.date = date_type.fromisoformat(body["date"])
        if "description" in body:
            desc = str(body["description"]).strip()
            if not desc:
                raise HTTPException(status_code=400, detail="Description cannot be empty")
            txn.description = desc
        if "amount" in body:
            txn.amount = round(float(body["amount"]), 2)
        if "notes" in body:
            txn.notes = body["notes"] or None
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid data: {e}")

    db.commit()
    db.refresh(txn)

    return {
        "id":           txn.id,
        "date":         str(txn.date),
        "description":  txn.description,
        "amount":       txn.amount,
        "notes":        txn.notes,
        "is_allocated": txn.is_allocated,
    }


@app.get("/api/savings/jars")
def get_savings_jars(db: Session = Depends(get_db)):
    """Return current balance for all savings jars. Used by the rebalance modal."""
    jars = get_jar_balances(db)
    return {"jars": jars}


@app.post("/api/savings/rebalance")
def rebalance_jars(body: dict, db: Session = Depends(get_db)):
    """
    Create a $0 rebalance transaction and apply the provided allocation adjustments.
    body expects: { "allocations": [{"category_id": int, "amount": float}, ...] }
    Each amount is the *delta* (positive = add to jar, negative = remove from jar).
    The sum of all amounts must equal 0 (it's a rebalance, not a deposit/withdrawal).
    """
    from models import SavingsTransaction, SavingsAllocation
    from datetime import date as date_type

    raw = body.get("allocations", [])
    if not raw:
        raise HTTPException(status_code=400, detail="No allocations provided")

    items = []
    for item in raw:
        try:
            cat_id = int(item["category_id"])
            amount = round(float(item["amount"]), 2)
        except (KeyError, ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Each allocation needs category_id and amount")
        if amount != 0:
            items.append({"category_id": cat_id, "amount": amount})

    # Validate that deltas net to zero (rebalance doesn't change account total)
    net = round(sum(i["amount"] for i in items), 2)
    if abs(net) > 0.01:
        raise HTTPException(
            status_code=400,
            detail=f"Rebalance allocations must net to $0.00 (got {net:+.2f})"
        )

    # Create a $0 rebalance transaction
    txn = SavingsTransaction(
        date=date_type.today(),
        amount=0.0,
        description="Jar Rebalance",
        notes="Automatic rebalance",
        is_allocated=True,
    )
    db.add(txn)
    db.flush()  # get txn.id

    for item in items:
        db.add(SavingsAllocation(
            savings_transaction_id=txn.id,
            category_id=item["category_id"],
            amount=item["amount"],
        ))

    db.commit()
    db.refresh(txn)

    return {
        "id":          txn.id,
        "date":        str(txn.date),
        "description": txn.description,
        "amount":      txn.amount,
        "allocations": items,
    }


@app.get("/api/savings/summary")
def get_savings_summary(db: Session = Depends(get_db)):
    """
    Return the four stat tile values for the savings page.
    Used for live tile updates after allocation changes without a full page reload.
    """
    from models import SavingsTransaction
    from datetime import date as date_type

    all_txns     = db.query(SavingsTransaction).all()
    current_year = date_type.today().year

    account_balance  = round(sum(t.amount for t in all_txns), 2)
    deposits_ytd     = round(sum(t.amount for t in all_txns if t.amount > 0 and t.date.year == current_year), 2)
    withdrawals_ytd  = round(abs(sum(t.amount for t in all_txns if t.amount < 0 and t.date.year == current_year)), 2)

    jar_balances = get_jar_balances(db)
    jar_total    = round(sum(j["balance"] for j in jar_balances), 2)

    return {
        "account_balance":  account_balance,
        "jar_total":        jar_total,
        "deposits_ytd":     deposits_ytd,
        "withdrawals_ytd":  withdrawals_ytd,
    }