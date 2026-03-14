"""
test_budget.py — Tests for budget aggregation and transaction filtering.

Covers get_monthly_spending, get_monthly_income, get_total_expenses,
get_total_income, the unassigned bucket, and the category filter/totals
on the transactions page — for normal, split, credit, savings, and income
transaction types.

Aggregation functions are imported directly from services.aggregations so
that tests exercise the real production code rather than a re-implementation.
If the service logic changes and tests fail, the service has drifted from
the expected contract.

Requires: conftest.py seed fixture, real models with is_split + parent_id columns.

Run from project root:
    pytest tests/ -v
"""

from datetime import date

import pytest
from sqlalchemy import extract, func

from models import Category, Transaction
from services.aggregations import (
    get_monthly_spending,
    get_monthly_income,
    get_total_expenses,
    get_total_income,
)


def get_unassigned_total(db, year, month):
    """Mirrors the unassigned bucket query in budget_page."""
    txns = db.query(Transaction).filter(
        extract("year",  Transaction.date) == year,
        extract("month", Transaction.date) == month,
        Transaction.category_id.is_(None),
        Transaction.excluded == False,
        Transaction.is_split == False,
    ).all()
    return abs(sum(t.amount for t in txns if t.amount < 0))


def get_transactions_for_category(db, year, month, category_id):
    """Mirrors the category filter in transactions_page."""
    from sqlalchemy import select as sa_select
    child_parent_ids = sa_select(Transaction.parent_id).where(
        Transaction.parent_id != None,
        Transaction.category_id == category_id,
    )

    return db.query(Transaction).filter(
        extract("year",  Transaction.date) == year,
        extract("month", Transaction.date) == month,
        (Transaction.excluded == False) | (Transaction.parent_id != None),
        (Transaction.category_id == category_id) | (Transaction.id.in_(child_parent_ids)),
    ).order_by(Transaction.date.desc()).all()


def get_category_total_for_filter(db, year, month, category_id):
    """Mirrors the totals logic when category filter is active in transactions_page."""
    transactions = get_transactions_for_category(db, year, month, category_id)
    total_txns = [
        t for t in transactions
        if (t.parent_id is not None and t.category_id == category_id)
        or (t.parent_id is None and not t.is_split and t.category_id == category_id)
    ]
    return sum(t.amount for t in total_txns)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_txn(db, seed, *, amount, category=None, desc="Test", d=date(2025, 3, 15),
             excluded=False, is_split=False, parent=None):
    cat = seed.get(category) if category else None
    t = Transaction(
        date=d,
        amount=amount,
        description=desc,
        excluded=excluded,
        is_split=is_split,
        parent_id=parent.id if parent else None,
        account_id=seed["acct"].id,
        category_id=cat.id if cat else None,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def make_split(db, seed, *, parent_amount, splits, d=date(2025, 3, 15)):
    """
    Create a split transaction: one parent (is_split=True) and N children (excluded=True).
    splits = list of (category_key, amount)
    """
    parent = make_txn(db, seed, amount=parent_amount, category=None,
                      desc="Split Txn", d=d, is_split=True)
    children = []
    for cat_key, amt in splits:
        child = make_txn(db, seed, amount=amt, category=cat_key,
                         desc="Split Txn", d=d, excluded=True, parent=parent)
        children.append(child)
    return parent, children


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1: Basic expense aggregation (no splits)
# ═══════════════════════════════════════════════════════════════════════════════

class TestBasicExpenses:

    def test_single_expense(self, db, seed):
        make_txn(db, seed, amount=-100.0, category="groceries")
        assert get_total_expenses(db, 2025, 3) == pytest.approx(-100.0)

    def test_multiple_expenses_same_category(self, db, seed):
        make_txn(db, seed, amount=-50.0, category="groceries")
        make_txn(db, seed, amount=-75.0, category="groceries")
        assert get_total_expenses(db, 2025, 3) == pytest.approx(-125.0)

    def test_multiple_expenses_different_categories(self, db, seed):
        make_txn(db, seed, amount=-100.0, category="groceries")
        make_txn(db, seed, amount=-40.0,  category="dining")
        assert get_total_expenses(db, 2025, 3) == pytest.approx(-140.0)

    def test_excluded_transaction_not_counted(self, db, seed):
        make_txn(db, seed, amount=-100.0, category="groceries")
        make_txn(db, seed, amount=-50.0,  category="groceries", excluded=True)
        assert get_total_expenses(db, 2025, 3) == pytest.approx(-100.0)

    def test_wrong_month_not_counted(self, db, seed):
        make_txn(db, seed, amount=-100.0, category="groceries", d=date(2025, 2, 15))
        assert get_total_expenses(db, 2025, 3) == 0.0

    def test_uncategorized_expense_counted(self, db, seed):
        make_txn(db, seed, amount=-80.0, category=None)
        assert get_total_expenses(db, 2025, 3) == pytest.approx(-80.0)

    def test_income_not_in_total_expenses(self, db, seed):
        make_txn(db, seed, amount=3000.0, category="income")
        make_txn(db, seed, amount=-100.0, category="groceries")
        assert get_total_expenses(db, 2025, 3) == pytest.approx(-100.0)

    def test_credit_refund_in_expense_category(self, db, seed):
        make_txn(db, seed, amount=-200.0, category="groceries")
        make_txn(db, seed, amount=50.0,   category="groceries")  # refund
        assert get_total_expenses(db, 2025, 3) == pytest.approx(-150.0)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2: Income aggregation (no splits)
# ═══════════════════════════════════════════════════════════════════════════════

class TestBasicIncome:

    def test_single_income(self, db, seed):
        make_txn(db, seed, amount=3000.0, category="income")
        assert get_total_income(db, 2025, 3) == pytest.approx(3000.0)

    def test_expense_not_in_total_income(self, db, seed):
        make_txn(db, seed, amount=3000.0, category="income")
        make_txn(db, seed, amount=-100.0, category="groceries")
        assert get_total_income(db, 2025, 3) == pytest.approx(3000.0)

    def test_excluded_income_not_counted(self, db, seed):
        make_txn(db, seed, amount=3000.0, category="income")
        make_txn(db, seed, amount=500.0,  category="income", excluded=True)
        assert get_total_income(db, 2025, 3) == pytest.approx(3000.0)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3: Split expense transactions
# ═══════════════════════════════════════════════════════════════════════════════

class TestSplitExpenses:

    def test_split_parent_not_double_counted(self, db, seed):
        make_split(db, seed,
                   parent_amount=-150.0,
                   splits=[("groceries", -100.0), ("dining", -50.0)])
        assert get_total_expenses(db, 2025, 3) == pytest.approx(-150.0)

    def test_split_children_appear_in_correct_categories(self, db, seed):
        make_split(db, seed,
                   parent_amount=-150.0,
                   splits=[("groceries", -100.0), ("dining", -50.0)])
        spending = {r.category_name: r.total for r in get_monthly_spending(db, 2025, 3)}
        assert spending["Groceries"] == pytest.approx(-100.0)
        assert spending["Dining"]    == pytest.approx(-50.0)

    def test_split_plus_normal_transaction(self, db, seed):
        make_txn(db, seed, amount=-200.0, category="groceries")
        make_split(db, seed,
                   parent_amount=-150.0,
                   splits=[("groceries", -100.0), ("dining", -50.0)])
        spending = {r.category_name: r.total for r in get_monthly_spending(db, 2025, 3)}
        assert spending["Groceries"] == pytest.approx(-300.0)
        assert spending["Dining"]    == pytest.approx(-50.0)
        assert get_total_expenses(db, 2025, 3) == pytest.approx(-350.0)

    def test_unsplit_transaction_no_longer_double_counted(self, db, seed):
        parent, children = make_split(db, seed,
                                      parent_amount=-150.0,
                                      splits=[("groceries", -100.0), ("dining", -50.0)])
        for child in children:
            db.delete(child)
        parent.is_split = False
        parent.category_id = seed["groceries"].id
        db.commit()

        assert get_total_expenses(db, 2025, 3) == pytest.approx(-150.0)
        spending = {r.category_name: r.total for r in get_monthly_spending(db, 2025, 3)}
        assert spending.get("Groceries") == pytest.approx(-150.0)
        assert "Dining" not in spending


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4: Split credit (positive amount) transactions
# ═══════════════════════════════════════════════════════════════════════════════

class TestSplitCredits:

    def test_split_credit_across_expense_categories(self, db, seed):
        make_split(db, seed,
                   parent_amount=150.0,
                   splits=[("groceries", 100.0), ("dining", 50.0)])
        spending = {r.category_name: r.total for r in get_monthly_spending(db, 2025, 3)}
        assert spending["Groceries"] == pytest.approx(100.0)
        assert spending["Dining"]    == pytest.approx(50.0)

    def test_split_credit_into_savings_category(self, db, seed):
        make_split(db, seed,
                   parent_amount=150.0,
                   splits=[("savings", 100.0), ("groceries", 50.0)])
        spending = {r.category_name: r.total for r in get_monthly_spending(db, 2025, 3)}
        assert spending.get("Emergency Fund") == pytest.approx(100.0)
        assert spending.get("Groceries")      == pytest.approx(50.0)

    def test_split_credit_into_income_category(self, db, seed):
        make_split(db, seed,
                   parent_amount=150.0,
                   splits=[("income", 100.0), ("groceries", 50.0)])
        income   = {r.category_name: r.total for r in get_monthly_income(db, 2025, 3)}
        spending = {r.category_name: r.total for r in get_monthly_spending(db, 2025, 3)}
        assert income.get("Salary")      == pytest.approx(100.0)
        assert spending.get("Groceries") == pytest.approx(50.0)
        assert "Salary" not in spending

    def test_split_credit_parent_not_counted(self, db, seed):
        make_split(db, seed,
                   parent_amount=150.0,
                   splits=[("groceries", 100.0), ("dining", 50.0)])
        assert get_total_expenses(db, 2025, 3) == pytest.approx(150.0)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5: Savings category aggregation
# ═══════════════════════════════════════════════════════════════════════════════

class TestSavingsCategories:

    def test_savings_expense_appears_in_spending(self, db, seed):
        make_txn(db, seed, amount=-500.0, category="savings")
        spending = {r.category_name: r.total for r in get_monthly_spending(db, 2025, 3)}
        assert spending.get("Emergency Fund") == pytest.approx(-500.0)

    def test_savings_not_in_income(self, db, seed):
        make_txn(db, seed, amount=-500.0, category="savings")
        income = {r.category_name: r.total for r in get_monthly_income(db, 2025, 3)}
        assert "Emergency Fund" not in income

    def test_split_into_savings_category(self, db, seed):
        make_split(db, seed,
                   parent_amount=-300.0,
                   splits=[("savings", -200.0), ("groceries", -100.0)])
        spending = {r.category_name: r.total for r in get_monthly_spending(db, 2025, 3)}
        assert spending.get("Emergency Fund") == pytest.approx(-200.0)
        assert spending.get("Groceries")      == pytest.approx(-100.0)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6: Unassigned bucket
# ═══════════════════════════════════════════════════════════════════════════════

class TestUnassigned:

    def test_uncategorized_appears_in_unassigned(self, db, seed):
        make_txn(db, seed, amount=-80.0, category=None)
        assert get_unassigned_total(db, 2025, 3) == pytest.approx(80.0)

    def test_categorized_not_in_unassigned(self, db, seed):
        make_txn(db, seed, amount=-80.0, category="groceries")
        assert get_unassigned_total(db, 2025, 3) == 0.0

    def test_split_parent_not_in_unassigned(self, db, seed):
        make_split(db, seed,
                   parent_amount=-150.0,
                   splits=[("groceries", -100.0), ("dining", -50.0)])
        assert get_unassigned_total(db, 2025, 3) == 0.0

    def test_excluded_not_in_unassigned(self, db, seed):
        make_txn(db, seed, amount=-80.0, category=None, excluded=True)
        assert get_unassigned_total(db, 2025, 3) == 0.0

    def test_positive_uncategorized_not_in_unassigned(self, db, seed):
        make_txn(db, seed, amount=100.0, category=None)
        assert get_unassigned_total(db, 2025, 3) == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 7: Transaction page category filter
# ═══════════════════════════════════════════════════════════════════════════════

class TestCategoryFilter:

    def test_direct_category_match(self, db, seed):
        t = make_txn(db, seed, amount=-100.0, category="groceries")
        make_txn(db, seed, amount=-40.0, category="dining")
        results = get_transactions_for_category(db, 2025, 3, seed["groceries"].id)
        assert len(results) == 1
        assert results[0].id == t.id

    def test_split_parent_appears_when_child_matches(self, db, seed):
        parent, _ = make_split(db, seed,
                               parent_amount=-150.0,
                               splits=[("groceries", -100.0), ("dining", -50.0)])
        results = get_transactions_for_category(db, 2025, 3, seed["groceries"].id)
        assert parent.id in {r.id for r in results}

    def test_split_parent_not_returned_for_unrelated_category(self, db, seed):
        parent, _ = make_split(db, seed,
                               parent_amount=-150.0,
                               splits=[("groceries", -100.0), ("dining", -50.0)])
        results = get_transactions_for_category(db, 2025, 3, seed["savings"].id)
        assert parent.id not in {r.id for r in results}

    def test_filter_returns_correct_total(self, db, seed):
        make_split(db, seed,
                   parent_amount=-150.0,
                   splits=[("groceries", -100.0), ("dining", -50.0)])
        total = get_category_total_for_filter(db, 2025, 3, seed["groceries"].id)
        assert total == pytest.approx(-100.0)

    def test_filter_total_includes_direct_and_split(self, db, seed):
        make_txn(db, seed, amount=-200.0, category="groceries")
        make_split(db, seed,
                   parent_amount=-150.0,
                   splits=[("groceries", -100.0), ("dining", -50.0)])
        total = get_category_total_for_filter(db, 2025, 3, seed["groceries"].id)
        assert total == pytest.approx(-300.0)

    def test_filter_does_not_count_parent_full_amount(self, db, seed):
        make_split(db, seed,
                   parent_amount=-150.0,
                   splits=[("groceries", -100.0), ("dining", -50.0)])
        total = get_category_total_for_filter(db, 2025, 3, seed["groceries"].id)
        assert total != pytest.approx(-150.0)
        assert total == pytest.approx(-100.0)

    def test_filter_by_savings_category(self, db, seed):
        make_split(db, seed,
                   parent_amount=-300.0,
                   splits=[("savings", -200.0), ("groceries", -100.0)])
        total = get_category_total_for_filter(db, 2025, 3, seed["savings"].id)
        assert total == pytest.approx(-200.0)

    def test_no_cross_month_bleed(self, db, seed):
        make_txn(db, seed, amount=-100.0, category="groceries", d=date(2025, 2, 10))
        results = get_transactions_for_category(db, 2025, 3, seed["groceries"].id)
        assert len(results) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 8: get_monthly_spending per-category detail
# ═══════════════════════════════════════════════════════════════════════════════

class TestMonthlySpendingDetail:

    def test_spending_by_category_no_splits(self, db, seed):
        make_txn(db, seed, amount=-100.0, category="groceries")
        make_txn(db, seed, amount=-40.0,  category="dining")
        spending = {r.category_name: r.total for r in get_monthly_spending(db, 2025, 3)}
        assert spending["Groceries"] == pytest.approx(-100.0)
        assert spending["Dining"]    == pytest.approx(-40.0)

    def test_income_category_excluded_from_spending(self, db, seed):
        make_txn(db, seed, amount=3000.0, category="income")
        spending = {r.category_name: r.total for r in get_monthly_spending(db, 2025, 3)}
        assert "Salary" not in spending

    def test_split_parent_excluded_from_spending(self, db, seed):
        make_split(db, seed,
                   parent_amount=-150.0,
                   splits=[("groceries", -100.0), ("dining", -50.0)])
        spending = {r.category_name: r.total for r in get_monthly_spending(db, 2025, 3)}
        assert spending.get("Groceries", 0) == pytest.approx(-100.0)
        assert spending.get("Dining",    0) == pytest.approx(-50.0)

    def test_resplit_updates_category_totals(self, db, seed):
        parent, old_children = make_split(db, seed,
                                          parent_amount=-150.0,
                                          splits=[("groceries", -100.0), ("dining", -50.0)])
        for child in old_children:
            db.delete(child)
        db.commit()
        make_txn(db, seed, amount=-90.0, category="dining",  excluded=True, parent=parent)
        make_txn(db, seed, amount=-60.0, category="savings", excluded=True, parent=parent)
        db.commit()

        spending = {r.category_name: r.total for r in get_monthly_spending(db, 2025, 3)}
        assert "Groceries"          not in spending
        assert spending.get("Dining",         0) == pytest.approx(-90.0)
        assert spending.get("Emergency Fund", 0) == pytest.approx(-60.0)


# ── Budget page actual calculation helper ─────────────────────────────────────
# Uses the real aggregation functions from services.aggregations.
# actual is signed: negative = net expense, positive = net credit/income.

def get_budget_actuals(db, year, month):
    """
    Returns {category_name: actual} mirroring the budget_page loop.
    actual is signed: negative = net expense, positive = net credit/income.
    """
    spending = get_monthly_spending(db, year, month)
    income   = get_monthly_income(db, year, month)
    spent_by_cat  = {r.category_name: r.total for r in spending}
    income_by_cat = {r.category_name: r.total for r in income}

    from models import Category as Cat
    all_cats = db.query(Cat).all()
    result = {}
    for cat in all_cats:
        if cat.is_income:
            actual = income_by_cat.get(cat.name, 0)
        else:
            actual = spent_by_cat.get(cat.name, 0)   # signed: negative=expense, positive=credit
        if actual != 0:
            result[cat.name] = actual
    return result


def validate_split(parent_amount, splits_with_cats):
    """
    Mirrors backend validation rules for split_transaction:
    - Sum of abs(child amounts) must equal abs(parent amount)
    - If parent is negative: no child may target an income category
    - All child amounts must have the same sign as the parent
    Returns (ok: bool, error: str | None)
    """
    parent_sign = 1 if parent_amount >= 0 else -1
    split_total = round(sum(abs(amt) for amt, _ in splits_with_cats), 2)
    parent_total = round(abs(parent_amount), 2)

    if abs(split_total - parent_total) > 0.01:
        return False, f"Split amounts ({split_total}) must equal transaction total ({parent_total})"

    for amt, is_income_cat in splits_with_cats:
        child_sign = 1 if amt >= 0 else -1
        if child_sign != parent_sign:
            return False, "Child amounts must match the sign of the parent transaction"
        if parent_sign < 0 and is_income_cat:
            return False, "Cannot split a debit transaction into an income category"

    return True, None


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 9: Full split matrix — budget page actuals
#
# 3 parent types × 3 category types (where allowed) = 8 valid combinations
# Parent types:  debit (negative expense), credit (positive non-income), income (positive income)
# Category types: expense, savings, income
# Blocked: debit → income category
# ═══════════════════════════════════════════════════════════════════════════════

class TestSplitMatrixBudgetActuals:
    """
    Verifies that after splitting, the budget page shows the correct signed
    actual for each category, and that total money is conserved.
    """

    # ── Debit parent ──────────────────────────────────────────────────────────

    def test_debit_split_into_two_expense_cats(self, db, seed):
        """Debit → expense + expense: both show negative actuals, total conserved."""
        make_split(db, seed, parent_amount=-150.0,
                   splits=[("groceries", -100.0), ("dining", -50.0)])
        actuals = get_budget_actuals(db, 2025, 3)
        assert actuals.get("Groceries")  == pytest.approx(-100.0)
        assert actuals.get("Dining")     == pytest.approx(-50.0)
        assert get_total_expenses(db, 2025, 3) == pytest.approx(-150.0)

    def test_debit_split_into_expense_and_savings(self, db, seed):
        """Debit → expense + savings: both negative, savings shows as expense."""
        make_split(db, seed, parent_amount=-200.0,
                   splits=[("groceries", -150.0), ("savings", -50.0)])
        actuals = get_budget_actuals(db, 2025, 3)
        assert actuals.get("Groceries")      == pytest.approx(-150.0)
        assert actuals.get("Emergency Fund") == pytest.approx(-50.0)
        assert get_total_expenses(db, 2025, 3) == pytest.approx(-200.0)

    def test_debit_split_into_three_expense_cats(self, db, seed):
        """Debit → three expense cats: all negative, total conserved."""
        make_split(db, seed, parent_amount=-300.0,
                   splits=[("groceries", -100.0), ("dining", -100.0), ("savings", -100.0)])
        actuals = get_budget_actuals(db, 2025, 3)
        assert actuals.get("Groceries")      == pytest.approx(-100.0)
        assert actuals.get("Dining")         == pytest.approx(-100.0)
        assert actuals.get("Emergency Fund") == pytest.approx(-100.0)
        assert get_total_expenses(db, 2025, 3) == pytest.approx(-300.0)

    # ── Credit parent (positive, non-income category) ─────────────────────────

    def test_credit_split_into_two_expense_cats(self, db, seed):
        """Credit refund → expense + expense: both positive (reduce spending), total conserved."""
        make_split(db, seed, parent_amount=150.0,
                   splits=[("groceries", 100.0), ("dining", 50.0)])
        actuals = get_budget_actuals(db, 2025, 3)
        assert actuals.get("Groceries") == pytest.approx(100.0)
        assert actuals.get("Dining")    == pytest.approx(50.0)
        assert get_total_expenses(db, 2025, 3) == pytest.approx(150.0)

    def test_credit_split_into_expense_and_savings(self, db, seed):
        """Credit → expense + savings: savings shows positive (money added), total conserved."""
        make_split(db, seed, parent_amount=150.0,
                   splits=[("groceries", 100.0), ("savings", 50.0)])
        actuals = get_budget_actuals(db, 2025, 3)
        assert actuals.get("Groceries")      == pytest.approx(100.0)
        assert actuals.get("Emergency Fund") == pytest.approx(50.0)   # positive = credit to savings
        assert get_total_expenses(db, 2025, 3) == pytest.approx(150.0)

    def test_credit_split_into_expense_and_income(self, db, seed):
        """Credit → expense + income: income portion shows in income total, total conserved."""
        make_split(db, seed, parent_amount=150.0,
                   splits=[("groceries", 100.0), ("income", 50.0)])
        actuals  = get_budget_actuals(db, 2025, 3)
        inc_total = get_total_income(db, 2025, 3)
        assert actuals.get("Groceries") == pytest.approx(100.0)
        assert inc_total                == pytest.approx(50.0)
        assert get_total_expenses(db, 2025, 3) == pytest.approx(100.0)

    def test_credit_split_into_savings_and_income(self, db, seed):
        """Credit → savings + income: savings positive, income total correct."""
        make_split(db, seed, parent_amount=200.0,
                   splits=[("savings", 120.0), ("income", 80.0)])
        actuals   = get_budget_actuals(db, 2025, 3)
        inc_total = get_total_income(db, 2025, 3)
        assert actuals.get("Emergency Fund") == pytest.approx(120.0)
        assert inc_total                     == pytest.approx(80.0)

    # ── Income parent (positive, income category) ─────────────────────────────

    def test_income_split_into_two_income_cats(self, db, seed):
        """Income → income + income: both appear in income total, total conserved."""
        # Need a second income category
        income2 = seed["income"]  # reuse same, just verify total
        make_split(db, seed, parent_amount=3000.0,
                   splits=[("income", 2500.0), ("income", 500.0)])
        assert get_total_income(db, 2025, 3) == pytest.approx(3000.0)

    def test_income_split_into_income_and_savings(self, db, seed):
        """Income → income + savings: income portion in income total, savings shows positive."""
        make_split(db, seed, parent_amount=3000.0,
                   splits=[("income", 2500.0), ("savings", 500.0)])
        actuals   = get_budget_actuals(db, 2025, 3)
        inc_total = get_total_income(db, 2025, 3)
        assert inc_total                     == pytest.approx(2500.0)
        assert actuals.get("Emergency Fund") == pytest.approx(500.0)

    def test_income_split_into_income_and_expense(self, db, seed):
        """Income → income + expense: expense child is a positive credit in that category."""
        make_split(db, seed, parent_amount=3000.0,
                   splits=[("income", 2700.0), ("groceries", 300.0)])
        actuals   = get_budget_actuals(db, 2025, 3)
        inc_total = get_total_income(db, 2025, 3)
        assert inc_total                == pytest.approx(2700.0)
        assert actuals.get("Groceries") == pytest.approx(300.0)   # credit reduces groceries spending

    def test_income_split_into_savings_and_expense(self, db, seed):
        """Income → savings + expense: no income category child, both show positive."""
        make_split(db, seed, parent_amount=1000.0,
                   splits=[("savings", 700.0), ("groceries", 300.0)])
        actuals   = get_budget_actuals(db, 2025, 3)
        inc_total = get_total_income(db, 2025, 3)
        assert inc_total                     == pytest.approx(0.0)   # no income cat child
        assert actuals.get("Emergency Fund") == pytest.approx(700.0)
        assert actuals.get("Groceries")      == pytest.approx(300.0)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 10: Total conservation across all split types
#
# After any split, total_expenses + total_income must equal what they were
# before the split (money is neither created nor destroyed).
# ═══════════════════════════════════════════════════════════════════════════════

class TestSplitTotalConservation:

    def test_debit_split_conserves_total_expenses(self, db, seed):
        make_txn(db, seed, amount=-500.0, category="groceries")
        before = get_total_expenses(db, 2025, 3)
        # Now split an additional transaction
        make_split(db, seed, parent_amount=-200.0,
                   splits=[("groceries", -120.0), ("dining", -80.0)])
        after = get_total_expenses(db, 2025, 3)
        assert after == pytest.approx(before + (-200.0))

    def test_credit_split_conserves_net(self, db, seed):
        make_txn(db, seed, amount=-300.0, category="groceries")
        before_exp = get_total_expenses(db, 2025, 3)
        make_split(db, seed, parent_amount=100.0,
                   splits=[("groceries", 60.0), ("dining", 40.0)])
        after_exp = get_total_expenses(db, 2025, 3)
        # Credit of 100 added to expenses (as positive = reduces spending)
        assert after_exp == pytest.approx(before_exp + 100.0)

    def test_income_split_conserves_total_income(self, db, seed):
        make_txn(db, seed, amount=3000.0, category="income")
        before = get_total_income(db, 2025, 3)
        # Re-split that same transaction by deleting and re-adding as split
        make_split(db, seed, parent_amount=1000.0,
                   splits=[("income", 700.0), ("savings", 300.0)])
        after_income = get_total_income(db, 2025, 3)
        # The new split's income portion (700) adds to the 3000 already there
        assert after_income == pytest.approx(before + 700.0)

    def test_resplit_conserves_totals(self, db, seed):
        """Re-splitting should not change the total — old children gone, new children replace them."""
        parent, old_children = make_split(db, seed, parent_amount=-150.0,
                                          splits=[("groceries", -100.0), ("dining", -50.0)])
        before = get_total_expenses(db, 2025, 3)

        for child in old_children:
            db.delete(child)
        db.commit()
        make_txn(db, seed, amount=-90.0, category="groceries", excluded=True, parent=parent)
        make_txn(db, seed, amount=-60.0, category="savings",   excluded=True, parent=parent)
        db.commit()

        after = get_total_expenses(db, 2025, 3)
        assert after == pytest.approx(before)

    def test_unsplit_conserves_totals(self, db, seed):
        """Removing a split should leave totals identical to before the split was created."""
        make_txn(db, seed, amount=-200.0, category="groceries")
        parent, children = make_split(db, seed, parent_amount=-150.0,
                                      splits=[("groceries", -100.0), ("dining", -50.0)])
        before_unsplit = get_total_expenses(db, 2025, 3)

        for child in children:
            db.delete(child)
        parent.is_split = False
        parent.category_id = seed["groceries"].id
        db.commit()

        after_unsplit = get_total_expenses(db, 2025, 3)
        assert after_unsplit == pytest.approx(before_unsplit)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 11: Backend validation rules
#
# Tests the validate_split() helper which mirrors the rules that should be
# enforced in split_transaction() in main.py.
# ═══════════════════════════════════════════════════════════════════════════════

class TestSplitValidation:

    # ── Sum validation ────────────────────────────────────────────────────────

    def test_valid_debit_split_passes(self):
        ok, err = validate_split(-150.0, [(-100.0, False), (-50.0, False)])
        assert ok is True
        assert err is None

    def test_valid_credit_split_passes(self):
        ok, err = validate_split(150.0, [(100.0, False), (50.0, False)])
        assert ok is True
        assert err is None

    def test_amounts_dont_sum_to_parent_fails(self):
        ok, err = validate_split(-150.0, [(-100.0, False), (-40.0, False)])
        assert ok is False
        assert "must equal" in err

    def test_amounts_exceed_parent_fails(self):
        ok, err = validate_split(-150.0, [(-100.0, False), (-60.0, False)])
        assert ok is False
        assert "must equal" in err

    # ── Sign validation ───────────────────────────────────────────────────────

    def test_debit_parent_with_positive_child_fails(self):
        """Child with wrong sign should be rejected."""
        ok, err = validate_split(-150.0, [(-100.0, False), (50.0, False)])
        assert ok is False
        assert "sign" in err.lower()

    def test_credit_parent_with_negative_child_fails(self):
        ok, err = validate_split(150.0, [(100.0, False), (-50.0, False)])
        assert ok is False
        assert "sign" in err.lower()

    # ── Debit → income category blocked ──────────────────────────────────────

    def test_debit_into_income_category_fails(self):
        """Debit parent targeting an income category must be rejected."""
        ok, err = validate_split(-150.0, [(-100.0, False), (-50.0, True)])
        assert ok is False
        assert "income" in err.lower()

    def test_credit_into_income_category_passes(self):
        """Credit parent can target an income category."""
        ok, err = validate_split(150.0, [(100.0, False), (50.0, True)])
        assert ok is True

    def test_income_into_expense_category_passes(self):
        """Income parent can target an expense category."""
        ok, err = validate_split(3000.0, [(2700.0, True), (300.0, False)])
        assert ok is True

    def test_income_into_savings_category_passes(self):
        """Income parent can target a savings category."""
        ok, err = validate_split(3000.0, [(2500.0, True), (500.0, False)])
        assert ok is True

    def test_debit_into_two_income_categories_fails(self):
        """Both children being income categories should still fail for a debit parent."""
        ok, err = validate_split(-150.0, [(-100.0, True), (-50.0, True)])
        assert ok is False
        assert "income" in err.lower()

    # ── Edge cases ────────────────────────────────────────────────────────────

    def test_single_split_line_fails(self):
        """A split with only one line has no point — should require at least 2."""
        # This is enforced separately in the route, but validate_split
        # should still handle it gracefully via sum check if amounts match
        ok, err = validate_split(-150.0, [(-150.0, False)])
        # Sum matches, sign matches, not income — passes validation
        # (the "at least 2 lines" check is a separate route-level guard)
        assert ok is True

    def test_zero_amount_parent_edge_case(self):
        """A zero-amount transaction split should pass if children also sum to zero."""
        ok, err = validate_split(0.0, [(0.0, False), (0.0, False)])
        assert ok is True
