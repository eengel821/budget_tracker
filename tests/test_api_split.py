"""
test_api_split.py — HTTP-level tests for split and unsplit transaction routes.

Tests the full validation and behaviour of the split API via TestClient.
The underlying split logic (budget aggregation correctness) is covered in
test_budget.py. These tests focus on the HTTP contract: status codes,
response shapes, DB side effects, and all validation error paths.

Routes covered:
  POST   /api/transactions/{id}/split    split_transaction
  DELETE /api/transactions/{id}/split    unsplit_transaction
"""

import pytest
from datetime import date
from models import Transaction, Category


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_txn(db, seed, *, amount, description="TEST TXN"):
    """Create and commit a single transaction, return it."""
    txn = Transaction(
        date=date(2025, 3, 15),
        amount=amount,
        description=description,
        excluded=False,
        account_id=seed["acct"].id,
        category_id=None,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


def split_payload(splits):
    """Build a split request body from a list of (amount, category_id) tuples."""
    return {
        "splits": [
            {"amount": amt, "category_id": cat_id}
            for amt, cat_id in splits
        ]
    }


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1: POST /api/transactions/{id}/split — success cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestSplitSuccess:
    """Happy-path tests for splitting transactions."""

    def test_split_debit_into_two_expense_categories(self, client, db, api_seed):
        """Splitting a debit into two expense categories returns 200 with two children."""
        txn = make_txn(db, api_seed, amount=-150.0)
        groceries = api_seed["groceries"]
        dining = api_seed["dining"]

        resp = client.post(
            f"/api/transactions/{txn.id}/split",
            json=split_payload([(-100.0, groceries.id), (-50.0, dining.id)]),
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["is_split"] is True
        assert data["parent_id"] == txn.id
        assert len(data["splits"]) == 2

    def test_split_sets_parent_is_split_true(self, client, db, api_seed):
        """After splitting, the parent transaction has is_split=True in the DB."""
        txn = make_txn(db, api_seed, amount=-150.0)
        resp = client.post(
            f"/api/transactions/{txn.id}/split",
            json=split_payload([(-100.0, api_seed["groceries"].id), (-50.0, api_seed["dining"].id)]),
        )
        assert resp.status_code == 200
        db.refresh(txn)
        assert txn.is_split is True

    def test_split_creates_excluded_children(self, client, db, api_seed):
        """Children are created with excluded=True so they don't double-count."""
        txn = make_txn(db, api_seed, amount=-150.0)
        client.post(
            f"/api/transactions/{txn.id}/split",
            json=split_payload([(-100.0, api_seed["groceries"].id), (-50.0, api_seed["dining"].id)]),
        )
        children = db.query(Transaction).filter(Transaction.parent_id == txn.id).all()
        assert len(children) == 2
        assert all(c.excluded is True for c in children)

    def test_split_children_have_correct_amounts_and_signs(self, client, db, api_seed):
        """Children receive the correct signed amounts matching the parent sign."""
        txn = make_txn(db, api_seed, amount=-200.0)
        client.post(
            f"/api/transactions/{txn.id}/split",
            json=split_payload([(-120.0, api_seed["groceries"].id), (-80.0, api_seed["dining"].id)]),
        )
        children = db.query(Transaction).filter(Transaction.parent_id == txn.id).all()
        amounts = sorted(c.amount for c in children)
        assert amounts == [-120.0, -80.0]

    def test_split_credit_into_two_categories(self, client, db, api_seed):
        """A credit (positive) transaction can be split into positive children."""
        txn = make_txn(db, api_seed, amount=150.0)
        resp = client.post(
            f"/api/transactions/{txn.id}/split",
            json=split_payload([(100.0, api_seed["groceries"].id), (50.0, api_seed["dining"].id)]),
        )
        assert resp.status_code == 200
        children = db.query(Transaction).filter(Transaction.parent_id == txn.id).all()
        assert all(c.amount > 0 for c in children)

    def test_split_into_three_lines(self, client, db, api_seed):
        """Splitting into more than two lines is supported."""
        txn = make_txn(db, api_seed, amount=-300.0)
        resp = client.post(
            f"/api/transactions/{txn.id}/split",
            json=split_payload([
                (-100.0, api_seed["groceries"].id),
                (-100.0, api_seed["dining"].id),
                (-100.0, api_seed["savings"].id),
            ]),
        )
        assert resp.status_code == 200
        assert len(resp.json()["splits"]) == 3

    def test_split_response_includes_category_names(self, client, db, api_seed):
        """Response includes category_name for each child split."""
        txn = make_txn(db, api_seed, amount=-150.0)
        resp = client.post(
            f"/api/transactions/{txn.id}/split",
            json=split_payload([(-100.0, api_seed["groceries"].id), (-50.0, api_seed["dining"].id)]),
        )
        names = {s["category_name"] for s in resp.json()["splits"]}
        assert "Groceries" in names
        assert "Dining" in names

    def test_split_into_savings_category(self, client, db, api_seed):
        """Debit can be split into a savings category."""
        txn = make_txn(db, api_seed, amount=-200.0)
        resp = client.post(
            f"/api/transactions/{txn.id}/split",
            json=split_payload([(-150.0, api_seed["groceries"].id), (-50.0, api_seed["savings"].id)]),
        )
        assert resp.status_code == 200

    def test_resplit_replaces_existing_children(self, client, db, api_seed):
        """Re-splitting a transaction replaces old children with new ones."""
        txn = make_txn(db, api_seed, amount=-150.0)

        # First split: -100 Groceries, -50 Dining
        client.post(
            f"/api/transactions/{txn.id}/split",
            json=split_payload([(-100.0, api_seed["groceries"].id), (-50.0, api_seed["dining"].id)]),
        )

        # Re-split: -90 Groceries, -60 Emergency Fund
        resp = client.post(
            f"/api/transactions/{txn.id}/split",
            json=split_payload([(-90.0, api_seed["groceries"].id), (-60.0, api_seed["savings"].id)]),
        )

        assert resp.status_code == 200
        db.expire_all()
        new_children = db.query(Transaction).filter(Transaction.parent_id == txn.id).all()

        # Should have exactly 2 children with the new amounts
        assert len(new_children) == 2
        amounts = sorted(c.amount for c in new_children)
        assert amounts == [-90.0, -60.0]

        # Old Dining child should be gone — no child in Dining category
        cat_ids = {c.category_id for c in new_children}
        assert api_seed["dining"].id not in cat_ids

        # New savings child should be present
        assert api_seed["savings"].id in cat_ids


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2: POST /api/transactions/{id}/split — validation errors
# ═══════════════════════════════════════════════════════════════════════════════

class TestSplitValidationErrors:
    """Tests for all 400/404 error paths in the split route."""

    def test_split_transaction_not_found(self, client, db, api_seed):
        """Returns 404 when the transaction does not exist."""
        resp = client.post(
            "/api/transactions/99999/split",
            json=split_payload([(-100.0, api_seed["groceries"].id), (-50.0, api_seed["dining"].id)]),
        )
        assert resp.status_code == 404
        assert "Transaction not found" in resp.json()["detail"]

    def test_split_child_transaction_rejected(self, client, db, api_seed):
        """Cannot split a child transaction (one that has a parent_id)."""
        parent = make_txn(db, api_seed, amount=-150.0)
        client.post(
            f"/api/transactions/{parent.id}/split",
            json=split_payload([(-100.0, api_seed["groceries"].id), (-50.0, api_seed["dining"].id)]),
        )
        children = db.query(Transaction).filter(Transaction.parent_id == parent.id).all()
        child = children[0]

        resp = client.post(
            f"/api/transactions/{child.id}/split",
            json=split_payload([(-60.0, api_seed["groceries"].id), (-40.0, api_seed["dining"].id)]),
        )
        assert resp.status_code == 400
        assert "child" in resp.json()["detail"].lower()

    def test_split_requires_at_least_two_lines(self, client, db, api_seed):
        """Submitting only one split line returns 400."""
        txn = make_txn(db, api_seed, amount=-150.0)
        resp = client.post(
            f"/api/transactions/{txn.id}/split",
            json={"splits": [{"amount": -150.0, "category_id": api_seed["groceries"].id}]},
        )
        assert resp.status_code == 400
        assert "2" in resp.json()["detail"]

    def test_split_amounts_must_sum_to_parent_total(self, client, db, api_seed):
        """Returns 400 when split amounts don't add up to the parent total."""
        txn = make_txn(db, api_seed, amount=-150.0)
        resp = client.post(
            f"/api/transactions/{txn.id}/split",
            json=split_payload([(-100.0, api_seed["groceries"].id), (-40.0, api_seed["dining"].id)]),
        )
        assert resp.status_code == 400
        assert "must equal" in resp.json()["detail"]

    def test_split_amounts_cannot_exceed_parent_total(self, client, db, api_seed):
        """Returns 400 when split amounts exceed the parent total."""
        txn = make_txn(db, api_seed, amount=-150.0)
        resp = client.post(
            f"/api/transactions/{txn.id}/split",
            json=split_payload([(-100.0, api_seed["groceries"].id), (-60.0, api_seed["dining"].id)]),
        )
        assert resp.status_code == 400

    def test_debit_split_into_income_category_rejected(self, client, db, api_seed):
        """A debit transaction cannot be split into an income category."""
        txn = make_txn(db, api_seed, amount=-150.0)
        resp = client.post(
            f"/api/transactions/{txn.id}/split",
            json=split_payload([(-100.0, api_seed["groceries"].id), (-50.0, api_seed["income"].id)]),
        )
        assert resp.status_code == 400
        assert "income" in resp.json()["detail"].lower()

    def test_child_sign_must_match_parent_sign(self, client, db, api_seed):
        """Returns 400 when a child amount has the wrong sign for the parent."""
        txn = make_txn(db, api_seed, amount=-150.0)
        resp = client.post(
            f"/api/transactions/{txn.id}/split",
            # Positive child for a negative parent
            json=split_payload([(100.0, api_seed["groceries"].id), (50.0, api_seed["dining"].id)]),
        )
        assert resp.status_code == 400
        assert "sign" in resp.json()["detail"].lower()

    def test_credit_into_income_category_allowed(self, client, db, api_seed):
        """A credit transaction CAN be split into an income category."""
        txn = make_txn(db, api_seed, amount=150.0)
        resp = client.post(
            f"/api/transactions/{txn.id}/split",
            json=split_payload([(100.0, api_seed["groceries"].id), (50.0, api_seed["income"].id)]),
        )
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3: DELETE /api/transactions/{id}/split — unsplit
# ═══════════════════════════════════════════════════════════════════════════════

class TestUnsplit:
    """Tests for the unsplit route."""

    def test_unsplit_success(self, client, db, api_seed):
        """Unsplitting a split transaction returns 200 and is_split=False."""
        txn = make_txn(db, api_seed, amount=-150.0)
        client.post(
            f"/api/transactions/{txn.id}/split",
            json=split_payload([(-100.0, api_seed["groceries"].id), (-50.0, api_seed["dining"].id)]),
        )

        resp = client.delete(f"/api/transactions/{txn.id}/split")

        assert resp.status_code == 200
        assert resp.json()["is_split"] is False

    def test_unsplit_removes_children_from_db(self, client, db, api_seed):
        """After unsplitting, no child transactions remain in the DB."""
        txn = make_txn(db, api_seed, amount=-150.0)
        client.post(
            f"/api/transactions/{txn.id}/split",
            json=split_payload([(-100.0, api_seed["groceries"].id), (-50.0, api_seed["dining"].id)]),
        )

        client.delete(f"/api/transactions/{txn.id}/split")

        children = db.query(Transaction).filter(Transaction.parent_id == txn.id).all()
        assert len(children) == 0

    def test_unsplit_sets_is_split_false_in_db(self, client, db, api_seed):
        """After unsplitting, the parent has is_split=False in the DB."""
        txn = make_txn(db, api_seed, amount=-150.0)
        client.post(
            f"/api/transactions/{txn.id}/split",
            json=split_payload([(-100.0, api_seed["groceries"].id), (-50.0, api_seed["dining"].id)]),
        )

        client.delete(f"/api/transactions/{txn.id}/split")

        db.refresh(txn)
        assert txn.is_split is False

    def test_unsplit_reports_deleted_count(self, client, db, api_seed):
        """Response message mentions how many children were deleted."""
        txn = make_txn(db, api_seed, amount=-300.0)
        client.post(
            f"/api/transactions/{txn.id}/split",
            json=split_payload([
                (-100.0, api_seed["groceries"].id),
                (-100.0, api_seed["dining"].id),
                (-100.0, api_seed["savings"].id),
            ]),
        )

        resp = client.delete(f"/api/transactions/{txn.id}/split")

        assert "3" in resp.json()["message"]

    def test_unsplit_transaction_not_found(self, client, db, api_seed):
        """Returns 404 when the transaction does not exist."""
        resp = client.delete("/api/transactions/99999/split")
        assert resp.status_code == 404
        assert "Transaction not found" in resp.json()["detail"]

    def test_unsplit_non_split_transaction_rejected(self, client, db, api_seed):
        """Returns 400 when trying to unsplit a transaction that isn't split."""
        txn = make_txn(db, api_seed, amount=-150.0)
        resp = client.delete(f"/api/transactions/{txn.id}/split")
        assert resp.status_code == 400
        assert "not split" in resp.json()["detail"].lower()

    def test_split_then_unsplit_then_resplit(self, client, db, api_seed):
        """A full split → unsplit → re-split roundtrip works correctly."""
        txn = make_txn(db, api_seed, amount=-150.0)

        # Split
        client.post(
            f"/api/transactions/{txn.id}/split",
            json=split_payload([(-100.0, api_seed["groceries"].id), (-50.0, api_seed["dining"].id)]),
        )
        db.refresh(txn)
        assert txn.is_split is True

        # Unsplit
        client.delete(f"/api/transactions/{txn.id}/split")
        db.refresh(txn)
        assert txn.is_split is False
        assert db.query(Transaction).filter(Transaction.parent_id == txn.id).count() == 0

        # Re-split with different amounts
        resp = client.post(
            f"/api/transactions/{txn.id}/split",
            json=split_payload([(-75.0, api_seed["groceries"].id), (-75.0, api_seed["savings"].id)]),
        )
        assert resp.status_code == 200
        db.refresh(txn)
        assert txn.is_split is True
        assert db.query(Transaction).filter(Transaction.parent_id == txn.id).count() == 2