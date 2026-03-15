"""
routers/pages.py — HTML page routes for Budget Tracker.

All routes that render Jinja2 templates and return HTML responses.
Each route builds the context dict required by its template and returns
a TemplateResponse. Calculation logic is delegated to services/.
"""

import calendar as cal_mod
import csv as csv_mod
import io
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import extract, func, select as sa_select
from sqlalchemy.orm import Session

from database import get_db
from deps import templates
from models import Account, Category, SavingsTransaction, Transaction
from services.aggregations import (
    get_available_months,
    get_current_month_str,
    get_jar_balances,
    get_month_label,
    get_monthly_spending,
    get_total_expenses,
    get_total_income,
    get_uncategorized_count,
    parse_month,
)
from services.budget import build_budget_page_data, calculate_transaction_page_totals

router = APIRouter()


# ── Dashboard ─────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    month: Optional[str] = None,
):
    """Render the dashboard with monthly summary stats and charts."""
    available_months = get_available_months(db)
    selected_month   = month or (
        available_months[-1]["value"] if available_months else get_current_month_str()
    )
    year, mo = parse_month(selected_month)

    spending              = get_monthly_spending(db, year, mo)
    total_spent           = get_total_expenses(db, year, mo)
    total_income          = get_total_income(db, year, mo)
    total_budgeted        = db.query(func.sum(Category.monthly_budget))\
                             .filter(Category.is_income == False).scalar() or 0  # noqa: E712
    total_budgeted_income = db.query(func.sum(Category.monthly_budget))\
                             .filter(Category.is_income == True).scalar() or 0   # noqa: E712
    total_remaining       = total_budgeted - abs(total_spent)
    net_total             = total_income + total_spent  # total_spent is negative

    # Pie chart: budgeted categories
    budget_pie_cats   = db.query(Category)\
                         .filter(Category.is_income == False, Category.monthly_budget > 0)\
                         .order_by(Category.name).all()  # noqa: E712
    budget_pie_labels = [c.name for c in budget_pie_cats]
    budget_pie_values = [c.monthly_budget for c in budget_pie_cats]

    # Pie chart: actual spend this month (expense categories only)
    spent_by_cat      = {row.category_name: abs(row.total) for row in spending if row.total < 0}
    actual_pie_labels = [k for k, v in sorted(spent_by_cat.items(), key=lambda x: -x[1]) if v > 0]
    actual_pie_values = [spent_by_cat[k] for k in actual_pie_labels]

    # 12-month trend chart
    trend_months       = available_months[-12:]
    trend_labels       = []
    trend_inc_budgeted = []
    trend_inc_actual   = []
    trend_exp_budgeted = []
    trend_exp_actual   = []
    trend_net_cashflow = []

    for m in trend_months:
        y, mo2     = parse_month(m["value"])
        exp_actual = abs(get_total_expenses(db, y, mo2))
        inc_actual = get_total_income(db, y, mo2)
        trend_labels.append(datetime(y, mo2, 1).strftime("%b %y"))
        trend_inc_budgeted.append(round(total_budgeted_income, 2))
        trend_inc_actual.append(round(inc_actual, 2))
        trend_exp_budgeted.append(round(total_budgeted, 2))
        trend_exp_actual.append(round(exp_actual, 2))
        trend_net_cashflow.append(round(inc_actual - exp_actual, 2))

    recent_transactions = db.query(Transaction).filter(
        extract("year",  Transaction.date) == year,
        extract("month", Transaction.date) == mo,
        Transaction.excluded == False,  # noqa: E712
    ).order_by(Transaction.date.desc()).limit(10).all()

    # Savings growth chart (last 12 months cumulative balance)
    all_savings_txns      = db.query(SavingsTransaction).all()
    savings_balance       = round(sum(t.amount for t in all_savings_txns), 2)
    jar_balances_dash     = get_jar_balances(db)
    unallocated_count     = sum(1 for t in all_savings_txns if not t.is_allocated)
    today_d               = date.today()
    savings_growth_labels = []
    savings_growth_bals   = []

    for i in range(11, -1, -1):
        total_mo = today_d.year * 12 + today_d.month - i - 1
        g_yr     = total_mo // 12
        g_mo     = total_mo % 12 + 1
        last_day = cal_mod.monthrange(g_yr, g_mo)[1]
        cutoff   = date(g_yr, g_mo, last_day)
        bal      = round(sum(t.amount for t in all_savings_txns if t.date <= cutoff), 2)
        savings_growth_labels.append(datetime(g_yr, g_mo, 1).strftime("%b %y"))
        savings_growth_bals.append(bal)

    return templates.TemplateResponse(request, "dashboard.html", {
        "active_page":            "dashboard",
        "available_months":       available_months,
        "selected_month":         selected_month,
        "current_month_label":    get_month_label(selected_month),
        "total_spent":            total_spent,
        "total_income":           total_income,
        "total_budgeted":         total_budgeted,
        "total_remaining":        total_remaining,
        "net_total":              net_total,
        "budget_pie_labels":      budget_pie_labels,
        "budget_pie_values":      budget_pie_values,
        "actual_pie_labels":      actual_pie_labels,
        "actual_pie_values":      actual_pie_values,
        "trend_labels":           trend_labels,
        "trend_inc_budgeted":     trend_inc_budgeted,
        "trend_inc_actual":       trend_inc_actual,
        "trend_exp_budgeted":     trend_exp_budgeted,
        "trend_exp_actual":       trend_exp_actual,
        "trend_net_cashflow":     trend_net_cashflow,
        "recent_transactions":    recent_transactions,
        "uncategorized_count":    get_uncategorized_count(db),
        "savings_balance":        savings_balance,
        "jar_balances_dash":      jar_balances_dash,
        "unallocated_count":      unallocated_count,
        "savings_growth_labels":  savings_growth_labels,
        "savings_growth_balances": savings_growth_bals,
    })


# ── Transactions ──────────────────────────────────────────────────────────────

@router.get("/transactions", response_class=HTMLResponse)
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
    available_months = get_available_months(db)
    accounts         = db.query(Account).order_by(Account.name).all()
    categories       = db.query(Category).order_by(Category.name).all()

    query = db.query(Transaction)

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
        cat_id_int       = int(category_id)
        child_parent_ids = sa_select(Transaction.parent_id).where(
            Transaction.parent_id != None,  # noqa: E711
            Transaction.category_id == cat_id_int,
        )
        query = query.filter(
            (Transaction.category_id == cat_id_int) |
            (Transaction.id.in_(child_parent_ids))
        )
    if keyword:
        query = query.filter(Transaction.description.ilike(f"%{keyword}%"))
    if date_from:
        query = query.filter(Transaction.date >= date_from)
    if date_to:
        query = query.filter(Transaction.date <= date_to)

    if show_excluded != "1":
        query = query.filter(
            (Transaction.excluded == False) |  # noqa: E712
            (Transaction.parent_id != None)    # noqa: E711
        )

    transactions   = query.order_by(Transaction.date.desc()).all()
    income_cat_ids = {c.id for c in db.query(Category).filter(
        Category.is_income == True  # noqa: E712
    ).all()}
    cat_id_int = int(category_id) if (category_id and category_id != "none") else None
    totals     = calculate_transaction_page_totals(transactions, income_cat_ids, cat_id_int)

    return templates.TemplateResponse(request, "transactions.html", {
        "active_page":       "transactions",
        "transactions":      transactions,
        "accounts":          accounts,
        "categories":        categories,
        "available_months":  available_months,
        "selected_month":    month or "",
        "selected_account":  account_id or "",
        "selected_category": category_id or "",
        "selected_keyword":  keyword or "",
        "selected_date_from": date_from or "",
        "selected_date_to":  date_to or "",
        "show_excluded":     show_excluded == "1",
        "total_count":       len(transactions),
        "total_spent":       totals["total_spent"],
        "total_income":      totals["total_income"],
        "net_total":         totals["net_total"],
        "uncategorized_count": get_uncategorized_count(db),
    })


@router.get("/transactions/download")
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
    query = db.query(Transaction).filter(Transaction.excluded == False)  # noqa: E712

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
        cat_id_int       = int(category_id)
        child_parent_ids = sa_select(Transaction.parent_id).where(
            Transaction.parent_id != None,  # noqa: E711
            Transaction.category_id == cat_id_int,
        )
        query = query.filter(
            (Transaction.category_id == cat_id_int) |
            (Transaction.id.in_(child_parent_ids))
        )
    if keyword:
        query = query.filter(Transaction.description.ilike(f"%{keyword}%"))
    if date_from:
        query = query.filter(Transaction.date >= date_from)
    if date_to:
        query = query.filter(Transaction.date <= date_to)

    transactions = query.order_by(Transaction.date.desc()).all()

    output = io.StringIO()
    writer = csv_mod.writer(output)
    writer.writerow(["Date", "Description", "Category", "Account", "Debit", "Credit", "Notes"])
    for t in transactions:
        debit  = f"{abs(t.amount):.2f}" if t.amount < 0 else ""
        credit = f"{t.amount:.2f}"      if t.amount > 0 else ""
        writer.writerow([
            t.date,
            t.description,
            t.category.name if t.category else "",
            t.account.name  if t.account  else "",
            debit, credit,
            t.notes or "",
        ])

    output.seek(0)
    filename = f"transactions_{month or 'all'}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ── Review queue ──────────────────────────────────────────────────────────────

@router.get("/review", response_class=HTMLResponse)
def review_page(
    request: Request,
    db: Session = Depends(get_db),
    message: Optional[str] = None,
):
    """Render the uncategorized transaction review queue."""
    transactions = db.query(Transaction).filter(
        Transaction.category_id.is_(None),
        Transaction.excluded == False,  # noqa: E712
    ).order_by(Transaction.date.desc()).all()

    categories = db.query(Category).order_by(Category.name).all()

    return templates.TemplateResponse(request, "review.html", {
        "active_page":        "review",
        "transactions":       transactions,
        "categories":         categories,
        "uncategorized_count": len(transactions),
        "message":            message,
    })


# ── Budget ────────────────────────────────────────────────────────────────────

@router.get("/budget", response_class=HTMLResponse)
def budget_page(
    request: Request,
    db: Session = Depends(get_db),
    month: Optional[str] = None,
):
    """Render the budget vs actual comparison page."""
    available_months = get_available_months(db)
    selected_month   = (
        (month or available_months[-1]["value"])
        if available_months else get_current_month_str()
    )
    year, mo = parse_month(selected_month)
    data     = build_budget_page_data(db, year, mo)

    return templates.TemplateResponse(request, "budget.html", {
        "active_page":         "budget",
        "available_months":    available_months,
        "selected_month":      selected_month,
        "current_month_label": get_month_label(selected_month),
        "uncategorized_count": get_uncategorized_count(db),
        **data,
    })


@router.get("/budget/manage", response_class=HTMLResponse)
def budget_manage_page(
    request: Request,
    db: Session = Depends(get_db),
    message: Optional[str] = None,
):
    """Render the budget management page for editing category budgets."""
    categories              = db.query(Category).order_by(Category.name).all()
    total_budgeted_expenses = sum(c.monthly_budget or 0 for c in categories if not c.is_income)
    total_budgeted_income   = sum(c.monthly_budget or 0 for c in categories if c.is_income)

    return templates.TemplateResponse(request, "budget_manage.html", {
        "active_page":             "budget",
        "categories":              categories,
        "total_budgeted_expenses": total_budgeted_expenses,
        "total_budgeted_income":   total_budgeted_income,
        "uncategorized_count":     get_uncategorized_count(db),
        "message":                 message,
    })


# ── Categories ────────────────────────────────────────────────────────────────

@router.get("/categories", response_class=HTMLResponse)
def categories_page(request: Request, db: Session = Depends(get_db)):
    """Render the category analysis page with per-category 12-month trend charts."""
    available_months = get_available_months(db)
    last_12          = available_months[-12:]

    all_expense_cats  = db.query(Category)\
                         .filter(Category.is_income == False)\
                         .order_by(Category.name).all()  # noqa: E712
    total_budgeted_mo = sum(c.monthly_budget for c in all_expense_cats)
    total_cat_count   = len(all_expense_cats)

    month_labels = [
        datetime(*parse_month(m["value"]), 1).strftime("%b %y")
        for m in last_12
    ]

    cat_rows = []
    for cat in all_expense_cats:
        monthly_spent = []
        for m in last_12:
            y2, mo2 = parse_month(m["value"])
            result  = db.query(func.sum(Transaction.amount)).filter(
                Transaction.category_id == cat.id,
                Transaction.excluded == False,  # noqa: E712
                extract("year",  Transaction.date) == y2,
                extract("month", Transaction.date) == mo2,
            ).scalar() or 0
            monthly_spent.append(round(abs(result) if result < 0 else 0, 2))

        active      = [v for v in monthly_spent if v > 0]
        avg_spent   = round(sum(active) / len(active), 2) if active else 0
        avg_budget  = cat.monthly_budget
        avg_diff    = round(avg_spent - avg_budget, 2) if avg_budget > 0 else None
        max_spent   = max(monthly_spent) if active else 0
        max_month   = month_labels[monthly_spent.index(max_spent)] if active else "—"

        cat_rows.append({
            "id":            cat.id,
            "name":          cat.name,
            "budget":        avg_budget,
            "avg_spent":     avg_spent,
            "avg_diff":      avg_diff,
            "max_spent":     max_spent,
            "max_month":     max_month,
            "active_months": len(active),
            "monthly_spent": monthly_spent,
            "over_under": [
                round(avg_budget - v, 2) if avg_budget > 0 else None
                for v in monthly_spent
            ],
        })

    budgeted_cats  = [r for r in cat_rows if r["budget"] > 0]
    most_over      = max(budgeted_cats, key=lambda r: r["avg_diff"] or 0) if budgeted_cats else None
    most_over_name = most_over["name"]     if most_over and most_over["avg_diff"] and most_over["avg_diff"] > 0 else "None"
    most_over_amt  = most_over["avg_diff"] if most_over and most_over["avg_diff"] and most_over["avg_diff"] > 0 else 0

    savings_cats     = [r for r in cat_rows if r["budget"] == 0 and r["avg_spent"] > 0]
    top_savings      = max(savings_cats, key=lambda r: r["avg_spent"]) if savings_cats else None
    top_savings_name = top_savings["name"]      if top_savings else "None"
    top_savings_amt  = top_savings["avg_spent"] if top_savings else 0

    return templates.TemplateResponse(request, "categories.html", {
        "active_page":        "categories",
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


# ── Savings page ──────────────────────────────────────────────────────────────

@router.get("/savings", response_class=HTMLResponse)
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
        query = query.filter(SavingsTransaction.is_allocated == True)   # noqa: E712
    elif status == "unallocated":
        query = query.filter(SavingsTransaction.is_allocated == False)  # noqa: E712

    savings_transactions = query.order_by(SavingsTransaction.date.desc()).all()
    all_txns             = db.query(SavingsTransaction).all()
    current_year         = date.today().year

    deposits_ytd     = sum(t.amount for t in all_txns if t.amount > 0 and t.date.year == current_year)
    withdrawals_ytd  = abs(sum(t.amount for t in all_txns if t.amount < 0 and t.date.year == current_year))
    deposit_count    = sum(1 for t in all_txns if t.amount > 0 and t.date.year == current_year)
    withdrawal_count = sum(1 for t in all_txns if t.amount < 0 and t.date.year == current_year)
    account_balance  = round(sum(t.amount for t in all_txns), 2)

    jar_balances      = get_jar_balances(db)
    jar_total         = round(sum(j["balance"] for j in jar_balances), 2)
    total_deposits    = sum(t.amount for t in savings_transactions if t.amount > 0)
    total_withdrawals = abs(sum(t.amount for t in savings_transactions if t.amount < 0))

    savings_account = db.query(Account).filter(
        Account.name.ilike("%etrade%") | Account.name.ilike("%savings%")
    ).first()

    return templates.TemplateResponse(request, "savings.html", {
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