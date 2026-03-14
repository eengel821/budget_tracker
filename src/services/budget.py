"""
services/budget.py — Budget page data construction for Budget Tracker.

Extracts the budget page row-building logic from main.py into a testable
service function. The budget_page route calls build_budget_page_data() and
passes the result directly to the template.

Sign conventions for row data:
  - row["spent"] is signed: negative = net expense, positive = net credit/refund
  - row["remaining"] uses abs(spent) so remaining is never inflated by negatives
  - row["pct_used"] is based on abs(spent) / budgeted
  - Footer totals use abs() for monthly rows, keep sign for savings rows
    (savings can receive credits which should show as positive)
"""

from sqlalchemy import extract, func
from sqlalchemy.orm import Session

from models import Category, Transaction
from services.aggregations import (
    get_monthly_spending,
    get_monthly_income,
    get_total_income,
)


def build_budget_page_data(db: Session, year: int, month: int) -> dict:
    """
    Build all data required to render the budget vs actual page.

    Constructs expense rows, savings rows, income rows, footer totals,
    and chart data for a given month. Handles the sign conventions needed
    to display positive credits in savings categories correctly.

    Args:
        db: An active SQLAlchemy database session.
        year: The 4-digit year to build budget data for.
        month: The month number (1-12) to build budget data for.

    Returns:
        A dict containing:
          monthly_rows      — expense categories with budget > 0
          savings_rows      — zero-budget expense/savings categories
          income_rows       — is_income categories
          monthly_total_spent  — abs sum of monthly row spent values
          savings_total_spent  — signed sum of savings row spent values
          total_spent          — abs total for budget comparison
          total_budgeted       — sum of all non-income category budgets
          total_remaining      — total_budgeted - total_spent
          total_income         — total income for the month
          net_total            — total_income - total_spent
          monthly_labels/budgets/spent — chart data arrays
          savings_labels/spent         — chart data arrays (expenses only)
          income_labels/budgets/spent  — chart data arrays
    """
    spending = get_monthly_spending(db, year, month)
    income   = get_monthly_income(db, year, month)

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
            # Preserve sign: negative = net expense, positive = net credit/refund
            actual = spent_by_cat.get(cat.name, 0)

        if budgeted == 0 and actual == 0:
            continue

        # Use abs(actual) for remaining/pct to avoid double-negation inflation
        spent_abs = abs(actual)
        pct_used  = (spent_abs / budgeted * 100) if budgeted > 0 else None
        remaining = budgeted - spent_abs

        row = {
            "id":        cat.id,
            "category":  cat.name,
            "budgeted":  budgeted,
            "spent":     actual,      # signed — template colors green if positive
            "remaining": remaining,
            "pct_used":  pct_used,
        }
        if cat.is_income:
            income_rows.append(row)
        else:
            expense_rows.append(row)

    # ── Unassigned bucket ─────────────────────────────────────────────────────
    # Uncategorized non-excluded expense transactions that aren't split parents.
    unassigned_txns = db.query(Transaction).filter(
        extract("year",  Transaction.date) == year,
        extract("month", Transaction.date) == month,
        Transaction.category_id.is_(None),
        Transaction.excluded == False,  # noqa: E712
        Transaction.is_split == False,  # noqa: E712
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

    # ── Split into monthly (budgeted) and savings (zero-budget) rows ──────────
    monthly_rows      = [r for r in expense_rows if r["category"] != "Unassigned" and r["budgeted"] > 0]
    savings_rows_base = [r for r in expense_rows if r["category"] != "Unassigned" and r["budgeted"] == 0]

    # Always show ALL non-income zero-budget categories, even if $0 this month
    all_savings_cats = db.query(Category).filter(
        Category.is_income == False,  # noqa: E712
        Category.monthly_budget == 0,
    ).order_by(Category.name).all()

    savings_spent_map = {r["category"]: r["spent"] for r in savings_rows_base}
    savings_rows = [
        {
            "id":       cat.id,
            "category": cat.name,
            "budgeted": 0,
            "spent":    savings_spent_map.get(cat.name, 0),
        }
        for cat in all_savings_cats
    ]

    # Unassigned goes into monthly group (has no budget, but shows as expense)
    unassigned = next((r for r in expense_rows if r["category"] == "Unassigned"), None)
    if unassigned:
        monthly_rows.append(unassigned)

    # ── Footer totals ─────────────────────────────────────────────────────────
    total_budgeted = db.query(func.sum(Category.monthly_budget)).filter(
        Category.is_income == False  # noqa: E712
    ).scalar() or 0
    total_income = get_total_income(db, year, month)

    # Monthly rows: abs() because spent is signed (negative = expense)
    monthly_total_spent = sum(abs(r["spent"]) for r in monthly_rows)
    # Savings rows: keep signed (positive credit to savings is valid)
    savings_total_spent = sum(r["spent"] for r in savings_rows)
    # Total for budget comparison uses abs of both
    total_spent     = monthly_total_spent + abs(savings_total_spent)
    total_remaining = total_budgeted - total_spent
    net_total       = total_income - total_spent

    # ── Chart data ────────────────────────────────────────────────────────────
    monthly_labels  = [r["category"] for r in monthly_rows]
    monthly_budgets = [r["budgeted"]  for r in monthly_rows]
    monthly_spent   = [abs(r["spent"]) for r in monthly_rows]
    # Savings chart only shows expense rows (negative spent), displayed as abs
    savings_labels  = [r["category"] for r in savings_rows if r["spent"] < 0]
    savings_spent   = [abs(r["spent"]) for r in savings_rows if r["spent"] < 0]

    return {
        "monthly_rows":          monthly_rows,
        "savings_rows":          savings_rows,
        "income_rows":           income_rows,
        "monthly_total_spent":   monthly_total_spent,
        "savings_total_spent":   savings_total_spent,
        "total_spent":           total_spent,
        "total_budgeted":        total_budgeted,
        "total_remaining":       total_remaining,
        "total_income":          total_income,
        "net_total":             net_total,
        "monthly_labels":        monthly_labels,
        "monthly_budgets":       monthly_budgets,
        "monthly_spent":         monthly_spent,
        "savings_labels":        savings_labels,
        "savings_spent":         savings_spent,
        "income_labels":         [r["category"] for r in income_rows],
        "income_budgets":        [r["budgeted"]  for r in income_rows],
        "income_spent":          [r["spent"]     for r in income_rows],
    }


def calculate_transaction_page_totals(
    transactions: list,
    income_cat_ids: set,
    category_filter_id: int | None = None,
) -> dict:
    """
    Calculate total spent, total income, and net total for the transactions page.

    When no category filter is active, only top-level transactions (parent_id
    is None) are used to avoid double-counting split children.

    When a category filter is active, split children matching that category
    are included (and their parents excluded), so the totals reflect only the
    filtered category's portion of any split transaction.

    Args:
        transactions: List of Transaction ORM objects from the filtered query.
        income_cat_ids: Set of category IDs marked is_income=True.
        category_filter_id: The active category filter ID, or None if unfiltered.

    Returns:
        A dict with keys: total_spent, total_income, net_total.
        total_spent is negative (net outflow), total_income is positive,
        net_total = total_income + total_spent.
    """
    if category_filter_id is not None:
        # Include split children for this category, exclude their parents
        total_txns = [
            t for t in transactions
            if (t.parent_id is not None and t.category_id == category_filter_id)
            or (t.parent_id is None and not t.is_split and t.category_id == category_filter_id)
        ]
    else:
        # No category filter — use only top-level transactions
        total_txns = [t for t in transactions if t.parent_id is None]

    total_spent = sum(
        t.amount for t in total_txns
        if t.category_id is None or t.category_id not in income_cat_ids
    )
    total_income = sum(
        t.amount for t in total_txns
        if t.amount > 0 and t.category_id in income_cat_ids
    )
    net_total = total_income + total_spent

    return {
        "total_spent":  total_spent,
        "total_income": total_income,
        "net_total":    net_total,
    }
