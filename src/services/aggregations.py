"""
services/aggregations.py — Database aggregation helpers for Budget Tracker.

All functions that query the database to produce summary numbers used by
page routes and the budget service. Extracted from main.py so they can be
imported and tested independently of the FastAPI application.

Sign conventions:
  - Expense amounts are negative (debits)
  - Income amounts are positive (credits)
  - get_total_expenses() returns a negative float (net outflow)
  - get_total_income() returns a positive float (net inflow)

Split transaction handling:
  - All aggregations filter Transaction.is_split == False to exclude
    split parents (their full amount would double-count their children)
  - Children (parent_id != None, excluded=True) are included via
    the (excluded == False) | (parent_id != None) filter
"""

from datetime import date, datetime
from sqlalchemy import extract, func
from sqlalchemy.orm import Session

from models import Category, Transaction


# ── Color palette for savings jar display ─────────────────────────────────────

JAR_COLORS = [
    "#4e73df", "#1cc88a", "#36b9cc", "#f6c23e",
    "#e74a3b", "#6f42c1", "#fd7e14", "#20c997",
    "#6610f2", "#d63384",
]


# ── Month utilities ───────────────────────────────────────────────────────────

def parse_month(month_str: str) -> tuple[int, int]:
    """
    Parse a YYYY-MM string into (year, month) integers.

    Args:
        month_str: A date string in YYYY-MM format (e.g. '2026-03').

    Returns:
        A (year, month) tuple of integers.
    """
    year, month = month_str.split("-")
    return int(year), int(month)


def get_current_month_str() -> str:
    """
    Return the current month as a YYYY-MM string.

    Returns:
        Current month formatted as 'YYYY-MM' (e.g. '2026-03').
    """
    today = date.today()
    return f"{today.year}-{today.month:02d}"


def get_month_label(month_str: str) -> str:
    """
    Convert a YYYY-MM string to a human-readable label.

    Args:
        month_str: A date string in YYYY-MM format.

    Returns:
        A formatted label like 'February 2026'.
    """
    year, month = parse_month(month_str)
    return datetime(year, month, 1).strftime("%B %Y")


def get_available_months(db: Session) -> list[dict]:
    """
    Return a sorted list of months that have transactions, formatted for dropdowns.

    Each entry has a 'value' key (YYYY-MM) and a 'label' key (e.g. 'February 2026').
    Returns an empty list if no transactions exist.

    Args:
        db: An active SQLAlchemy database session.

    Returns:
        List of dicts with 'value' and 'label' keys, ordered oldest to newest.
    """
    rows = db.query(
        extract("year",  Transaction.date).label("year"),
        extract("month", Transaction.date).label("month"),
    ).distinct().order_by("year", "month").all()

    months = []
    for row in rows:
        year, month = int(row.year), int(row.month)
        label = datetime(year, month, 1).strftime("%B %Y")
        months.append({"value": f"{year}-{month:02d}", "label": label})
    return months


# ── Transaction counts ────────────────────────────────────────────────────────

def get_uncategorized_count(db: Session) -> int:
    """
    Return the count of uncategorized non-excluded transactions.

    Used to drive the review queue badge in the nav bar.

    Args:
        db: An active SQLAlchemy database session.

    Returns:
        Integer count of transactions with no category assigned.
    """
    return db.query(Transaction).filter(
        Transaction.category_id.is_(None),
        Transaction.excluded == False,  # noqa: E712
    ).count()


# ── Monthly aggregations ──────────────────────────────────────────────────────

def get_monthly_spending(db: Session, year: int, month: int):
    """
    Return aggregated spending per non-income category for a given month.

    Sums ALL transaction amounts including credits (refunds reduce net spending).
    Excludes income categories, excluded transactions, and split parents.
    Split children (excluded=True, parent_id set) are included so each
    category reflects its actual allocated portion.

    Args:
        db: An active SQLAlchemy database session.
        year: The 4-digit year to aggregate.
        month: The month number (1-12) to aggregate.

    Returns:
        List of SQLAlchemy Row objects with category_name, monthly_budget,
        and total fields. total is negative for net expenses, positive for
        net credits/refunds.
    """
    return db.query(
        Category.name.label("category_name"),
        Category.monthly_budget.label("monthly_budget"),
        func.sum(Transaction.amount).label("total"),
    ).join(Transaction, Transaction.category_id == Category.id).filter(
        extract("year",  Transaction.date) == year,
        extract("month", Transaction.date) == month,
        Transaction.is_split == False,  # noqa: E712
        (Transaction.excluded == False) | (Transaction.parent_id != None),  # noqa: E712
        Category.is_income == False,  # noqa: E712
    ).group_by(Category.id).order_by(func.sum(Transaction.amount)).all()


def get_monthly_income(db: Session, year: int, month: int):
    """
    Return aggregated income per is_income category for a given month.

    Only counts positive transactions (credits) in income categories.
    Excludes split parents to avoid double-counting.

    Args:
        db: An active SQLAlchemy database session.
        year: The 4-digit year to aggregate.
        month: The month number (1-12) to aggregate.

    Returns:
        List of SQLAlchemy Row objects with category_name, monthly_budget,
        and total fields, ordered descending by total.
    """
    return db.query(
        Category.name.label("category_name"),
        Category.monthly_budget.label("monthly_budget"),
        func.sum(Transaction.amount).label("total"),
    ).join(Transaction, Transaction.category_id == Category.id).filter(
        extract("year",  Transaction.date) == year,
        extract("month", Transaction.date) == month,
        Transaction.amount > 0,
        Transaction.is_split == False,  # noqa: E712
        (Transaction.excluded == False) | (Transaction.parent_id != None),  # noqa: E712
        Category.is_income == True,  # noqa: E712
    ).group_by(Category.id).order_by(func.sum(Transaction.amount).desc()).all()


def get_total_expenses(db: Session, year: int, month: int) -> float:
    """
    Return the total net expenses for a month as a negative float.

    Sums all transactions in non-income categories plus uncategorized
    transactions. Excluded transactions are never counted. Split parents
    are excluded (their children carry the per-category amounts).

    Args:
        db: An active SQLAlchemy database session.
        year: The 4-digit year to aggregate.
        month: The month number (1-12) to aggregate.

    Returns:
        A negative float representing net outflow, or 0.0 if no expenses.
    """
    categorized = db.query(func.sum(Transaction.amount))\
        .join(Category, Transaction.category_id == Category.id)\
        .filter(
            extract("year",  Transaction.date) == year,
            extract("month", Transaction.date) == month,
            Transaction.is_split == False,  # noqa: E712
            (Transaction.excluded == False) | (Transaction.parent_id != None),  # noqa: E712
            Category.is_income == False,  # noqa: E712
        ).scalar() or 0

    uncategorized = db.query(func.sum(Transaction.amount))\
        .filter(
            extract("year",  Transaction.date) == year,
            extract("month", Transaction.date) == month,
            Transaction.excluded == False,  # noqa: E712
            Transaction.is_split == False,  # noqa: E712
            Transaction.category_id.is_(None),
        ).scalar() or 0

    return categorized + uncategorized


def get_total_income(db: Session, year: int, month: int) -> float:
    """
    Return the total income for a month as a positive float.

    Sums positive transactions in is_income categories only.
    Excluded transactions and split parents are never counted.

    Args:
        db: An active SQLAlchemy database session.
        year: The 4-digit year to aggregate.
        month: The month number (1-12) to aggregate.

    Returns:
        A positive float representing total income, or 0.0 if none.
    """
    return db.query(func.sum(Transaction.amount))\
        .join(Category, Transaction.category_id == Category.id)\
        .filter(
            extract("year",  Transaction.date) == year,
            extract("month", Transaction.date) == month,
            Transaction.amount > 0,
            Transaction.is_split == False,  # noqa: E712
            (Transaction.excluded == False) | (Transaction.parent_id != None),  # noqa: E712
            Category.is_income == True,  # noqa: E712
        ).scalar() or 0


# ── Savings jar balances ──────────────────────────────────────────────────────

def get_jar_balances(db: Session) -> list[dict]:
    """
    Calculate the current balance of every savings jar.

    A savings jar is a Category with is_savings=True. Its balance is the
    sum of all SavingsAllocation rows for that category. The pct field
    expresses each jar's share of the total positive balance.

    Args:
        db: An active SQLAlchemy database session.

    Returns:
        List of dicts with keys: category_id, name, balance, pct, color.
        pct is clamped to 0 minimum (negative balances don't show negative pct).
    """
    from models import SavingsAllocation

    savings_cats = db.query(Category).filter(
        Category.is_savings == True  # noqa: E712
    ).order_by(Category.name).all()

    total_positive = sum(
        db.query(func.sum(SavingsAllocation.amount))
          .filter(SavingsAllocation.category_id == cat.id)
          .scalar() or 0
        for cat in savings_cats
    )
    total_abs = abs(total_positive) if total_positive else 1

    results = []
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
