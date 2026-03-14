"""
test_api_savings.py — HTTP-level tests for savings API routes.

Tests all savings endpoints via TestClient. A savings_seed fixture provides
a savings jar category, a savings transaction, and allocations so tests
can verify read operations without creating data inline every time.

Routes covered:
  POST   /api/savings/transactions                      create_savings_transaction
  DELETE /api/savings/transactions/{id}                 delete_savings_transaction
  PATCH  /api/savings/transactions/{id}                 edit_savings_transaction
  GET    /api/savings/transactions/{id}/allocations     get_savings_allocations
  PUT    /api/savings/transactions/{id}/allocations     save_savings_allocations
  GET    /api/savings/jars                              get_savings_jars
  GET    /api/savings/jars/{category_id}/history        get_jar_history
  POST   /api/savings/rebalance                         rebalance_jars
  GET    /api/savings/templates/default                 get_default_template
  PUT    /api/savings/templates/default                 save_default_template
  GET    /api/savings/summary                           get_savings_summary
"""

import pytest
from datetime import date
from models import Category, SavingsTransaction, SavingsAllocation, AllocationTemplate


# ── Savings seed fixture ──────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def savings_seed(db):
    """
    Seed the database with savings jars, a transaction, and allocations.

    Creates:
      - Two savings jar categories (Emergency Fund, Vacation)
      - One deposit SavingsTransaction ($1000)
      - One SavingsAllocation per jar ($600 Emergency, $400 Vacation)

    Returns a dict of named records for use in tests.
    """
    emergency = Category(name="Emergency Fund", monthly_budget=0.0, is_savings=True)
    vacation  = Category(name="Vacation",       monthly_budget=0.0, is_savings=True)
    db.add_all([emergency, vacation])
    db.commit()

    txn = SavingsTransaction(
        date=date(date.today().year, 3, 1),
        amount=1000.0,
        description="Paycheck deposit",
        notes=None,
        is_allocated=True,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)

    alloc_e = SavingsAllocation(
        savings_transaction_id=txn.id,
        category_id=emergency.id,
        amount=600.0,
    )
    alloc_v = SavingsAllocation(
        savings_transaction_id=txn.id,
        category_id=vacation.id,
        amount=400.0,
    )
    db.add_all([alloc_e, alloc_v])
    db.commit()

    return {
        "emergency": emergency,
        "vacation":  vacation,
        "txn":       txn,
        "alloc_e":   alloc_e,
        "alloc_v":   alloc_v,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1: POST /api/savings/transactions
# ═══════════════════════════════════════════════════════════════════════════════

class TestCreateSavingsTransaction:
    """Tests for creating savings transactions manually."""

    def test_create_success(self, client, db):
        """Creating a valid savings transaction returns 200 with the new record."""
        resp = client.post("/api/savings/transactions", json={
            "date": f"{date.today().year}-03-15",
            "amount": 500.0,
            "description": "Monthly deposit",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["amount"] == 500.0
        assert data["description"] == "Monthly deposit"
        assert data["is_allocated"] is False

    def test_create_persists_to_db(self, client, db):
        """After creation, the transaction exists in the database."""
        client.post("/api/savings/transactions", json={
            "date": f"{date.today().year}-03-15",
            "amount": 500.0,
            "description": "Monthly deposit",
        })
        db.expire_all()
        txn = db.query(SavingsTransaction).first()
        assert txn is not None
        assert txn.amount == 500.0

    def test_create_with_notes(self, client, db):
        """Notes field is stored correctly."""
        resp = client.post("/api/savings/transactions", json={
            "date": f"{date.today().year}-03-15",
            "amount": 200.0,
            "description": "Transfer",
            "notes": "From checking",
        })
        assert resp.status_code == 200
        db.expire_all()
        txn = db.query(SavingsTransaction).first()
        assert txn.notes == "From checking"

    def test_create_missing_date_returns_400(self, client, db):
        """Returns 400 when date is missing."""
        resp = client.post("/api/savings/transactions", json={
            "amount": 500.0,
            "description": "Missing date",
        })
        assert resp.status_code == 400

    def test_create_empty_description_returns_400(self, client, db):
        """Returns 400 when description is empty."""
        resp = client.post("/api/savings/transactions", json={
            "date": f"{date.today().year}-03-15",
            "amount": 500.0,
            "description": "   ",
        })
        assert resp.status_code == 400
        assert "Description" in resp.json()["detail"]

    def test_create_negative_amount_for_withdrawal(self, client, db):
        """Negative amounts (withdrawals) are accepted."""
        resp = client.post("/api/savings/transactions", json={
            "date": f"{date.today().year}-03-15",
            "amount": -250.0,
            "description": "Car repair withdrawal",
        })
        assert resp.status_code == 200
        assert resp.json()["amount"] == -250.0


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2: DELETE /api/savings/transactions/{id}
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeleteSavingsTransaction:
    """Tests for deleting savings transactions."""

    def test_delete_success(self, client, db, savings_seed):
        """Deleting an existing transaction returns 200."""
        txn = savings_seed["txn"]
        resp = client.delete(f"/api/savings/transactions/{txn.id}")
        assert resp.status_code == 200
        assert str(txn.id) in resp.json()["message"]

    def test_delete_removes_from_db(self, client, db, savings_seed):
        """After deletion, the transaction no longer exists."""
        txn = savings_seed["txn"]
        txn_id = txn.id
        client.delete(f"/api/savings/transactions/{txn_id}")
        db.expire_all()
        assert db.query(SavingsTransaction).filter(SavingsTransaction.id == txn_id).first() is None

    def test_delete_cascades_to_allocations(self, client, db, savings_seed):
        """Deleting a transaction also deletes its allocations."""
        txn = savings_seed["txn"]
        txn_id = txn.id
        client.delete(f"/api/savings/transactions/{txn_id}")
        db.expire_all()
        allocs = db.query(SavingsAllocation).filter(
            SavingsAllocation.savings_transaction_id == txn_id
        ).all()
        assert len(allocs) == 0

    def test_delete_not_found(self, client, db):
        """Returns 404 when transaction does not exist."""
        resp = client.delete("/api/savings/transactions/99999")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3: PATCH /api/savings/transactions/{id}
# ═══════════════════════════════════════════════════════════════════════════════

class TestEditSavingsTransaction:
    """Tests for editing savings transactions."""

    def test_edit_description(self, client, db, savings_seed):
        """Patching description updates it."""
        txn = savings_seed["txn"]
        resp = client.patch(f"/api/savings/transactions/{txn.id}", json={
            "description": "Updated description",
        })
        assert resp.status_code == 200
        assert resp.json()["description"] == "Updated description"

    def test_edit_amount(self, client, db, savings_seed):
        """Patching amount updates it."""
        txn = savings_seed["txn"]
        resp = client.patch(f"/api/savings/transactions/{txn.id}", json={"amount": 1200.0})
        assert resp.status_code == 200
        assert resp.json()["amount"] == 1200.0

    def test_edit_date(self, client, db, savings_seed):
        """Patching date updates it."""
        txn = savings_seed["txn"]
        resp = client.patch(f"/api/savings/transactions/{txn.id}", json={"date": f"{date.today().year}-04-01"})
        assert resp.status_code == 200
        assert resp.json()["date"] == f"{date.today().year}-04-01"

    def test_edit_empty_description_returns_400(self, client, db, savings_seed):
        """Empty description is rejected."""
        txn = savings_seed["txn"]
        resp = client.patch(f"/api/savings/transactions/{txn.id}", json={"description": ""})
        assert resp.status_code == 400

    def test_edit_not_found(self, client, db):
        """Returns 404 when transaction does not exist."""
        resp = client.patch("/api/savings/transactions/99999", json={"description": "ghost"})
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4: GET /api/savings/transactions/{id}/allocations
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetSavingsAllocations:
    """Tests for retrieving allocations for a savings transaction."""

    def test_get_allocations_success(self, client, db, savings_seed):
        """Returns allocations and jar balances for an existing transaction."""
        txn = savings_seed["txn"]
        resp = client.get(f"/api/savings/transactions/{txn.id}/allocations")
        assert resp.status_code == 200
        data = resp.json()
        assert data["txn_id"] == txn.id
        assert data["amount"] == 1000.0
        assert len(data["allocations"]) == 2

    def test_get_allocations_includes_jar_balances(self, client, db, savings_seed):
        """Response includes current jar balances."""
        txn = savings_seed["txn"]
        resp = client.get(f"/api/savings/transactions/{txn.id}/allocations")
        assert "jars" in resp.json()
        assert len(resp.json()["jars"]) == 2

    def test_get_allocations_not_found(self, client, db):
        """Returns 404 when transaction does not exist."""
        resp = client.get("/api/savings/transactions/99999/allocations")
        assert resp.status_code == 404

    def test_get_allocations_empty_for_unallocated(self, client, db, savings_seed):
        """A new unallocated transaction returns an empty allocations list."""
        txn = SavingsTransaction(
            date=date(date.today().year, 4, 1),
            amount=500.0,
            description="New deposit",
            is_allocated=False,
        )
        db.add(txn)
        db.commit()
        resp = client.get(f"/api/savings/transactions/{txn.id}/allocations")
        assert resp.json()["allocations"] == []


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5: PUT /api/savings/transactions/{id}/allocations
# ═══════════════════════════════════════════════════════════════════════════════

class TestSaveSavingsAllocations:
    """Tests for saving/replacing allocations on a savings transaction."""

    def test_save_allocations_success(self, client, db, savings_seed):
        """Saving valid allocations returns 200 with updated data."""
        txn = savings_seed["txn"]
        emergency = savings_seed["emergency"]
        vacation = savings_seed["vacation"]

        resp = client.put(f"/api/savings/transactions/{txn.id}/allocations", json={
            "allocations": [
                {"category_id": emergency.id, "amount": 700.0},
                {"category_id": vacation.id,  "amount": 300.0},
            ]
        })
        assert resp.status_code == 200
        assert resp.json()["is_allocated"] is True
        assert resp.json()["total_allocated"] == 1000.0

    def test_save_allocations_marks_allocated_when_balanced(self, client, db, savings_seed):
        """Transaction is marked is_allocated=True when amounts sum to transaction total."""
        txn = savings_seed["txn"]
        emergency = savings_seed["emergency"]
        vacation = savings_seed["vacation"]

        client.put(f"/api/savings/transactions/{txn.id}/allocations", json={
            "allocations": [
                {"category_id": emergency.id, "amount": 600.0},
                {"category_id": vacation.id,  "amount": 400.0},
            ]
        })
        db.expire_all()
        db.refresh(txn)
        assert txn.is_allocated is True

    def test_save_allocations_not_allocated_when_unbalanced(self, client, db, savings_seed):
        """Transaction is not marked allocated when amounts don't sum to transaction total."""
        txn = savings_seed["txn"]
        emergency = savings_seed["emergency"]

        client.put(f"/api/savings/transactions/{txn.id}/allocations", json={
            "allocations": [
                {"category_id": emergency.id, "amount": 500.0},  # only 500 of 1000
            ]
        })
        db.expire_all()
        db.refresh(txn)
        assert txn.is_allocated is False

    def test_save_allocations_non_savings_category_rejected(self, client, db, savings_seed):
        """Returns 400 when allocation targets a non-savings category."""
        txn = savings_seed["txn"]
        # Create a non-savings category
        expense_cat = Category(name="Groceries", monthly_budget=500.0, is_savings=False)
        db.add(expense_cat)
        db.commit()

        resp = client.put(f"/api/savings/transactions/{txn.id}/allocations", json={
            "allocations": [
                {"category_id": expense_cat.id, "amount": 1000.0},
            ]
        })
        assert resp.status_code == 400
        assert "savings jar" in resp.json()["detail"].lower()

    def test_save_allocations_replaces_existing(self, client, db, savings_seed):
        """Saving new allocations replaces the old ones entirely."""
        txn = savings_seed["txn"]
        emergency = savings_seed["emergency"]
        vacation = savings_seed["vacation"]

        # Save new allocations
        client.put(f"/api/savings/transactions/{txn.id}/allocations", json={
            "allocations": [
                {"category_id": emergency.id, "amount": 800.0},
                {"category_id": vacation.id,  "amount": 200.0},
            ]
        })
        db.expire_all()
        allocs = db.query(SavingsAllocation).filter(
            SavingsAllocation.savings_transaction_id == txn.id
        ).all()
        amounts = sorted(a.amount for a in allocs)
        assert amounts == [200.0, 800.0]

    def test_save_allocations_not_found(self, client, db, savings_seed):
        """Returns 404 when transaction does not exist."""
        resp = client.put("/api/savings/transactions/99999/allocations", json={
            "allocations": []
        })
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6: GET /api/savings/jars
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetSavingsJars:
    """Tests for the savings jars balance endpoint."""

    def test_get_jars_empty(self, client, db):
        """Returns empty list when no savings jars exist."""
        resp = client.get("/api/savings/jars")
        assert resp.status_code == 200
        assert resp.json()["jars"] == []

    def test_get_jars_returns_correct_balances(self, client, db, savings_seed):
        """Returns balances matching the seeded allocations."""
        resp = client.get("/api/savings/jars")
        assert resp.status_code == 200
        jars = {j["name"]: j["balance"] for j in resp.json()["jars"]}
        assert jars["Emergency Fund"] == 600.0
        assert jars["Vacation"] == 400.0

    def test_get_jars_includes_pct(self, client, db, savings_seed):
        """Each jar includes a pct field."""
        resp = client.get("/api/savings/jars")
        for jar in resp.json()["jars"]:
            assert "pct" in jar


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 7: GET /api/savings/jars/{id}/history
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetJarHistory:
    """Tests for per-jar history endpoint."""

    def test_get_jar_history_success(self, client, db, savings_seed):
        """Returns history entries and stats for a savings jar."""
        cat = savings_seed["emergency"]
        resp = client.get(f"/api/savings/jars/{cat.id}/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Emergency Fund"
        assert data["balance"] == 600.0
        assert len(data["entries"]) == 1
        assert len(data["chart_labels"]) == 12  # last 12 months

    def test_get_jar_history_running_balance(self, client, db, savings_seed):
        """Entries include correct running balance."""
        cat = savings_seed["emergency"]
        resp = client.get(f"/api/savings/jars/{cat.id}/history")
        entry = resp.json()["entries"][0]
        assert entry["running_balance"] == 600.0
        assert entry["amount"] == 600.0

    def test_get_jar_history_not_found(self, client, db):
        """Returns 404 when category does not exist."""
        resp = client.get("/api/savings/jars/99999/history")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 8: POST /api/savings/rebalance
# ═══════════════════════════════════════════════════════════════════════════════

class TestRebalanceJars:
    """Tests for the jar rebalance endpoint."""

    def test_rebalance_success(self, client, db, savings_seed):
        """A valid rebalance (net zero) returns 200 with the new transaction."""
        emergency = savings_seed["emergency"]
        vacation = savings_seed["vacation"]

        resp = client.post("/api/savings/rebalance", json={
            "allocations": [
                {"category_id": emergency.id, "amount": 100.0},
                {"category_id": vacation.id,  "amount": -100.0},
            ]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["amount"] == 0.0
        assert data["description"] == "Jar Rebalance"

    def test_rebalance_creates_zero_amount_transaction(self, client, db, savings_seed):
        """Rebalance creates a $0 SavingsTransaction."""
        emergency = savings_seed["emergency"]
        vacation = savings_seed["vacation"]

        client.post("/api/savings/rebalance", json={
            "allocations": [
                {"category_id": emergency.id, "amount": 50.0},
                {"category_id": vacation.id,  "amount": -50.0},
            ]
        })
        db.expire_all()
        # The rebalance txn is the second transaction (seed has one)
        txns = db.query(SavingsTransaction).all()
        rebalance = next(t for t in txns if t.amount == 0.0)
        assert rebalance is not None
        assert rebalance.is_allocated is True

    def test_rebalance_non_zero_net_rejected(self, client, db, savings_seed):
        """Returns 400 when rebalance allocations don't net to zero."""
        emergency = savings_seed["emergency"]
        vacation = savings_seed["vacation"]

        resp = client.post("/api/savings/rebalance", json={
            "allocations": [
                {"category_id": emergency.id, "amount": 100.0},
                {"category_id": vacation.id,  "amount": -50.0},  # net = +50, not zero
            ]
        })
        assert resp.status_code == 400
        assert "net to $0.00" in resp.json()["detail"]

    def test_rebalance_empty_allocations_rejected(self, client, db, savings_seed):
        """Returns 400 when no allocations are provided."""
        resp = client.post("/api/savings/rebalance", json={"allocations": []})
        assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 9: GET + PUT /api/savings/templates/default
# ═══════════════════════════════════════════════════════════════════════════════

class TestDefaultTemplate:
    """Tests for saving and retrieving the default allocation template."""

    def test_get_template_empty(self, client, db):
        """Returns empty template when none exists."""
        resp = client.get("/api/savings/templates/default")
        assert resp.status_code == 200
        data = resp.json()
        assert data["template_id"] is None
        assert data["items"] == []

    def test_save_template_success(self, client, db, savings_seed):
        """Saving a template returns 200 with the saved items."""
        emergency = savings_seed["emergency"]
        vacation = savings_seed["vacation"]

        resp = client.put("/api/savings/templates/default", json={
            "name": "Paycheck",
            "items": [
                {"category_id": emergency.id, "amount": 600.0},
                {"category_id": vacation.id,  "amount": 400.0},
            ]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Paycheck"
        assert len(data["items"]) == 2

    def test_get_template_after_save(self, client, db, savings_seed):
        """GET returns the template that was previously saved."""
        emergency = savings_seed["emergency"]

        client.put("/api/savings/templates/default", json={
            "name": "Monthly",
            "items": [{"category_id": emergency.id, "amount": 500.0}]
        })

        resp = client.get("/api/savings/templates/default")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Monthly"
        assert len(data["items"]) == 1

    def test_save_template_replaces_existing(self, client, db, savings_seed):
        """Saving a second template replaces the first one."""
        emergency = savings_seed["emergency"]
        vacation = savings_seed["vacation"]

        client.put("/api/savings/templates/default", json={
            "name": "Old Template",
            "items": [{"category_id": emergency.id, "amount": 1000.0}]
        })
        client.put("/api/savings/templates/default", json={
            "name": "New Template",
            "items": [{"category_id": vacation.id, "amount": 500.0}]
        })

        resp = client.get("/api/savings/templates/default")
        data = resp.json()
        assert data["name"] == "New Template"
        assert len(data["items"]) == 1
        assert data["items"][0]["category_id"] == vacation.id

        # Only one template should exist
        db.expire_all()
        count = db.query(AllocationTemplate).count()
        assert count == 1

    def test_save_template_skips_zero_amounts(self, client, db, savings_seed):
        """Items with zero amount are silently skipped."""
        emergency = savings_seed["emergency"]
        vacation = savings_seed["vacation"]

        resp = client.put("/api/savings/templates/default", json={
            "name": "Template",
            "items": [
                {"category_id": emergency.id, "amount": 500.0},
                {"category_id": vacation.id,  "amount": 0.0},  # should be skipped
            ]
        })
        assert len(resp.json()["items"]) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 10: GET /api/savings/summary
# ═══════════════════════════════════════════════════════════════════════════════

class TestSavingsSummary:
    """Tests for the savings summary stats endpoint."""

    def test_summary_empty(self, client, db):
        """Returns zeros when no savings transactions exist."""
        resp = client.get("/api/savings/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["account_balance"] == 0.0
        assert data["jar_total"] == 0.0
        assert data["deposits_ytd"] == 0.0
        assert data["withdrawals_ytd"] == 0.0

    def test_summary_account_balance(self, client, db, savings_seed):
        """account_balance reflects sum of all savings transactions."""
        resp = client.get("/api/savings/summary")
        assert resp.json()["account_balance"] == 1000.0

    def test_summary_jar_total_matches_allocations(self, client, db, savings_seed):
        """jar_total reflects sum of all allocations across all jars."""
        resp = client.get("/api/savings/summary")
        assert resp.json()["jar_total"] == 1000.0

    def test_summary_keys_present(self, client, db):
        """Response includes all four expected keys."""
        resp = client.get("/api/savings/summary")
        data = resp.json()
        assert all(k in data for k in [
            "account_balance", "jar_total", "deposits_ytd", "withdrawals_ytd"
        ])
