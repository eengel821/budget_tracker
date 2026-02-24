"""
test_duplicate.py - Tests for the is_duplicate() function.

Verifies that duplicate detection correctly identifies existing transactions
and correctly returns False for transactions that are not duplicates.
"""

import pytest
from datetime import date

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from import_transactions import is_duplicate
from models import Transaction


class TestIsDuplicate:

    def test_returns_true_for_exact_duplicate(self, db, sample_transaction):
        """
        is_duplicate() should return True when a transaction with the same
        date, amount, and description already exists in the database.
        """
        result = is_duplicate(
            db,
            date=date(2026, 2, 18),
            amount=-7.00,
            description="SDOT PAYBYPHONE PARKING",
        )
        assert result is True

    def test_returns_false_for_different_date(self, db, sample_transaction):
        """
        is_duplicate() should return False when the date differs,
        even if amount and description match.
        """
        result = is_duplicate(
            db,
            date=date(2026, 2, 19),  # different date
            amount=-7.00,
            description="SDOT PAYBYPHONE PARKING",
        )
        assert result is False

    def test_returns_false_for_different_amount(self, db, sample_transaction):
        """
        is_duplicate() should return False when the amount differs,
        even if date and description match.
        """
        result = is_duplicate(
            db,
            date=date(2026, 2, 18),
            amount=-10.00,  # different amount
            description="SDOT PAYBYPHONE PARKING",
        )
        assert result is False

    def test_returns_false_for_different_description(self, db, sample_transaction):
        """
        is_duplicate() should return False when the description differs,
        even if date and amount match.
        """
        result = is_duplicate(
            db,
            date=date(2026, 2, 18),
            amount=-7.00,
            description="DIFFERENT DESCRIPTION",  # different description
        )
        assert result is False

    def test_returns_false_for_empty_database(self, db):
        """
        is_duplicate() should return False when the database has no transactions at all.
        """
        result = is_duplicate(
            db,
            date=date(2026, 2, 18),
            amount=-7.00,
            description="SDOT PAYBYPHONE PARKING",
        )
        assert result is False

    def test_returns_bool(self, db, sample_transaction):
        """is_duplicate() should always return a bool, not a SQLAlchemy object or None."""
        result = is_duplicate(
            db,
            date=date(2026, 2, 18),
            amount=-7.00,
            description="SDOT PAYBYPHONE PARKING",
        )
        assert isinstance(result, bool)

    def test_does_not_flag_same_description_different_amount(self, db, sample_account):
        """
        Two transactions with the same description but different amounts
        on the same day should not be flagged as duplicates.
        This covers cases like paying the same vendor twice for different amounts.
        """
        transaction = Transaction(
            date=date(2026, 2, 18),
            amount=-7.00,
            description="STARBUCKS",
            account_id=sample_account.id,
        )
        db.add(transaction)
        db.commit()

        result = is_duplicate(
            db,
            date=date(2026, 2, 18),
            amount=-5.50,  # different amount, same description and date
            description="STARBUCKS",
        )
        assert result is False
