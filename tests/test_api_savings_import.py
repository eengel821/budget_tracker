"""
test_api_savings_import.py — HTTP-level tests for the /api/savings/import endpoint.

Tests the savings CSV upload route via TestClient. CSV content is built
inline as strings. The endpoint supports two banks (etrade, becu) with
different format definitions hardcoded inside the route.

Key differences from /api/import:
  - Only etrade and becu are valid banks
  - ETrade CSVs have preamble rows before the real header (header_marker)
  - Amount values may contain $ and , characters
  - No auto-exclusion logic
  - Creates Account with type="savings"

Route covered:
  POST /api/savings/import    import_savings_transactions
"""

import io
import pytest
from models import Account, SavingsTransaction


# ── CSV helpers ───────────────────────────────────────────────────────────────

def make_csv_file(content: str, filename: str = "savings.csv"):
    """Wrap a CSV string as a file-like upload tuple for TestClient."""
    return {"file": (filename, io.BytesIO(content.encode("utf-8")), "text/csv")}


# ── ETrade CSV format ─────────────────────────────────────────────────────────
# ETrade exports include preamble lines before the real header row.
# The route skips lines until it finds one starting with "TransactionDate".

ETRADE_PREAMBLE = (
    "For account: xxxxxx1234\n"
    "Account type: Individual\n"
    "\n"
)
ETRADE_HEADER = "TransactionDate,TransactionType,SecurityType,Symbol,Quantity,Amount,Price,Commission,Description"

def etrade_row(date_str, amount, description, txn_type="Dividend"):
    return f'"{date_str}","{txn_type}",,,"0","{amount}",,,"{description}"'


# ── BECU CSV format ───────────────────────────────────────────────────────────
# BECU has no preamble — header is the first row.

BECU_HEADER = "Date,Description,Amount,Balance"

def becu_row(date_str, description, amount):
    return f"{date_str},{description},{amount},10000.00"


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1: Validation errors
# ═══════════════════════════════════════════════════════════════════════════════

class TestSavingsImportValidation:
    """Tests for request validation before CSV processing begins."""

    def test_non_csv_file_rejected(self, client, db):
        """Returns 400 when the uploaded file is not a .csv."""
        resp = client.post(
            "/api/savings/import",
            files={"file": ("savings.xlsx", b"fake content", "application/octet-stream")},
            data={"bank": "etrade"},
        )
        assert resp.status_code == 400
        assert "CSV" in resp.json()["detail"]

    def test_unknown_bank_rejected(self, client, db):
        """Returns 400 when the bank is not in the savings formats."""
        csv_content = f"{BECU_HEADER}\n{becu_row('01/15/2026', 'Deposit', '500.00')}"
        resp = client.post(
            "/api/savings/import",
            files=make_csv_file(csv_content),
            data={"bank": "chase"},  # chase is not a savings import bank
        )
        assert resp.status_code == 400
        assert "chase" in resp.json()["detail"]

    def test_unknown_bank_error_mentions_savings(self, client, db):
        """Error message for unknown bank is specific to savings import."""
        csv_content = f"{BECU_HEADER}\n{becu_row('01/15/2026', 'Deposit', '500.00')}"
        resp = client.post(
            "/api/savings/import",
            files=make_csv_file(csv_content),
            data={"bank": "unknownbank"},
        )
        assert "savings import" in resp.json()["detail"].lower()


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2: BECU imports
# ═══════════════════════════════════════════════════════════════════════════════

class TestSavingsImportBECU:
    """Tests for BECU savings CSV imports."""

    def test_becu_import_success(self, client, db):
        """Importing a valid BECU CSV creates the expected transactions."""
        csv_content = "\n".join([
            BECU_HEADER,
            becu_row("01/15/2026", "Paycheck deposit", "1000.00"),
            becu_row("01/20/2026", "ATM withdrawal",   "-250.00"),
        ])
        resp = client.post(
            "/api/savings/import",
            files=make_csv_file(csv_content),
            data={"bank": "becu"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["imported"] == 2
        assert data["skipped"] == 0
        assert data["duplicates_skipped"] == 0

    def test_becu_creates_savings_account(self, client, db):
        """First BECU import creates an Account with type='savings'."""
        csv_content = f"{BECU_HEADER}\n{becu_row('01/15/2026', 'Deposit', '500.00')}"
        client.post("/api/savings/import", files=make_csv_file(csv_content), data={"bank": "becu"})

        db.expire_all()
        account = db.query(Account).filter(Account.name == "becu").first()
        assert account is not None
        assert account.type == "savings"

    def test_becu_deposit_is_positive(self, client, db):
        """Positive amounts are stored as positive."""
        csv_content = f"{BECU_HEADER}\n{becu_row('01/15/2026', 'Deposit', '1000.00')}"
        client.post("/api/savings/import", files=make_csv_file(csv_content), data={"bank": "becu"})

        db.expire_all()
        txn = db.query(SavingsTransaction).first()
        assert txn.amount == 1000.0

    def test_becu_withdrawal_is_negative(self, client, db):
        """Negative amounts are stored as negative."""
        csv_content = f"{BECU_HEADER}\n{becu_row('01/15/2026', 'Withdrawal', '-500.00')}"
        client.post("/api/savings/import", files=make_csv_file(csv_content), data={"bank": "becu"})

        db.expire_all()
        txn = db.query(SavingsTransaction).first()
        assert txn.amount == -500.0

    def test_becu_new_transactions_are_unallocated(self, client, db):
        """Imported transactions start as is_allocated=False."""
        csv_content = f"{BECU_HEADER}\n{becu_row('01/15/2026', 'Deposit', '500.00')}"
        client.post("/api/savings/import", files=make_csv_file(csv_content), data={"bank": "becu"})

        db.expire_all()
        txn = db.query(SavingsTransaction).first()
        assert txn.is_allocated is False

    def test_becu_reuses_existing_account(self, client, db):
        """Second BECU import reuses the existing account."""
        csv_content1 = f"{BECU_HEADER}\n{becu_row('01/15/2026', 'Deposit', '500.00')}"
        csv_content2 = f"{BECU_HEADER}\n{becu_row('01/16/2026', 'Deposit', '200.00')}"
        client.post("/api/savings/import", files=make_csv_file(csv_content1), data={"bank": "becu"})
        client.post("/api/savings/import", files=make_csv_file(csv_content2), data={"bank": "becu"})

        db.expire_all()
        accounts = db.query(Account).filter(Account.name == "becu").all()
        assert len(accounts) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3: ETrade imports (with preamble)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSavingsImportETrade:
    """Tests for ETrade savings CSV imports including preamble handling."""

    def test_etrade_import_with_preamble(self, client, db):
        """ETrade CSV with preamble rows is imported correctly."""
        csv_content = (
            ETRADE_PREAMBLE
            + ETRADE_HEADER + "\n"
            + etrade_row("01/15/26", "500.00", "Dividend payment") + "\n"
            + etrade_row("01/20/26", "-250.00", "ATM withdrawal")
        )
        resp = client.post(
            "/api/savings/import",
            files=make_csv_file(csv_content),
            data={"bank": "etrade"},
        )
        assert resp.status_code == 200
        assert resp.json()["imported"] == 2

    def test_etrade_without_preamble_also_works(self, client, db):
        """ETrade CSV without preamble still imports correctly."""
        csv_content = "\n".join([
            ETRADE_HEADER,
            etrade_row("01/15/26", "1000.00", "Paycheck"),
        ])
        resp = client.post(
            "/api/savings/import",
            files=make_csv_file(csv_content),
            data={"bank": "etrade"},
        )
        assert resp.status_code == 200
        assert resp.json()["imported"] == 1

    def test_etrade_amount_strips_dollar_sign(self, client, db):
        """Amounts with $ prefix are parsed correctly."""
        csv_content = "\n".join([
            ETRADE_HEADER,
            etrade_row("01/15/26", "$1,000.00", "Large deposit"),
        ])
        client.post("/api/savings/import", files=make_csv_file(csv_content), data={"bank": "etrade"})

        db.expire_all()
        txn = db.query(SavingsTransaction).first()
        assert txn.amount == 1000.0

    def test_etrade_amount_strips_comma(self, client, db):
        """Amounts with comma separators are parsed correctly."""
        csv_content = "\n".join([
            ETRADE_HEADER,
            etrade_row("01/15/26", "2,500.00", "Large deposit"),
        ])
        client.post("/api/savings/import", files=make_csv_file(csv_content), data={"bank": "etrade"})

        db.expire_all()
        txn = db.query(SavingsTransaction).first()
        assert txn.amount == 2500.0

    def test_etrade_creates_savings_account(self, client, db):
        """ETrade import creates an Account with type='savings'."""
        csv_content = f"{ETRADE_HEADER}\n{etrade_row('01/15/26', '500.00', 'Dividend')}"
        client.post("/api/savings/import", files=make_csv_file(csv_content), data={"bank": "etrade"})

        db.expire_all()
        account = db.query(Account).filter(Account.name == "etrade").first()
        assert account is not None
        assert account.type == "savings"


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4: Duplicate handling
# ═══════════════════════════════════════════════════════════════════════════════

class TestSavingsImportDuplicates:
    """Tests for duplicate detection in savings imports."""

    def test_duplicate_skipped(self, client, db):
        """Importing the same transaction twice skips it the second time."""
        csv_content = f"{BECU_HEADER}\n{becu_row('01/15/2026', 'Deposit', '500.00')}"

        resp1 = client.post("/api/savings/import", files=make_csv_file(csv_content), data={"bank": "becu"})
        resp2 = client.post("/api/savings/import", files=make_csv_file(csv_content), data={"bank": "becu"})

        assert resp1.json()["imported"] == 1
        assert resp2.json()["duplicates_skipped"] == 1
        assert resp2.json()["imported"] == 0

    def test_duplicate_does_not_create_second_record(self, client, db):
        """After importing the same CSV twice, only one transaction exists."""
        csv_content = f"{BECU_HEADER}\n{becu_row('01/15/2026', 'Deposit', '500.00')}"
        client.post("/api/savings/import", files=make_csv_file(csv_content), data={"bank": "becu"})
        client.post("/api/savings/import", files=make_csv_file(csv_content), data={"bank": "becu"})

        db.expire_all()
        assert db.query(SavingsTransaction).count() == 1

    def test_same_description_different_amount_not_duplicate(self, client, db):
        """Same description and date but different amount is not a duplicate."""
        csv_content = "\n".join([
            BECU_HEADER,
            becu_row("01/15/2026", "Deposit", "500.00"),
            becu_row("01/15/2026", "Deposit", "750.00"),
        ])
        resp = client.post("/api/savings/import", files=make_csv_file(csv_content), data={"bank": "becu"})
        assert resp.json()["imported"] == 2
        assert resp.json()["duplicates_skipped"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5: Edge cases
# ═══════════════════════════════════════════════════════════════════════════════

class TestSavingsImportEdgeCases:
    """Tests for malformed rows and edge cases."""

    def test_empty_csv_imports_zero(self, client, db):
        """A CSV with only a header row imports zero transactions."""
        resp = client.post(
            "/api/savings/import",
            files=make_csv_file(BECU_HEADER),
            data={"bank": "becu"},
        )
        assert resp.status_code == 200
        assert resp.json()["imported"] == 0

    def test_row_with_missing_date_is_skipped(self, client, db):
        """Rows with no date value are counted as skipped."""
        csv_content = "\n".join([
            BECU_HEADER,
            becu_row("01/15/2026", "Valid row", "500.00"),
            ",No date row,100.00,10000.00",
        ])
        resp = client.post("/api/savings/import", files=make_csv_file(csv_content), data={"bank": "becu"})
        assert resp.json()["imported"] == 1
        assert resp.json()["skipped"] == 1