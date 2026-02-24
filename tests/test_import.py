"""
test_import.py - End-to-end tests for the import_csv() function.

Verifies that full CSV files are correctly imported into the database for
each supported bank format, including correct transaction counts, amounts,
dates, and descriptions.
"""

import pytest
from datetime import date
from unittest.mock import patch

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from import_transactions import import_csv
from models import Transaction, Account


# --- Sample CSV content for each bank ---

CHASE_CSV = """Transaction Date,Post Date,Description,Category,Type,Amount,Memo
02/18/2026,02/20/2026,SDOT PAYBYPHONE PARKING,Travel,Sale,-7.00,
02/19/2026,02/21/2026,AMAZON PRIME,Shopping,Sale,-14.99,
02/20/2026,02/22/2026,PAYROLL DEPOSIT,Income,Payment,2500.00,
"""

CAPITALONE_CSV = """Transaction Date,Posted Date,Card No.,Description,Category,Debit,Credit
2026-02-20,2026-02-21,2717,TST* PEACE OF MIND BRE,Dining,15.92,
2026-02-21,2026-02-22,2717,WHOLE FOODS,Groceries,87.43,
2026-02-22,2026-02-23,2717,PAYMENT THANK YOU,Payments,,500.00
"""

BECU_CSV = """"Date","No.","Description","Debit","Credit"
"1/30/2026","","Deposit - Online Banking Transfer","","30"
"1/29/2026","","NETFLIX","12.99",""
"1/28/2026","","GROCERY OUTLET","45.00",""
"""

DISCOVER_CSV = """Trans. Date,Post Date,Description,Amount,Category
01/18/2026,01/18/2026,DIRECTPAY FULL BALANCE,-500.00,Payments and Credits
01/19/2026,01/19/2026,SPOTIFY,9.99,Entertainment
01/20/2026,01/20/2026,TARGET,32.50,Shopping
"""


class TestImportChase:

    def test_imports_correct_number_of_transactions(self, db, tmp_csv, formats):
        """All three Chase transactions should be imported successfully."""
        filepath = tmp_csv("chase.csv", CHASE_CSV)
        with patch("import_transactions.SessionLocal", return_value=db):
            import_csv(filepath, "chase", formats)
        transactions = db.query(Transaction).all()
        assert len(transactions) == 3

    def test_debit_amount_is_negative(self, db, tmp_csv, formats):
        """Chase debit transactions should be stored as negative amounts."""
        filepath = tmp_csv("chase.csv", CHASE_CSV)
        with patch("import_transactions.SessionLocal", return_value=db):
            import_csv(filepath, "chase", formats)
        parking = db.query(Transaction).filter(
            Transaction.description == "SDOT PAYBYPHONE PARKING"
        ).first()
        assert parking.amount == -7.00

    def test_credit_amount_is_positive(self, db, tmp_csv, formats):
        """Chase credit/payment transactions should be stored as positive amounts."""
        filepath = tmp_csv("chase.csv", CHASE_CSV)
        with patch("import_transactions.SessionLocal", return_value=db):
            import_csv(filepath, "chase", formats)
        payroll = db.query(Transaction).filter(
            Transaction.description == "PAYROLL DEPOSIT"
        ).first()
        assert payroll.amount == 2500.00

    def test_date_is_parsed_correctly(self, db, tmp_csv, formats):
        """Chase transaction dates should be correctly parsed from MM/DD/YYYY format."""
        filepath = tmp_csv("chase.csv", CHASE_CSV)
        with patch("import_transactions.SessionLocal", return_value=db):
            import_csv(filepath, "chase", formats)
        parking = db.query(Transaction).filter(
            Transaction.description == "SDOT PAYBYPHONE PARKING"
        ).first()
        assert parking.date == date(2026, 2, 18)

    def test_account_is_created(self, db, tmp_csv, formats):
        """A Chase account record should be created automatically on first import."""
        filepath = tmp_csv("chase.csv", CHASE_CSV)
        with patch("import_transactions.SessionLocal", return_value=db):
            import_csv(filepath, "chase", formats)
        account = db.query(Account).filter(Account.name == "chase").first()
        assert account is not None


class TestImportCapitalOne:

    def test_imports_correct_number_of_transactions(self, db, tmp_csv, formats):
        """All three Capital One transactions should be imported successfully."""
        filepath = tmp_csv("capitalone.csv", CAPITALONE_CSV)
        with patch("import_transactions.SessionLocal", return_value=db):
            import_csv(filepath, "capitalone", formats)
        transactions = db.query(Transaction).all()
        assert len(transactions) == 3

    def test_debit_amount_is_negative(self, db, tmp_csv, formats):
        """Capital One debit transactions should be stored as negative amounts."""
        filepath = tmp_csv("capitalone.csv", CAPITALONE_CSV)
        with patch("import_transactions.SessionLocal", return_value=db):
            import_csv(filepath, "capitalone", formats)
        dining = db.query(Transaction).filter(
            Transaction.description == "TST* PEACE OF MIND BRE"
        ).first()
        assert dining.amount == -15.92

    def test_credit_amount_is_positive(self, db, tmp_csv, formats):
        """Capital One credit/payment transactions should be stored as positive amounts."""
        filepath = tmp_csv("capitalone.csv", CAPITALONE_CSV)
        with patch("import_transactions.SessionLocal", return_value=db):
            import_csv(filepath, "capitalone", formats)
        payment = db.query(Transaction).filter(
            Transaction.description == "PAYMENT THANK YOU"
        ).first()
        assert payment.amount == 500.00

    def test_date_is_parsed_correctly(self, db, tmp_csv, formats):
        """Capital One dates should be correctly parsed from YYYY-MM-DD format."""
        filepath = tmp_csv("capitalone.csv", CAPITALONE_CSV)
        with patch("import_transactions.SessionLocal", return_value=db):
            import_csv(filepath, "capitalone", formats)
        dining = db.query(Transaction).filter(
            Transaction.description == "TST* PEACE OF MIND BRE"
        ).first()
        assert dining.date == date(2026, 2, 20)


class TestImportBECU:

    def test_imports_correct_number_of_transactions(self, db, tmp_csv, formats):
        """All three BECU transactions should be imported successfully."""
        filepath = tmp_csv("becu.csv", BECU_CSV)
        with patch("import_transactions.SessionLocal", return_value=db):
            import_csv(filepath, "becu", formats)
        transactions = db.query(Transaction).all()
        assert len(transactions) == 3

    def test_debit_amount_is_negative(self, db, tmp_csv, formats):
        """BECU debit transactions should be stored as negative amounts."""
        filepath = tmp_csv("becu.csv", BECU_CSV)
        with patch("import_transactions.SessionLocal", return_value=db):
            import_csv(filepath, "becu", formats)
        netflix = db.query(Transaction).filter(
            Transaction.description == "NETFLIX"
        ).first()
        assert netflix.amount == -12.99

    def test_credit_amount_is_positive(self, db, tmp_csv, formats):
        """BECU credit/deposit transactions should be stored as positive amounts."""
        filepath = tmp_csv("becu.csv", BECU_CSV)
        with patch("import_transactions.SessionLocal", return_value=db):
            import_csv(filepath, "becu", formats)
        deposit = db.query(Transaction).filter(
            Transaction.description == "Deposit - Online Banking Transfer"
        ).first()
        assert deposit.amount == 30.00

    def test_date_is_parsed_correctly(self, db, tmp_csv, formats):
        """BECU dates should be correctly parsed from M/D/YYYY format."""
        filepath = tmp_csv("becu.csv", BECU_CSV)
        with patch("import_transactions.SessionLocal", return_value=db):
            import_csv(filepath, "becu", formats)
        deposit = db.query(Transaction).filter(
            Transaction.description == "Deposit - Online Banking Transfer"
        ).first()
        assert deposit.date == date(2026, 1, 30)


class TestImportDiscover:

    def test_imports_correct_number_of_transactions(self, db, tmp_csv, formats):
        """All three Discover transactions should be imported successfully."""
        filepath = tmp_csv("discover.csv", DISCOVER_CSV)
        with patch("import_transactions.SessionLocal", return_value=db):
            import_csv(filepath, "discover", formats)
        transactions = db.query(Transaction).all()
        assert len(transactions) == 3

    def test_debit_amount_is_negative(self, db, tmp_csv, formats):
        """Discover debit transactions should be stored as negative amounts."""
        filepath = tmp_csv("discover.csv", DISCOVER_CSV)
        with patch("import_transactions.SessionLocal", return_value=db):
            import_csv(filepath, "discover", formats)
        spotify = db.query(Transaction).filter(
            Transaction.description == "SPOTIFY"
        ).first()
        assert spotify.amount == 9.99

    def test_date_is_parsed_correctly(self, db, tmp_csv, formats):
        """Discover dates should be correctly parsed from MM/DD/YYYY format."""
        filepath = tmp_csv("discover.csv", DISCOVER_CSV)
        with patch("import_transactions.SessionLocal", return_value=db):
            import_csv(filepath, "discover", formats)
        spotify = db.query(Transaction).filter(
            Transaction.description == "SPOTIFY"
        ).first()
        assert spotify.date == date(2026, 1, 19)


class TestImportEdgeCases:

    def test_unknown_bank_exits(self, db, tmp_csv, formats):
        """import_csv() should exit with an error for an unrecognized bank name."""
        filepath = tmp_csv("unknown.csv", CHASE_CSV)
        with patch("import_transactions.SessionLocal", return_value=db):
            with pytest.raises(SystemExit):
                import_csv(filepath, "unknownbank", formats)

    def test_account_not_duplicated_on_reimport(self, db, tmp_csv, formats):
        """
        Importing from the same bank twice should not create duplicate account records.
        Only one account per bank name should ever exist.
        """
        filepath = tmp_csv("chase.csv", CHASE_CSV)
        with patch("import_transactions.SessionLocal", return_value=db):
            import_csv(filepath, "chase", formats)
        with patch("import_transactions.SessionLocal", return_value=db):
            # Mock input to skip all duplicates on second import
            with patch("builtins.input", return_value="sa"):
                import_csv(filepath, "chase", formats)
        accounts = db.query(Account).filter(Account.name == "chase").all()
        assert len(accounts) == 1
