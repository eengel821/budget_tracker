"""
test_pages.py — Smoke tests for all HTML page routes.

Verifies that every page route returns HTTP 200 and doesn't raise an
unhandled exception. Does not assert on HTML content — the goal is
coverage of the route handler logic (aggregations, DB queries, template
context building) and to catch any 500 errors introduced by refactoring.

Routes covered:
  GET /              dashboard
  GET /transactions  transactions page
  GET /review        review queue
  GET /budget        budget page
  GET /budget/manage budget management page
  GET /categories    category analysis page
  GET /savings       savings page
"""

import pytest
from datetime import date
from models import Account, Category, Transaction, SavingsTransaction, SavingsAllocation


# ── Page seed fixture ─────────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def page_seed(db):
    """
    Seed the database with enough data for all page routes to render
    without errors. Pages that aggregate by month need at least one
    transaction; pages that show categories need at least one category.
    """
    acct = Account(name="chase", type="imported")
    db.add(acct)

    groceries = Category(name="Groceries",     monthly_budget=500.0)
    dining    = Category(name="Dining",        monthly_budget=200.0)
    income    = Category(name="Salary",        monthly_budget=0.0,   is_income=True)
    savings   = Category(name="Emergency Fund",monthly_budget=0.0,   is_savings=True)
    db.add_all([groceries, dining, income, savings])
    db.commit()

    # A few transactions in the current month
    today = date.today()
    txns = [
        Transaction(date=today, amount=-50.0,   description="SAFEWAY",   account_id=acct.id, category_id=groceries.id),
        Transaction(date=today, amount=-25.0,   description="CHIPOTLE",  account_id=acct.id, category_id=dining.id),
        Transaction(date=today, amount=3000.0,  description="PAYROLL",   account_id=acct.id, category_id=income.id),
        Transaction(date=today, amount=-10.0,   description="UNCATEGORIZED", account_id=acct.id, category_id=None),
    ]
    db.add_all(txns)
    db.commit()

    # A savings transaction with allocation
    stxn = SavingsTransaction(
        date=today, amount=500.0, description="Savings deposit", is_allocated=True
    )
    db.add(stxn)
    db.commit()

    alloc = SavingsAllocation(
        savings_transaction_id=stxn.id,
        category_id=savings.id,
        amount=500.0,
    )
    db.add(alloc)
    db.commit()

    return {
        "acct":      acct,
        "groceries": groceries,
        "dining":    dining,
        "income":    income,
        "savings":   savings,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1: Dashboard
# ═══════════════════════════════════════════════════════════════════════════════

class TestDashboardPage:
    """Smoke tests for the dashboard route."""

    def test_dashboard_returns_200(self, client, db, page_seed):
        """Dashboard renders without error when data exists."""
        resp = client.get("/")
        assert resp.status_code == 200

    def test_dashboard_empty_db_returns_200(self, client, db):
        """Dashboard renders without error when database is empty."""
        resp = client.get("/")
        assert resp.status_code == 200

    def test_dashboard_with_month_param(self, client, db, page_seed):
        """Dashboard accepts a month query parameter."""
        today = date.today()
        resp = client.get(f"/?month={today.year}-{today.month:02d}")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2: Transactions page
# ═══════════════════════════════════════════════════════════════════════════════

class TestTransactionsPage:
    """Smoke tests for the transactions page route."""

    def test_transactions_returns_200(self, client, db, page_seed):
        """Transactions page renders without error."""
        resp = client.get("/transactions")
        assert resp.status_code == 200

    def test_transactions_empty_db_returns_200(self, client, db):
        """Transactions page renders without error when database is empty."""
        resp = client.get("/transactions")
        assert resp.status_code == 200

    def test_transactions_with_month_filter(self, client, db, page_seed):
        """Transactions page accepts month filter."""
        today = date.today()
        resp = client.get(f"/transactions?month={today.year}-{today.month:02d}")
        assert resp.status_code == 200

    def test_transactions_with_category_filter(self, client, db, page_seed):
        """Transactions page accepts category_id filter."""
        cat_id = page_seed["groceries"].id
        resp = client.get(f"/transactions?category_id={cat_id}")
        assert resp.status_code == 200

    def test_transactions_with_keyword_filter(self, client, db, page_seed):
        """Transactions page accepts keyword filter."""
        resp = client.get("/transactions?keyword=SAFEWAY")
        assert resp.status_code == 200

    def test_transactions_show_excluded(self, client, db, page_seed):
        """Transactions page accepts show_excluded parameter."""
        resp = client.get("/transactions?show_excluded=1")
        assert resp.status_code == 200

    def test_transactions_category_none_filter(self, client, db, page_seed):
        """Transactions page accepts category_id=none for uncategorized filter."""
        resp = client.get("/transactions?category_id=none")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3: Review queue
# ═══════════════════════════════════════════════════════════════════════════════

class TestReviewPage:
    """Smoke tests for the review queue page."""

    def test_review_returns_200(self, client, db, page_seed):
        """Review page renders without error when uncategorized transactions exist."""
        resp = client.get("/review")
        assert resp.status_code == 200

    def test_review_empty_queue_returns_200(self, client, db):
        """Review page renders without error when queue is empty."""
        resp = client.get("/review")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4: Budget pages
# ═══════════════════════════════════════════════════════════════════════════════

class TestBudgetPages:
    """Smoke tests for budget-related page routes."""

    def test_budget_returns_200(self, client, db, page_seed):
        """Budget page renders without error when data exists."""
        resp = client.get("/budget")
        assert resp.status_code == 200

    def test_budget_empty_db_returns_200(self, client, db):
        """Budget page renders without error when database is empty."""
        resp = client.get("/budget")
        assert resp.status_code == 200

    def test_budget_with_month_param(self, client, db, page_seed):
        """Budget page accepts a month query parameter."""
        today = date.today()
        resp = client.get(f"/budget?month={today.year}-{today.month:02d}")
        assert resp.status_code == 200

    def test_budget_manage_returns_200(self, client, db, page_seed):
        """Budget management page renders without error."""
        resp = client.get("/budget/manage")
        assert resp.status_code == 200

    def test_budget_manage_empty_db_returns_200(self, client, db):
        """Budget management page renders without error when database is empty."""
        resp = client.get("/budget/manage")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5: Categories page
# ═══════════════════════════════════════════════════════════════════════════════

class TestCategoriesPage:
    """Smoke tests for the category analysis page."""

    def test_categories_returns_200(self, client, db, page_seed):
        """Categories page renders without error when categories and data exist."""
        resp = client.get("/categories")
        assert resp.status_code == 200

    def test_categories_empty_db_returns_200(self, client, db):
        """Categories page renders without error when database is empty."""
        resp = client.get("/categories")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6: Savings page
# ═══════════════════════════════════════════════════════════════════════════════

class TestSavingsPage:
    """Smoke tests for the savings page route."""

    def test_savings_returns_200(self, client, db, page_seed):
        """Savings page renders without error when savings data exists."""
        resp = client.get("/savings")
        assert resp.status_code == 200

    def test_savings_empty_db_returns_200(self, client, db):
        """Savings page renders without error when database is empty."""
        resp = client.get("/savings")
        assert resp.status_code == 200

    def test_savings_with_keyword_filter(self, client, db, page_seed):
        """Savings page accepts keyword filter."""
        resp = client.get("/savings?keyword=deposit")
        assert resp.status_code == 200

    def test_savings_with_type_filter(self, client, db, page_seed):
        """Savings page accepts type filter."""
        resp = client.get("/savings?type=deposit")
        assert resp.status_code == 200

    def test_savings_with_status_filter(self, client, db, page_seed):
        """Savings page accepts status filter."""
        resp = client.get("/savings?status=allocated")
        assert resp.status_code == 200
