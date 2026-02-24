"""
test_formats.py - Tests for the load_formats() function.

Verifies that format definitions are correctly loaded from formats.json
and that errors are handled gracefully when the file is missing or malformed.
"""

import json
import pytest
from pathlib import Path
import import_transactions
from import_transactions import load_formats
from unittest.mock import patch

# Import the function we are testing
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

# Point FORMATS_FILE to the absolute path of formats.json in the project root
import_transactions.FORMATS_FILE = Path(__file__).resolve().parent.parent / "formats.json"

EXPECTED_BANKS = {"chase", "capitalone", "becu", "discover"}
REQUIRED_KEYS = {"date_col", "description_col", "category_col", "amount_col", "debit_col", "credit_col", "date_format"}


class TestLoadFormats:

    def test_returns_dictionary(self):
        """load_formats() should return a dictionary."""
        result = load_formats()
        assert isinstance(result, dict)

    def test_contains_all_expected_banks(self):
        """formats.json should contain an entry for every supported bank."""
        result = load_formats()
        assert EXPECTED_BANKS.issubset(result.keys()), (
            f"Missing banks: {EXPECTED_BANKS - result.keys()}"
        )

    def test_each_bank_has_required_keys(self):
        """Every bank format should define all required column mapping keys."""
        result = load_formats()
        for bank, fmt in result.items():
            missing = REQUIRED_KEYS - fmt.keys()
            assert not missing, f"Bank '{bank}' is missing keys: {missing}"

    def test_chase_uses_single_amount_column(self):
        """Chase format should use a single amount column, not split debit/credit."""
        result = load_formats()
        assert result["chase"]["amount_col"] is not None
        assert result["chase"]["debit_col"] is None
        assert result["chase"]["credit_col"] is None

    def test_discover_uses_single_amount_column(self):
        """Discover format should use a single amount column, not split debit/credit."""
        result = load_formats()
        assert result["discover"]["amount_col"] is not None
        assert result["discover"]["debit_col"] is None
        assert result["discover"]["credit_col"] is None

    def test_capitalone_uses_split_debit_credit_columns(self):
        """Capital One format should use split debit/credit columns, not a single amount."""
        result = load_formats()
        assert result["capitalone"]["amount_col"] is None
        assert result["capitalone"]["debit_col"] is not None
        assert result["capitalone"]["credit_col"] is not None

    def test_becu_uses_split_debit_credit_columns(self):
        """BECU format should use split debit/credit columns, not a single amount."""
        result = load_formats()
        assert result["becu"]["amount_col"] is None
        assert result["becu"]["debit_col"] is not None
        assert result["becu"]["credit_col"] is not None

    def test_date_formats_are_valid_strings(self):
        """Every bank format should define a non-empty date format string."""
        result = load_formats()
        for bank, fmt in result.items():
            assert isinstance(fmt["date_format"], str), f"Bank '{bank}' date_format is not a string"
            assert len(fmt["date_format"]) > 0, f"Bank '{bank}' date_format is empty"

    def test_exits_when_formats_file_missing(self):
        """load_formats() should call sys.exit() if formats.json cannot be found."""
        with patch("import_transactions.FORMATS_FILE", Path("./nonexistent_formats.json")):
            with pytest.raises(SystemExit):
                load_formats()
