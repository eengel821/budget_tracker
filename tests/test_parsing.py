"""
test_parsing.py - Tests for the parse_amount() and parse_date() functions.

Verifies that amounts and dates are correctly extracted and normalized
from CSV rows for each supported bank format.
"""

import pytest
from datetime import date

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from import_transactions import parse_amount, parse_date


class TestParseAmountSingleColumn:
    """Tests for banks that use a single Amount column (Chase, Discover)."""

    def test_chase_debit_is_negative(self, formats):
        """Chase debit transactions should be stored as negative amounts."""
        row = {"Amount": "-7.00"}
        result = parse_amount(row, formats["chase"])
        assert result == -7.00

    def test_chase_credit_is_positive(self, formats):
        """Chase credit transactions should be stored as positive amounts."""
        row = {"Amount": "250.00"}
        result = parse_amount(row, formats["chase"])
        assert result == 250.00

    def test_discover_debit_is_negative(self, formats):
        """Discover debit transactions should be stored as negative amounts."""
        row = {"Amount": "-5.00"}
        result = parse_amount(row, formats["discover"])
        assert result == -5.00

    def test_discover_credit_is_positive(self, formats):
        """Discover credit/payment transactions should be stored as positive amounts."""
        row = {"Amount": "100.00"}
        result = parse_amount(row, formats["discover"])
        assert result == 100.00

    def test_handles_large_amount(self, formats):
        """parse_amount() should handle large transaction amounts correctly."""
        row = {"Amount": "-1500.99"}
        result = parse_amount(row, formats["chase"])
        assert result == -1500.99


class TestParseAmountSplitColumns:
    """Tests for banks that use separate Debit and Credit columns (Capital One, BECU)."""

    def test_capitalone_debit_is_negative(self, formats):
        """Capital One debit amounts should be converted to negative floats."""
        row = {"Debit": "15.92", "Credit": ""}
        result = parse_amount(row, formats["capitalone"])
        assert result == -15.92

    def test_capitalone_credit_is_positive(self, formats):
        """Capital One credit amounts should be stored as positive floats."""
        row = {"Debit": "", "Credit": "200.00"}
        result = parse_amount(row, formats["capitalone"])
        assert result == 200.00

    def test_becu_debit_is_negative(self, formats):
        """BECU debit amounts should be converted to negative floats."""
        row = {"Debit": "45.00", "Credit": ""}
        result = parse_amount(row, formats["becu"])
        assert result == -45.00

    def test_becu_credit_is_positive(self, formats):
        """BECU credit/deposit amounts should be stored as positive floats."""
        row = {"Debit": "", "Credit": "30"}
        result = parse_amount(row, formats["becu"])
        assert result == 30.00

    def test_empty_debit_and_credit_returns_zero(self, formats):
        """A row with both debit and credit empty should return 0.0."""
        row = {"Debit": "", "Credit": ""}
        result = parse_amount(row, formats["capitalone"])
        assert result == 0.0


class TestParseDate:
    """Tests for parse_date() across all supported bank date formats."""

    def test_chase_date_format(self, formats):
        """Chase dates in MM/DD/YYYY format should parse correctly."""
        row = {"Transaction Date": "02/18/2026"}
        result = parse_date(row, formats["chase"])
        assert result == date(2026, 2, 18)

    def test_discover_date_format(self, formats):
        """Discover dates in MM/DD/YYYY format should parse correctly."""
        row = {"Trans. Date": "01/18/2026"}
        result = parse_date(row, formats["discover"])
        assert result == date(2026, 1, 18)

    def test_capitalone_date_format(self, formats):
        """Capital One dates in YYYY-MM-DD format should parse correctly."""
        row = {"Transaction Date": "2026-02-20"}
        result = parse_date(row, formats["capitalone"])
        assert result == date(2026, 2, 20)

    def test_becu_date_format(self, formats):
        """BECU dates in M/D/YYYY format should parse correctly."""
        row = {"Date": "1/30/2026"}
        result = parse_date(row, formats["becu"])
        assert result == date(2026, 1, 30)

    def test_invalid_date_raises_value_error(self, formats):
        """An unparseable date string should raise a ValueError."""
        row = {"Transaction Date": "not-a-date"}
        with pytest.raises(ValueError):
            parse_date(row, formats["chase"])

    def test_date_returns_date_object(self, formats):
        """parse_date() should always return a datetime.date object, not a string."""
        row = {"Transaction Date": "02/18/2026"}
        result = parse_date(row, formats["chase"])
        assert isinstance(result, date)
