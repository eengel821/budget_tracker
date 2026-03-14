"""
test_services.py — Unit tests for services/aggregations.py and services/budget.py.

Tests the calculation logic directly without going through HTTP routes.
All functions receive a real SQLAlchemy session (from the db fixture) so
the queries run against a real in-memory SQLite database.

This file is the primary test coverage for:
  - Budget page row-building (monthly_rows, savings_rows, income_rows)
  - Footer totals (total_spent, total_remaining, net_total)
  - Sign correctness for expense/credit/savings rows
  - Transactions page total calculations including category filter handling
  - Dashboard stat calculations (total_remaining, net_total sign conventions)
  - Utility helpers (parse_month, get_available_months, get_uncategorized_count)
"""

import pytest
from datetime import date

from models import Account, Category, Transaction, SavingsAllocation, SavingsTransaction
from services.aggregations import (
    get_available_months,
    get_current_month_str,
    get_jar_balances,
    get_month_label,
    get_monthly_income,
    get_monthly_spending,
    get_total_expenses,
    get_total_income,
    get_uncategorized_count,
    parse_month,
)
from services.budget import build_budget_page_data, calculate_transaction_page_totals


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def svc_seed(db):
    """
    Seed data for service tests. Provides an account, four categories
    (expense with budget, savings zero-budget, income, and a second expense),
    and returns named references.
    """
    acct = Account(name="chase", type="imported")
    db.add(acct)

    groceries = Category(name="Groceries",     monthly_budget=500.0)
    dining    = Category(name="Dining",        monthly_budget=200.0)
    savings   = Category(name="Emergency Fund",monthly_budget=0.0, is_savings=True)
    income    = Category(name="Salary",        monthly_budget=0.0, is_income=True)
    db.add_all([groceries, dining, savings, income])
    db.commit()

    return {
        "acct":      acct,
        "groceries": groceries,
        "dining":    dining,
        "savings":   savings,
        "income":    income,
    }


def make_txn(db, seed, *, amount, category=None, d=date(2025, 3, 15),
             excluded=False, is_split=False, parent=None):
    """Create and commit a transaction, return it."""
    cat_id = seed[category].id if category else None
    txn = Transaction(
        date=d, amount=amount, description="TEST",
        excluded=excluded, is_split=is_split,
        parent_id=parent.id if parent else None,
        account_id=seed["acct"].id,
        category_id=cat_id,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1: Utility helpers
# ═══════════════════════════════════════════════════════════════════════════════

class TestParseMonth:
    def test_parses_year_and_month(self):
        assert parse_month("2025-03") == (2025, 3)

    def test_parses_single_digit_month(self):
        assert parse_month("2025-01") == (2025, 1)

    def test_parses_december(self):
        assert parse_month("2025-12") == (2025, 12)


class TestGetMonthLabel:
    def test_formats_label_correctly(self):
        assert get_month_label("2025-03") == "March 2025"

    def test_january(self):
        assert get_month_label("2026-01") == "January 2026"


class TestGetAvailableMonths:
    def test_empty_db_returns_empty_list(self, db):
        assert get_available_months(db) == []

    def test_returns_month_with_transaction(self, db, svc_seed):
        make_txn(db, svc_seed, amount=-50.0, category="groceries")
        months = get_available_months(db)
        assert len(months) == 1
        assert months[0]["value"] == "2025-03"
        assert months[0]["label"] == "March 2025"

    def test_returns_months_in_order(self, db, svc_seed):
        make_txn(db, svc_seed, amount=-50.0, d=date(2025, 1, 1))
        make_txn(db, svc_seed, amount=-50.0, d=date(2025, 3, 1))
        make_txn(db, svc_seed, amount=-50.0, d=date(2025, 2, 1))
        months = get_available_months(db)
        values = [m["value"] for m in months]
        assert values == ["2025-01", "2025-02", "2025-03"]

    def test_deduplicates_same_month(self, db, svc_seed):
        make_txn(db, svc_seed, amount=-50.0, d=date(2025, 3, 1))
        make_txn(db, svc_seed, amount=-25.0, d=date(2025, 3, 15))
        months = get_available_months(db)
        assert len(months) == 1


class TestGetUncategorizedCount:
    def test_zero_when_all_categorized(self, db, svc_seed):
        make_txn(db, svc_seed, amount=-50.0, category="groceries")
        assert get_uncategorized_count(db) == 0

    def test_counts_uncategorized(self, db, svc_seed):
        make_txn(db, svc_seed, amount=-50.0, category=None)
        make_txn(db, svc_seed, amount=-25.0, category=None)
        assert get_uncategorized_count(db) == 2

    def test_excludes_excluded_transactions(self, db, svc_seed):
        make_txn(db, svc_seed, amount=-50.0, category=None, excluded=True)
        assert get_uncategorized_count(db) == 0

    def test_mixed_returns_only_uncategorized_non_excluded(self, db, svc_seed):
        make_txn(db, svc_seed, amount=-50.0, category=None)           # counted
        make_txn(db, svc_seed, amount=-50.0, category="groceries")    # not counted
        make_txn(db, svc_seed, amount=-50.0, category=None, excluded=True)  # not counted
        assert get_uncategorized_count(db) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2: get_total_expenses and get_total_income
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetTotalExpenses:
    def test_returns_zero_when_empty(self, db, svc_seed):
        assert get_total_expenses(db, 2025, 3) == 0

    def test_sums_expense_transactions(self, db, svc_seed):
        make_txn(db, svc_seed, amount=-100.0, category="groceries")
        make_txn(db, svc_seed, amount=-50.0,  category="dining")
        assert get_total_expenses(db, 2025, 3) == pytest.approx(-150.0)

    def test_includes_uncategorized(self, db, svc_seed):
        make_txn(db, svc_seed, amount=-75.0, category=None)
        assert get_total_expenses(db, 2025, 3) == pytest.approx(-75.0)

    def test_excludes_income_categories(self, db, svc_seed):
        make_txn(db, svc_seed, amount=3000.0, category="income")
        assert get_total_expenses(db, 2025, 3) == 0

    def test_excludes_excluded_transactions(self, db, svc_seed):
        make_txn(db, svc_seed, amount=-100.0, category="groceries", excluded=True)
        assert get_total_expenses(db, 2025, 3) == 0

    def test_excludes_wrong_month(self, db, svc_seed):
        make_txn(db, svc_seed, amount=-100.0, category="groceries", d=date(2025, 4, 1))
        assert get_total_expenses(db, 2025, 3) == 0

    def test_excludes_split_parents(self, db, svc_seed):
        parent = make_txn(db, svc_seed, amount=-150.0, is_split=True)
        make_txn(db, svc_seed, amount=-100.0, category="groceries", excluded=True, parent=parent)
        make_txn(db, svc_seed, amount=-50.0,  category="dining",    excluded=True, parent=parent)
        assert get_total_expenses(db, 2025, 3) == pytest.approx(-150.0)

    def test_credit_in_expense_category_reduces_total(self, db, svc_seed):
        make_txn(db, svc_seed, amount=-100.0, category="groceries")
        make_txn(db, svc_seed, amount=30.0,   category="groceries")  # refund
        assert get_total_expenses(db, 2025, 3) == pytest.approx(-70.0)


class TestGetTotalIncome:
    def test_returns_zero_when_empty(self, db, svc_seed):
        assert get_total_income(db, 2025, 3) == 0

    def test_sums_income_transactions(self, db, svc_seed):
        make_txn(db, svc_seed, amount=3000.0, category="income")
        assert get_total_income(db, 2025, 3) == pytest.approx(3000.0)

    def test_excludes_expense_categories(self, db, svc_seed):
        make_txn(db, svc_seed, amount=-100.0, category="groceries")
        assert get_total_income(db, 2025, 3) == 0

    def test_excludes_excluded_transactions(self, db, svc_seed):
        make_txn(db, svc_seed, amount=3000.0, category="income", excluded=True)
        assert get_total_income(db, 2025, 3) == 0

    def test_excludes_wrong_month(self, db, svc_seed):
        make_txn(db, svc_seed, amount=3000.0, category="income", d=date(2025, 4, 1))
        assert get_total_income(db, 2025, 3) == 0

    def test_excludes_split_parents(self, db, svc_seed):
        parent = make_txn(db, svc_seed, amount=3000.0, is_split=True)
        make_txn(db, svc_seed, amount=2500.0, category="income", excluded=True, parent=parent)
        make_txn(db, svc_seed, amount=500.0,  category="savings", excluded=True, parent=parent)
        assert get_total_income(db, 2025, 3) == pytest.approx(2500.0)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3: build_budget_page_data — row building
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildBudgetPageDataRows:
    """Tests for the row-building logic in build_budget_page_data."""

    def test_expense_row_has_correct_fields(self, db, svc_seed):
        """Expense rows include id, category, budgeted, spent, remaining, pct_used."""
        make_txn(db, svc_seed, amount=-200.0, category="groceries")
        data = build_budget_page_data(db, 2025, 3)
        row = next(r for r in data["monthly_rows"] if r["category"] == "Groceries")
        assert row["budgeted"] == 500.0
        assert row["spent"] == pytest.approx(-200.0)
        assert row["remaining"] == pytest.approx(300.0)
        assert row["pct_used"] == pytest.approx(40.0)

    def test_expense_row_remaining_uses_abs_spent(self, db, svc_seed):
        """remaining = budgeted - abs(spent), not budgeted - signed_spent."""
        make_txn(db, svc_seed, amount=-300.0, category="groceries")
        data = build_budget_page_data(db, 2025, 3)
        row = next(r for r in data["monthly_rows"] if r["category"] == "Groceries")
        # Should be 500 - 300 = 200, not 500 - (-300) = 800
        assert row["remaining"] == pytest.approx(200.0)

    def test_income_row_in_income_rows(self, db, svc_seed):
        """Income categories appear in income_rows, not monthly_rows."""
        make_txn(db, svc_seed, amount=3000.0, category="income")
        data = build_budget_page_data(db, 2025, 3)
        income_names = [r["category"] for r in data["income_rows"]]
        monthly_names = [r["category"] for r in data["monthly_rows"]]
        assert "Salary" in income_names
        assert "Salary" not in monthly_names

    def test_savings_row_in_savings_rows(self, db, svc_seed):
        """Zero-budget categories appear in savings_rows."""
        make_txn(db, svc_seed, amount=-100.0, category="savings")
        data = build_budget_page_data(db, 2025, 3)
        savings_names = [r["category"] for r in data["savings_rows"]]
        assert "Emergency Fund" in savings_names

    def test_savings_rows_always_shown_even_with_zero_activity(self, db, svc_seed):
        """Savings categories are always included even with no transactions this month."""
        data = build_budget_page_data(db, 2025, 3)
        savings_names = [r["category"] for r in data["savings_rows"]]
        assert "Emergency Fund" in savings_names

    def test_zero_activity_zero_budget_expense_hidden(self, db, svc_seed):
        """Non-savings zero-budget categories with no activity are excluded."""
        # Groceries has budget=500, so it appears even with no activity
        # There's no zero-budget non-savings expense category in our seed
        # Add one and verify it doesn't appear
        misc = Category(name="Misc", monthly_budget=0.0, is_savings=False)
        db.add(misc)
        db.commit()
        data = build_budget_page_data(db, 2025, 3)
        all_names = (
            [r["category"] for r in data["monthly_rows"]] +
            [r["category"] for r in data["savings_rows"]] +
            [r["category"] for r in data["income_rows"]]
        )
        # Misc has zero budget and zero activity — it should be in savings_rows
        # (zero-budget non-income) but with spent=0
        misc_rows = [r for r in data["savings_rows"] if r["category"] == "Misc"]
        assert len(misc_rows) == 1
        assert misc_rows[0]["spent"] == 0

    def test_unassigned_bucket_appears_in_monthly_rows(self, db, svc_seed):
        """Uncategorized expense transactions create an Unassigned row."""
        make_txn(db, svc_seed, amount=-75.0, category=None)
        data = build_budget_page_data(db, 2025, 3)
        monthly_names = [r["category"] for r in data["monthly_rows"]]
        assert "Unassigned" in monthly_names

    def test_unassigned_bucket_not_shown_when_empty(self, db, svc_seed):
        """No Unassigned row when all transactions are categorized."""
        make_txn(db, svc_seed, amount=-50.0, category="groceries")
        data = build_budget_page_data(db, 2025, 3)
        monthly_names = [r["category"] for r in data["monthly_rows"]]
        assert "Unassigned" not in monthly_names

    def test_credit_in_expense_category_shows_positive_spent(self, db, svc_seed):
        """A refund in an expense category shows as positive spent (green)."""
        make_txn(db, svc_seed, amount=50.0, category="groceries")
        data = build_budget_page_data(db, 2025, 3)
        row = next(r for r in data["monthly_rows"] if r["category"] == "Groceries")
        assert row["spent"] == pytest.approx(50.0)
        assert row["remaining"] == pytest.approx(450.0)  # 500 - abs(50) = 450

    def test_credit_in_savings_shows_positive(self, db, svc_seed):
        """A credit to a savings category shows as positive spent."""
        make_txn(db, svc_seed, amount=200.0, category="savings")
        data = build_budget_page_data(db, 2025, 3)
        row = next(r for r in data["savings_rows"] if r["category"] == "Emergency Fund")
        assert row["spent"] == pytest.approx(200.0)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4: build_budget_page_data — footer totals
# ═══════════════════════════════════════════════════════════════════════════════

class TestBuildBudgetPageDataTotals:
    """Tests for footer total calculations in build_budget_page_data."""

    def test_total_spent_is_abs_of_expenses(self, db, svc_seed):
        """total_spent is a positive abs value, not negative."""
        make_txn(db, svc_seed, amount=-200.0, category="groceries")
        data = build_budget_page_data(db, 2025, 3)
        assert data["total_spent"] == pytest.approx(200.0)

    def test_total_remaining_correct(self, db, svc_seed):
        """total_remaining = total_budgeted - total_spent."""
        make_txn(db, svc_seed, amount=-200.0, category="groceries")
        data = build_budget_page_data(db, 2025, 3)
        # budgeted = 500 (groceries) + 200 (dining) = 700
        assert data["total_budgeted"] == pytest.approx(700.0)
        assert data["total_remaining"] == pytest.approx(500.0)

    def test_net_total_correct(self, db, svc_seed):
        """net_total = total_income - total_spent."""
        make_txn(db, svc_seed, amount=3000.0, category="income")
        make_txn(db, svc_seed, amount=-200.0, category="groceries")
        data = build_budget_page_data(db, 2025, 3)
        assert data["total_income"] == pytest.approx(3000.0)
        assert data["total_spent"]  == pytest.approx(200.0)
        assert data["net_total"]    == pytest.approx(2800.0)

    def test_monthly_total_spent_matches_row_sum(self, db, svc_seed):
        """monthly_total_spent equals sum of abs(spent) for all monthly rows."""
        make_txn(db, svc_seed, amount=-200.0, category="groceries")
        make_txn(db, svc_seed, amount=-80.0,  category="dining")
        data = build_budget_page_data(db, 2025, 3)
        row_sum = sum(abs(r["spent"]) for r in data["monthly_rows"])
        assert data["monthly_total_spent"] == pytest.approx(row_sum)

    def test_split_parent_not_double_counted(self, db, svc_seed):
        """Split parent amount is not added to total — only children count."""
        parent = make_txn(db, svc_seed, amount=-150.0, is_split=True)
        make_txn(db, svc_seed, amount=-100.0, category="groceries", excluded=True, parent=parent)
        make_txn(db, svc_seed, amount=-50.0,  category="dining",    excluded=True, parent=parent)
        data = build_budget_page_data(db, 2025, 3)
        assert data["total_spent"] == pytest.approx(150.0)

    def test_credit_reduces_total_spent(self, db, svc_seed):
        """A refund (credit) in an expense category reduces total_spent."""
        make_txn(db, svc_seed, amount=-200.0, category="groceries")
        make_txn(db, svc_seed, amount=50.0,   category="groceries")  # refund
        data = build_budget_page_data(db, 2025, 3)
        # net for groceries = -200 + 50 = -150, abs = 150
        assert data["total_spent"] == pytest.approx(150.0)

    def test_empty_month_all_zeros(self, db, svc_seed):
        """All totals are zero for a month with no transactions."""
        data = build_budget_page_data(db, 2025, 3)
        assert data["total_spent"]     == 0
        assert data["total_income"]    == 0
        assert data["net_total"]       == 0
        assert data["monthly_total_spent"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5: calculate_transaction_page_totals
# ═══════════════════════════════════════════════════════════════════════════════

class TestCalculateTransactionPageTotals:
    """Tests for the transactions page total calculations."""

    def test_basic_expense_total(self, db, svc_seed):
        """Total spent is sum of expense transaction amounts."""
        t1 = make_txn(db, svc_seed, amount=-100.0, category="groceries")
        t2 = make_txn(db, svc_seed, amount=-50.0,  category="dining")
        income_ids = {svc_seed["income"].id}
        result = calculate_transaction_page_totals([t1, t2], income_ids)
        assert result["total_spent"]  == pytest.approx(-150.0)
        assert result["total_income"] == pytest.approx(0.0)
        assert result["net_total"]    == pytest.approx(-150.0)

    def test_income_separated_from_expenses(self, db, svc_seed):
        """Income transactions are counted in total_income, not total_spent."""
        t1 = make_txn(db, svc_seed, amount=-100.0, category="groceries")
        t2 = make_txn(db, svc_seed, amount=3000.0, category="income")
        income_ids = {svc_seed["income"].id}
        result = calculate_transaction_page_totals([t1, t2], income_ids)
        assert result["total_spent"]  == pytest.approx(-100.0)
        assert result["total_income"] == pytest.approx(3000.0)
        assert result["net_total"]    == pytest.approx(2900.0)

    def test_split_children_excluded_without_filter(self, db, svc_seed):
        """Without category filter, split children are excluded from totals."""
        parent = make_txn(db, svc_seed, amount=-150.0, is_split=True)
        child1 = make_txn(db, svc_seed, amount=-100.0, category="groceries",
                          excluded=True, parent=parent)
        child2 = make_txn(db, svc_seed, amount=-50.0,  category="dining",
                          excluded=True, parent=parent)
        income_ids = {svc_seed["income"].id}
        # Without filter: only top-level (parent) counted
        result = calculate_transaction_page_totals([parent, child1, child2], income_ids)
        assert result["total_spent"] == pytest.approx(-150.0)

    def test_category_filter_uses_split_children(self, db, svc_seed):
        """With category filter, split children matching category are used."""
        parent = make_txn(db, svc_seed, amount=-150.0, is_split=True)
        child1 = make_txn(db, svc_seed, amount=-100.0, category="groceries",
                          excluded=True, parent=parent)
        child2 = make_txn(db, svc_seed, amount=-50.0,  category="dining",
                          excluded=True, parent=parent)
        income_ids = {svc_seed["income"].id}
        groceries_id = svc_seed["groceries"].id

        result = calculate_transaction_page_totals(
            [parent, child1, child2], income_ids, category_filter_id=groceries_id
        )
        # Only the groceries child should be counted
        assert result["total_spent"] == pytest.approx(-100.0)

    def test_uncategorized_counted_in_spent(self, db, svc_seed):
        """Uncategorized transactions count toward total_spent."""
        t = make_txn(db, svc_seed, amount=-75.0, category=None)
        income_ids = {svc_seed["income"].id}
        result = calculate_transaction_page_totals([t], income_ids)
        assert result["total_spent"] == pytest.approx(-75.0)

    def test_net_total_sign_convention(self, db, svc_seed):
        """net_total = total_income + total_spent (total_spent is negative)."""
        t1 = make_txn(db, svc_seed, amount=1000.0, category="income")
        t2 = make_txn(db, svc_seed, amount=-300.0, category="groceries")
        income_ids = {svc_seed["income"].id}
        result = calculate_transaction_page_totals([t1, t2], income_ids)
        assert result["net_total"] == pytest.approx(700.0)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6: get_jar_balances
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetJarBalances:
    def test_returns_empty_when_no_savings_cats(self, db):
        assert get_jar_balances(db) == []

    def test_returns_correct_balance(self, db, svc_seed):
        stxn = SavingsTransaction(
            date=date(2025, 3, 1), amount=1000.0,
            description="Deposit", is_allocated=True,
        )
        db.add(stxn)
        db.commit()
        alloc = SavingsAllocation(
            savings_transaction_id=stxn.id,
            category_id=svc_seed["savings"].id,
            amount=600.0,
        )
        db.add(alloc)
        db.commit()
        jars = get_jar_balances(db)
        assert len(jars) == 1
        assert jars[0]["balance"] == pytest.approx(600.0)
        assert jars[0]["name"] == "Emergency Fund"

    def test_pct_clamped_to_zero_minimum(self, db, svc_seed):
        """Negative balance jars show pct=0, not negative."""
        stxn = SavingsTransaction(
            date=date(2025, 3, 1), amount=-100.0,
            description="Withdrawal", is_allocated=True,
        )
        db.add(stxn)
        db.commit()
        alloc = SavingsAllocation(
            savings_transaction_id=stxn.id,
            category_id=svc_seed["savings"].id,
            amount=-100.0,
        )
        db.add(alloc)
        db.commit()
        jars = get_jar_balances(db)
        assert jars[0]["pct"] == 0
