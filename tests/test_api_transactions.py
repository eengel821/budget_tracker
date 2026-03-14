"""
test_api_transactions.py — HTTP-level tests for transaction API routes.

Tests every route in the transaction API using FastAPI's TestClient.
The `client` fixture (from conftest.py) wires the app to an in-memory
SQLite database, so these tests never touch the real database file.

Routes covered:
  PUT  /transactions/{id}/category       assign_category
  PATCH /api/transactions/{id}           patch_transaction
  DELETE /api/transactions/{id}          delete_transaction
  PUT  /api/transactions/{id}/exclude    set_transaction_excluded
  PUT  /api/transactions/{id}/unexclude  set_transaction_unexcluded
"""

import pytest
from datetime import date
from models import Transaction, Category


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1: PUT /transactions/{id}/category
# ═══════════════════════════════════════════════════════════════════════════════

class TestAssignCategory:
    """Tests for the assign_category route."""

    def test_assign_category_success(self, client, db, api_seed):
        """Assigning a valid category to a transaction returns 200 and the category name."""
        txn = api_seed["txn"]
        cat = api_seed["groceries"]

        resp = client.put(
            f"/transactions/{txn.id}/category",
            json={"category_id": cat.id},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["transaction_id"] == txn.id
        assert data["category_id"] == cat.id
        assert data["category_name"] == "Groceries"

    def test_assign_category_persists_to_db(self, client, db, api_seed):
        """After assignment, the transaction's category_id is updated in the database."""
        txn = api_seed["txn"]
        cat = api_seed["dining"]

        client.put(
            f"/transactions/{txn.id}/category",
            json={"category_id": cat.id},
        )

        db.refresh(txn)
        assert txn.category_id == cat.id

    def test_assign_category_overrides_existing(self, client, db, api_seed):
        """Assigning a new category to an already-categorized transaction replaces it."""
        txn = api_seed["txn"]
        txn.category_id = api_seed["groceries"].id
        db.commit()

        resp = client.put(
            f"/transactions/{txn.id}/category",
            json={"category_id": api_seed["dining"].id},
        )

        assert resp.status_code == 200
        db.refresh(txn)
        assert txn.category_id == api_seed["dining"].id

    def test_assign_category_transaction_not_found(self, client, db, api_seed):
        """Returns 404 when the transaction ID does not exist."""
        resp = client.put(
            "/transactions/99999/category",
            json={"category_id": api_seed["groceries"].id},
        )
        assert resp.status_code == 404
        assert "Transaction not found" in resp.json()["detail"]

    def test_assign_category_category_not_found(self, client, db, api_seed):
        """Returns 404 when the category ID does not exist."""
        txn = api_seed["txn"]
        resp = client.put(
            f"/transactions/{txn.id}/category",
            json={"category_id": 99999},
        )
        assert resp.status_code == 404
        assert "Category not found" in resp.json()["detail"]


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2: PATCH /api/transactions/{id}
# ═══════════════════════════════════════════════════════════════════════════════

class TestPatchTransaction:
    """Tests for the patch_transaction route."""

    def test_patch_description(self, client, db, api_seed):
        """Patching description updates it and returns the new value."""
        txn = api_seed["txn"]

        resp = client.patch(
            f"/api/transactions/{txn.id}",
            json={"description": "Updated description"},
        )

        assert resp.status_code == 200
        assert resp.json()["description"] == "Updated description"
        db.refresh(txn)
        assert txn.description == "Updated description"

    def test_patch_notes(self, client, db, api_seed):
        """Patching notes updates it and returns the new value."""
        txn = api_seed["txn"]

        resp = client.patch(
            f"/api/transactions/{txn.id}",
            json={"notes": "My note"},
        )

        assert resp.status_code == 200
        assert resp.json()["notes"] == "My note"
        db.refresh(txn)
        assert txn.notes == "My note"

    def test_patch_both_fields(self, client, db, api_seed):
        """Patching both fields at once updates both."""
        txn = api_seed["txn"]

        resp = client.patch(
            f"/api/transactions/{txn.id}",
            json={"description": "New desc", "notes": "New note"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["description"] == "New desc"
        assert data["notes"] == "New note"

    def test_patch_partial_leaves_other_field_unchanged(self, client, db, api_seed):
        """Patching only description leaves notes unchanged."""
        txn = api_seed["txn"]
        txn.notes = "existing note"
        db.commit()

        resp = client.patch(
            f"/api/transactions/{txn.id}",
            json={"description": "changed"},
        )

        assert resp.status_code == 200
        assert resp.json()["notes"] == "existing note"

    def test_patch_transaction_not_found(self, client, db, api_seed):
        """Returns 404 when the transaction ID does not exist."""
        resp = client.patch(
            "/api/transactions/99999",
            json={"description": "ghost"},
        )
        assert resp.status_code == 404
        assert "Transaction not found" in resp.json()["detail"]


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3: DELETE /api/transactions/{id}
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeleteTransaction:
    """Tests for the delete_transaction route."""

    def test_delete_success(self, client, db, api_seed):
        """Deleting an existing transaction returns 200 and a confirmation message."""
        txn = api_seed["txn"]
        txn_id = txn.id

        resp = client.delete(f"/api/transactions/{txn_id}")

        assert resp.status_code == 200
        assert str(txn_id) in resp.json()["message"]

    def test_delete_removes_from_db(self, client, db, api_seed):
        """After deletion, the transaction no longer exists in the database."""
        txn = api_seed["txn"]
        txn_id = txn.id

        client.delete(f"/api/transactions/{txn_id}")

        remaining = db.query(Transaction).filter(Transaction.id == txn_id).first()
        assert remaining is None

    def test_delete_not_found(self, client, db, api_seed):
        """Returns 404 when the transaction ID does not exist."""
        resp = client.delete("/api/transactions/99999")
        assert resp.status_code == 404
        assert "Transaction not found" in resp.json()["detail"]

    def test_delete_second_time_returns_404(self, client, db, api_seed):
        """Deleting the same transaction twice returns 404 on the second attempt."""
        txn = api_seed["txn"]
        client.delete(f"/api/transactions/{txn.id}")
        resp = client.delete(f"/api/transactions/{txn.id}")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4: PUT /api/transactions/{id}/exclude and /unexclude
# ═══════════════════════════════════════════════════════════════════════════════

class TestExcludeUnexclude:
    """Tests for the exclude and unexclude routes."""

    def test_exclude_success(self, client, db, api_seed):
        """Excluding a transaction returns 200 and sets excluded=True in db."""
        txn = api_seed["txn"]
        assert txn.excluded is False

        resp = client.put(f"/api/transactions/{txn.id}/exclude")

        assert resp.status_code == 200
        assert resp.json()["transaction_id"] == txn.id
        db.refresh(txn)
        assert txn.excluded is True

    def test_unexclude_success(self, client, db, api_seed):
        """Unexcluding a transaction returns 200 and sets excluded=False in db."""
        txn = api_seed["txn"]
        txn.excluded = True
        db.commit()

        resp = client.put(f"/api/transactions/{txn.id}/unexclude")

        assert resp.status_code == 200
        db.refresh(txn)
        assert txn.excluded is False

    def test_exclude_not_found(self, client, db, api_seed):
        """Returns 404 when the transaction ID does not exist."""
        resp = client.put("/api/transactions/99999/exclude")
        assert resp.status_code == 404

    def test_unexclude_not_found(self, client, db, api_seed):
        """Returns 404 when the transaction ID does not exist."""
        resp = client.put("/api/transactions/99999/unexclude")
        assert resp.status_code == 404

    def test_exclude_is_idempotent(self, client, db, api_seed):
        """Excluding an already-excluded transaction succeeds without error."""
        txn = api_seed["txn"]
        txn.excluded = True
        db.commit()

        resp = client.put(f"/api/transactions/{txn.id}/exclude")
        assert resp.status_code == 200
        db.refresh(txn)
        assert txn.excluded is True

    def test_exclude_then_unexclude_roundtrip(self, client, db, api_seed):
        """A full exclude → unexclude roundtrip leaves the transaction unexcluded."""
        txn = api_seed["txn"]

        client.put(f"/api/transactions/{txn.id}/exclude")
        db.refresh(txn)
        assert txn.excluded is True

        client.put(f"/api/transactions/{txn.id}/unexclude")
        db.refresh(txn)
        assert txn.excluded is False
