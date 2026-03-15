"""
test_api_import.py — HTTP-level tests for the /api/import endpoint.

Tests the CSV upload and transaction import route via TestClient.
CSV content is built inline as strings — no real CSV files needed.
The endpoint reads formats.json from the project root, so the real
formats file is used (same as production).

Route covered:
  POST /api/import    import_transactions_endpoint
"""

import io
import pytest
from datetime import date
from unittest.mock import patch
from models import Transaction, Account


# ── CSV helpers ───────────────────────────────────────────────────────────────

def make_csv_file(content: str, filename: str = "test.csv"):
    """
    Wrap a CSV string as a file-like upload tuple for TestClient.

    Returns a dict suitable for the `files` parameter of client.post():
        files=make_csv_file("header\\nrow")
    """
    return {"file": (filename, io.BytesIO(content.encode("utf-8")), "text/csv")}


# ── Chase CSV format (single amount column, %m/%d/%Y) ─────────────────────────

CHASE_HEADER = "Transaction Date,Description,Category,Type,Amount,Memo"

def chase_row(date_str, description, amount, category="Shopping"):
    return f'{date_str},{description},{category},Sale,{amount},'


# ── Capital One CSV format (split debit/credit columns, %Y-%m-%d) ─────────────

CAPITALONE_HEADER = "Transaction Date,Posted Date,Card No.,Description,Category,Debit,Credit"

def capitalone_row(date_str, description, debit="", credit=""):
    return f'{date_str},{date_str},1234,{description},Shopping,{debit},{credit}'


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1: Validation errors (before any processing)
# ═══════════════════════════════════════════════════════════════════════════════

class TestImportValidation:
    """Tests for request validation before CSV processing begins."""

    def test_non_csv_file_rejected(self, client, db):
        """Returns 400 when the uploaded file is not a .csv."""
        resp = client.post(
            "/api/import",
            files={"file": ("transactions.xlsx", b"fake content", "application/octet-stream")},
            data={"bank": "chase"},
        )
        assert resp.status_code == 400
        assert "CSV" in resp.json()["detail"]

    def test_unknown_bank_rejected(self, client, db):
        """Returns 400 when the bank name is not in formats.json."""
        csv_content = f"{CHASE_HEADER}\n{chase_row('01/15/2025', 'STARBUCKS', -5.50)}"
        resp = client.post(
            "/api/import",
            files=make_csv_file(csv_content),
            data={"bank": "unknownbank"},
        )
        assert resp.status_code == 400
        assert "unknownbank" in resp.json()["detail"]

    def test_unknown_bank_lists_available_banks(self, client, db):
        """Error message for unknown bank includes list of valid banks."""
        csv_content = f"{CHASE_HEADER}\n{chase_row('01/15/2025', 'STARBUCKS', -5.50)}"
        resp = client.post(
            "/api/import",
            files=make_csv_file(csv_content),
            data={"bank": "fakebank"},
        )
        detail = resp.json()["detail"]
        # Should mention at least one real bank name
        assert any(bank in detail for bank in ["chase", "becu", "capitalone", "discover"])


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2: Successful imports
# ═══════════════════════════════════════════════════════════════════════════════

class TestImportSuccess:
    """Tests for successful CSV import scenarios."""

    def test_import_chase_creates_transactions(self, client, db):
        """Importing a valid Chase CSV creates the expected transactions."""
        csv_content = "\n".join([
            CHASE_HEADER,
            chase_row("01/15/2025", "STARBUCKS", -5.50),
            chase_row("01/16/2025", "AMAZON", -42.99),
            chase_row("01/17/2025", "PAYCHECK", 3000.00),
        ])
        resp = client.post(
            "/api/import",
            files=make_csv_file(csv_content),
            data={"bank": "chase"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] == 3
        assert data["skipped"] == 0
        assert data["duplicates_skipped"] == 0

    def test_import_creates_account_if_not_exists(self, client, db):
        """First import for a bank creates a new Account record."""
        csv_content = f"{CHASE_HEADER}\n{chase_row('01/15/2025', 'STARBUCKS', -5.50)}"
        client.post(
            "/api/import",
            files=make_csv_file(csv_content),
            data={"bank": "chase"},
        )
        account = db.query(Account).filter(Account.name == "chase").first()
        assert account is not None
        assert account.type == "imported"

    def test_import_reuses_existing_account(self, client, db):
        """Second import for same bank reuses the existing Account, not create a new one."""
        csv_content = f"{CHASE_HEADER}\n{chase_row('01/15/2025', 'STARBUCKS', -5.50)}"
        client.post("/api/import", files=make_csv_file(csv_content), data={"bank": "chase"})
        csv_content2 = f"{CHASE_HEADER}\n{chase_row('01/16/2025', 'AMAZON', -10.00)}"
        client.post("/api/import", files=make_csv_file(csv_content2), data={"bank": "chase"})

        accounts = db.query(Account).filter(Account.name == "chase").all()
        assert len(accounts) == 1

    def test_import_stores_correct_amount_sign(self, client, db):
        """Negative amounts are stored as negative, positive as positive."""
        csv_content = "\n".join([
            CHASE_HEADER,
            chase_row("01/15/2025", "PURCHASE", -50.00),
            chase_row("01/16/2025", "REFUND", 20.00),
        ])
        client.post("/api/import", files=make_csv_file(csv_content), data={"bank": "chase"})

        db.expire_all()
        txns = db.query(Transaction).order_by(Transaction.amount).all()
        amounts = [t.amount for t in txns]
        assert -50.00 in amounts
        assert 20.00 in amounts

    def test_import_capitalone_split_columns(self, client, db):
        """Capital One format with separate debit/credit columns imports correctly."""
        csv_content = "\n".join([
            CAPITALONE_HEADER,
            capitalone_row("2025-01-15", "WHOLE FOODS", debit="85.00"),
            capitalone_row("2025-01-16", "REFUND", credit="15.00"),
        ])
        resp = client.post(
            "/api/import",
            files=make_csv_file(csv_content),
            data={"bank": "capitalone"},
        )
        assert resp.status_code == 200
        assert resp.json()["imported"] == 2

    def test_import_capitalone_debit_is_negative(self, client, db):
        """Capital One debit column values are stored as negative amounts."""
        csv_content = f"{CAPITALONE_HEADER}\n{capitalone_row('2025-01-15', 'SAFEWAY', debit='100.00')}"
        client.post("/api/import", files=make_csv_file(csv_content), data={"bank": "capitalone"})

        db.expire_all()
        txn = db.query(Transaction).first()
        assert txn.amount == -100.00

    def test_import_capitalone_credit_is_positive(self, client, db):
        """Capital One credit column values are stored as positive amounts."""
        csv_content = f"{CAPITALONE_HEADER}\n{capitalone_row('2025-01-15', 'REFUND', credit='50.00')}"
        client.post("/api/import", files=make_csv_file(csv_content), data={"bank": "capitalone"})

        db.expire_all()
        txn = db.query(Transaction).first()
        assert txn.amount == 50.00

    def test_import_returns_uncategorized_count(self, client, db):
        """Response includes uncategorized_count reflecting newly imported transactions."""
        csv_content = "\n".join([
            CHASE_HEADER,
            chase_row("01/15/2025", "STARBUCKS", -5.50),
            chase_row("01/16/2025", "AMAZON", -42.99),
        ])
        resp = client.post("/api/import", files=make_csv_file(csv_content), data={"bank": "chase"})
        assert resp.status_code == 200
        # Both transactions are uncategorized after import
        assert resp.json()["uncategorized_count"] == 2


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3: Duplicate handling
# ═══════════════════════════════════════════════════════════════════════════════

class TestImportDuplicates:
    """Tests for duplicate detection during import."""

    def test_duplicate_transaction_is_skipped(self, client, db):
        """Importing the same transaction twice skips it the second time."""
        csv_content = f"{CHASE_HEADER}\n{chase_row('01/15/2025', 'STARBUCKS', -5.50)}"

        resp1 = client.post("/api/import", files=make_csv_file(csv_content), data={"bank": "chase"})
        resp2 = client.post("/api/import", files=make_csv_file(csv_content), data={"bank": "chase"})

        assert resp1.json()["imported"] == 1
        assert resp2.json()["duplicates_skipped"] == 1
        assert resp2.json()["imported"] == 0

    def test_duplicate_does_not_create_second_record(self, client, db):
        """After importing the same CSV twice, only one transaction exists in DB."""
        csv_content = f"{CHASE_HEADER}\n{chase_row('01/15/2025', 'STARBUCKS', -5.50)}"
        client.post("/api/import", files=make_csv_file(csv_content), data={"bank": "chase"})
        client.post("/api/import", files=make_csv_file(csv_content), data={"bank": "chase"})

        db.expire_all()
        count = db.query(Transaction).count()
        assert count == 1

    def test_similar_but_different_transactions_not_flagged_as_duplicate(self, client, db):
        """Transactions with same description but different amounts are not duplicates."""
        csv_content = "\n".join([
            CHASE_HEADER,
            chase_row("01/15/2025", "STARBUCKS", -5.50),
            chase_row("01/15/2025", "STARBUCKS", -6.75),  # same desc+date, different amount
        ])
        resp = client.post("/api/import", files=make_csv_file(csv_content), data={"bank": "chase"})
        assert resp.json()["imported"] == 2
        assert resp.json()["duplicates_skipped"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4: Auto-exclusion
# ═══════════════════════════════════════════════════════════════════════════════

class TestImportAutoExclusion:
    """Tests for keyword-based auto-exclusion during import.

    exclude_keywords.json is gitignored (contains personal data). Tests use
    unittest.mock.patch to inject a known keyword list so they work in CI
    without depending on any local config file.
    """

    def test_excluded_keyword_auto_excludes_transaction(self, client, db):
        """Transactions matching an exclude keyword are imported as excluded=True."""
        csv_content = f"{CHASE_HEADER}\n{chase_row('01/15/2025', 'DISCOVER PAYMENT', -500.00)}"
        with patch("routers.imports.load_exclude_keywords", return_value=["DISCOVER"]):
            resp = client.post("/api/import", files=make_csv_file(csv_content), data={"bank": "chase"})

        assert resp.status_code == 200
        assert resp.json()["auto_excluded"] == 1

        db.expire_all()
        txn = db.query(Transaction).first()
        assert txn.excluded is True

    def test_normal_transaction_not_auto_excluded(self, client, db):
        """Transactions not matching any exclude keyword are imported as excluded=False."""
        csv_content = f"{CHASE_HEADER}\n{chase_row('01/15/2025', 'STARBUCKS', -5.50)}"
        with patch("routers.imports.load_exclude_keywords", return_value=["DISCOVER"]):
            resp = client.post("/api/import", files=make_csv_file(csv_content), data={"bank": "chase"})

        assert resp.json()["auto_excluded"] == 0

        db.expire_all()
        txn = db.query(Transaction).first()
        assert txn.excluded is False

    def test_mixed_excluded_and_normal_transactions(self, client, db):
        """Import counts are correct when mix of normal and auto-excluded rows."""
        csv_content = "\n".join([
            CHASE_HEADER,
            chase_row("01/15/2025", "STARBUCKS", -5.50),           # normal
            chase_row("01/16/2025", "DISCOVER PAYMENT", -500.00),  # excluded
            chase_row("01/17/2025", "AMAZON", -42.99),             # normal
        ])
        with patch("routers.imports.load_exclude_keywords", return_value=["DISCOVER"]):
            resp = client.post("/api/import", files=make_csv_file(csv_content), data={"bank": "chase"})

        data = resp.json()
        assert data["imported"] == 3        # all 3 imported
        assert data["auto_excluded"] == 1   # 1 auto-excluded


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5: Edge cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestImportEdgeCases:
    """Tests for malformed rows and edge cases."""

    def test_empty_csv_imports_zero_transactions(self, client, db):
        """A CSV with only a header row imports zero transactions."""
        csv_content = CHASE_HEADER
        resp = client.post("/api/import", files=make_csv_file(csv_content), data={"bank": "chase"})
        assert resp.status_code == 200
        assert resp.json()["imported"] == 0

    def test_row_with_missing_date_is_skipped(self, client, db):
        """Rows with no date value are counted as skipped."""
        csv_content = "\n".join([
            CHASE_HEADER,
            chase_row("01/15/2025", "STARBUCKS", -5.50),  # valid
            ",NODATEROW,Shopping,Sale,-10.00,",            # no date
        ])
        resp = client.post("/api/import", files=make_csv_file(csv_content), data={"bank": "chase"})
        data = resp.json()
        assert data["imported"] == 1
        assert data["skipped"] == 1