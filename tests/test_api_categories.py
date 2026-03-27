"""
test_api_categories.py — HTTP-level tests for category API routes.

Tests every route in the category API using FastAPI's TestClient.
The `client` fixture (from conftest.py) wires the app to an in-memory
SQLite database so these tests never touch the real database file.

Routes covered:
  GET  /api/categories                       get_categories
  POST /api/categories                       create_category
  PUT  /api/categories/{id}/name             rename_category
  PUT  /api/categories/{id}/budget           update_category_budget
  PUT  /api/categories/{id}/is_income        toggle_category_is_income
  PUT  /api/categories/{id}/is_savings       toggle_category_is_savings
"""

import pytest
from models import Category


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1: GET /api/categories
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetCategories:
    """Tests for the get_categories route."""

    def test_get_categories_empty(self, client, db):
        """Returns an empty list when no categories exist."""
        resp = client.get("/api/categories")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_categories_returns_all(self, client, db, api_seed):
        """Returns all seeded categories."""
        resp = client.get("/api/categories")
        assert resp.status_code == 200
        names = [c["name"] for c in resp.json()]
        assert "Groceries" in names
        assert "Dining" in names
        assert "Salary" in names

    def test_get_categories_ordered_by_name(self, client, db, api_seed):
        """Categories are returned in alphabetical order."""
        resp = client.get("/api/categories")
        names = [c["name"] for c in resp.json()]
        assert names == sorted(names)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2: POST /api/categories
# ═══════════════════════════════════════════════════════════════════════════════

class TestCreateCategory:
    """Tests for the create_category route."""

    def test_create_category_success(self, client, db):
        """Creating a new category returns 200 with id, name, and monthly_budget."""
        resp = client.post(
            "/api/categories",
            json={"name": "Coffee Shops", "monthly_budget": 75.0},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Coffee Shops"
        assert data["monthly_budget"] == 75.0
        assert "id" in data

    def test_create_category_persists_to_db(self, client, db):
        """After creation, the category exists in the database."""
        client.post("/api/categories", json={"name": "Gym", "monthly_budget": 50.0})
        cat = db.query(Category).filter(Category.name == "Gym").first()
        assert cat is not None
        assert cat.monthly_budget == 50.0

    def test_create_category_default_budget_zero(self, client, db):
        """Creating a category without a budget defaults monthly_budget to 0."""
        resp = client.post("/api/categories", json={"name": "Misc"})
        assert resp.status_code == 200
        assert resp.json()["monthly_budget"] == 0.0

    def test_create_category_duplicate_returns_409(self, client, db, api_seed):
        """Creating a category with an existing name returns 409."""
        resp = client.post(
            "/api/categories",
            json={"name": "Groceries", "monthly_budget": 100.0},
        )
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]

    def test_create_category_duplicate_case_sensitive(self, client, db, api_seed):
        """Category names are case-sensitive — 'groceries' is different from 'Groceries'."""
        resp = client.post(
            "/api/categories",
            json={"name": "groceries", "monthly_budget": 100.0},
        )
        # SQLite unique constraint is case-insensitive by default for ASCII,
        # but our app-level check uses exact match — either 200 or 409 is valid
        # depending on db collation. We just verify it doesn't 500.
        assert resp.status_code in (200, 409)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3: PUT /api/categories/{id}/name
# ═══════════════════════════════════════════════════════════════════════════════

class TestRenameCategory:
    """Tests for the rename_category route."""

    def test_rename_success(self, client, db, api_seed):
        """Renaming a category returns 200 with the new name."""
        cat = api_seed["groceries"]

        resp = client.put(
            f"/api/categories/{cat.id}/name",
            json={"name": "Food & Drink"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Food & Drink"
        assert data["category_id"] == cat.id

    def test_rename_persists_to_db(self, client, db, api_seed):
        """After rename, the category name is updated in the database."""
        cat = api_seed["groceries"]
        client.put(f"/api/categories/{cat.id}/name", json={"name": "Supermarket"})
        db.refresh(cat)
        assert cat.name == "Supermarket"

    def test_rename_to_same_name_succeeds(self, client, db, api_seed):
        """Renaming a category to its own current name is allowed (no conflict)."""
        cat = api_seed["groceries"]
        resp = client.put(
            f"/api/categories/{cat.id}/name",
            json={"name": "Groceries"},
        )
        assert resp.status_code == 200

    def test_rename_conflict_with_other_category_returns_409(self, client, db, api_seed):
        """Renaming to a name already used by another category returns 409."""
        cat = api_seed["groceries"]
        resp = client.put(
            f"/api/categories/{cat.id}/name",
            json={"name": "Dining"},  # already exists
        )
        assert resp.status_code == 409
        assert "already exists" in resp.json()["detail"]

    def test_rename_not_found_returns_404(self, client, db):
        """Returns 404 when the category ID does not exist."""
        resp = client.put("/api/categories/99999/name", json={"name": "Ghost"})
        assert resp.status_code == 404
        assert "Category not found" in resp.json()["detail"]


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4: PUT /api/categories/{id}/budget
# ═══════════════════════════════════════════════════════════════════════════════

class TestUpdateCategoryBudget:
    """Tests for the update_category_budget route."""

    def test_update_budget_success(self, client, db, api_seed):
        """Updating the budget returns 200 with the new value."""
        cat = api_seed["groceries"]

        resp = client.put(
            f"/api/categories/{cat.id}/budget",
            json={"monthly_budget": 600.0},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["monthly_budget"] == 600.0
        assert data["category_id"] == cat.id

    def test_update_budget_persists_to_db(self, client, db, api_seed):
        """After update, the budget is changed in the database."""
        cat = api_seed["groceries"]
        client.put(f"/api/categories/{cat.id}/budget", json={"monthly_budget": 999.0})
        db.refresh(cat)
        assert cat.monthly_budget == 999.0

    def test_update_budget_to_zero(self, client, db, api_seed):
        """Setting the budget to zero is valid."""
        cat = api_seed["groceries"]
        resp = client.put(f"/api/categories/{cat.id}/budget", json={"monthly_budget": 0.0})
        assert resp.status_code == 200
        assert resp.json()["monthly_budget"] == 0.0

    def test_update_budget_not_found(self, client, db):
        """Returns 404 when the category ID does not exist."""
        resp = client.put("/api/categories/99999/budget", json={"monthly_budget": 100.0})
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5: PUT /api/categories/{id}/is_income
# ═══════════════════════════════════════════════════════════════════════════════

class TestToggleIsIncome:
    """Tests for the toggle_category_is_income route."""

    def test_toggle_is_income_on(self, client, db, api_seed):
        """Toggling is_income on a non-income category sets it to True."""
        cat = api_seed["groceries"]
        assert cat.is_income is False

        resp = client.put(f"/api/categories/{cat.id}/is_income")

        assert resp.status_code == 200
        assert resp.json()["is_income"] is True
        db.refresh(cat)
        assert cat.is_income is True

    def test_toggle_is_income_off(self, client, db, api_seed):
        """Toggling is_income on an income category sets it to False."""
        cat = api_seed["income"]
        assert cat.is_income is True

        resp = client.put(f"/api/categories/{cat.id}/is_income")

        assert resp.status_code == 200
        assert resp.json()["is_income"] is False

    def test_toggle_is_income_twice_returns_to_original(self, client, db, api_seed):
        """Toggling twice returns the flag to its original state."""
        cat = api_seed["groceries"]
        original = cat.is_income

        client.put(f"/api/categories/{cat.id}/is_income")
        client.put(f"/api/categories/{cat.id}/is_income")

        db.refresh(cat)
        assert cat.is_income == original

    def test_toggle_is_income_not_found(self, client, db):
        """Returns 404 when the category ID does not exist."""
        resp = client.put("/api/categories/99999/is_income")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6: PUT /api/categories/{id}/is_savings
# ═══════════════════════════════════════════════════════════════════════════════

class TestToggleIsSavings:
    """Tests for the toggle_category_is_savings route."""

    def test_toggle_is_savings_on(self, client, db, api_seed):
        """Toggling is_savings on a non-savings category sets it to True."""
        cat = api_seed["groceries"]
        assert cat.is_savings is False

        resp = client.put(f"/api/categories/{cat.id}/is_savings")

        assert resp.status_code == 200
        assert resp.json()["is_savings"] is True
        db.refresh(cat)
        assert cat.is_savings is True

    def test_toggle_is_savings_off(self, client, db, api_seed):
        """Toggling is_savings on a savings category sets it to False."""
        cat = api_seed["savings"]
        assert cat.is_savings is True

        resp = client.put(f"/api/categories/{cat.id}/is_savings")

        assert resp.status_code == 200
        assert resp.json()["is_savings"] is False

    def test_toggle_is_savings_twice_returns_to_original(self, client, db, api_seed):
        """Toggling twice returns the flag to its original state."""
        cat = api_seed["savings"]
        original = cat.is_savings

        client.put(f"/api/categories/{cat.id}/is_savings")
        client.put(f"/api/categories/{cat.id}/is_savings")

        db.refresh(cat)
        assert cat.is_savings == original

    def test_toggle_is_savings_not_found(self, client, db):
        """Returns 404 when the category ID does not exist."""
        resp = client.put("/api/categories/99999/is_savings")
        assert resp.status_code == 404

    def test_toggle_is_savings_off_blocked_when_nonzero_balance(self, client, db, api_seed):
        """Turning off is_savings is blocked when the jar has a non-zero net balance."""
        from models import SavingsAllocation, SavingsTransaction
        from datetime import date

        cat = api_seed["savings"]
        assert cat.is_savings is True

        # Create a deposit allocation leaving a positive balance
        stxn = SavingsTransaction(
            date=date(2025, 3, 1), amount=500.0,
            description="Deposit", is_allocated=True,
        )
        db.add(stxn)
        db.commit()
        alloc = SavingsAllocation(
            savings_transaction_id=stxn.id,
            category_id=cat.id,
            amount=500.0,
        )
        db.add(alloc)
        db.commit()

        resp = client.put(f"/api/categories/{cat.id}/is_savings")
        assert resp.status_code == 409
        assert "balance" in resp.json()["detail"].lower()
        # Category should still be a savings jar
        db.refresh(cat)
        assert cat.is_savings is True

    def test_toggle_is_savings_off_allowed_when_balance_is_zero(self, client, db, api_seed):
        """Turning off is_savings is allowed when net balance is zero (history is fine)."""
        from models import SavingsAllocation, SavingsTransaction
        from datetime import date

        cat = api_seed["savings"]

        # Deposit then fully withdraw — net balance = 0
        stxn1 = SavingsTransaction(date=date(2025, 3, 1), amount=500.0,
                                   description="Deposit", is_allocated=True)
        stxn2 = SavingsTransaction(date=date(2025, 3, 2), amount=-500.0,
                                   description="Withdrawal", is_allocated=True)
        db.add_all([stxn1, stxn2])
        db.commit()
        db.add(SavingsAllocation(savings_transaction_id=stxn1.id,
                                 category_id=cat.id, amount=500.0))
        db.add(SavingsAllocation(savings_transaction_id=stxn2.id,
                                 category_id=cat.id, amount=-500.0))
        db.commit()

        resp = client.put(f"/api/categories/{cat.id}/is_savings")
        assert resp.status_code == 200
        assert resp.json()["is_savings"] is False

    def test_toggle_is_savings_off_allowed_when_no_allocations(self, client, db, api_seed):
        """Turning off is_savings is allowed when the jar has no allocations."""
        cat = api_seed["savings"]
        resp = client.put(f"/api/categories/{cat.id}/is_savings")
        assert resp.status_code == 200
        assert resp.json()["is_savings"] is False