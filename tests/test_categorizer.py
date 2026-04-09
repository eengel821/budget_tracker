"""
test_categorizer.py - Tests for the categorization engine in categorizer.py

Covers keyword matching, history matching, confidence thresholds, the combined
categorize_transaction() function, and the bulk categorize_all_uncategorized()
function.

Phase 1 additions cover:
  - Specificity ordering (longer keywords beat shorter ones)
  - Negative keywords (exclude_if_contains)
  - Description normalization (store numbers, noise stripped before matching)
  - Short keyword whole-word matching (prevents "PSE" matching "EXPENSE")
  - Priority field overrides
"""

import pytest
from datetime import date
from unittest.mock import patch
from collections import Counter

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from categorizer import (
    match_by_keywords,
    match_by_history,
    get_category_by_name,
    categorize_transaction,
    categorize_all_uncategorized,
    normalize_description,
    HISTORY_CONFIDENCE_THRESHOLD,
    HISTORY_MIN_MATCHES,
)
from models import Transaction, Category, Account


# --- Shared sample keywords for tests ---

SAMPLE_KEYWORDS = [
    {"keyword": "STARBUCKS", "category": "Coffee Shops", "match_type": "contains"},
    {"keyword": "WHOLE FOODS", "category": "Groceries", "match_type": "contains"},
    {"keyword": "NETFLIX", "category": "Subscription", "match_type": "contains"},
    {"keyword": "SHELL", "category": "Gas", "match_type": "contains"},
    {"keyword": "HOME DEPOT", "category": "Home Improvements", "match_type": "contains"},
    {"keyword": "TST*", "category": "Restaurants", "match_type": "contains"},
]

# Extended keyword set used by Phase 1 specificity and negative keyword tests.
# These mirror the real keywords.json structure including the new fields.
PHASE1_KEYWORDS = [
    # Specific gas rules — priority 10 so they are checked first
    {"keyword": "COSTCO GAS", "category": "Gas", "match_type": "contains", "priority": 10},
    {"keyword": "FRED MEYER GAS", "category": "Gas", "match_type": "contains", "priority": 10},
    # Amazon Prime must beat Amazon
    {"keyword": "AMAZON PRIME", "category": "Subscription", "match_type": "contains", "priority": 10},
    # General rules with negative keywords
    {"keyword": "COSTCO", "category": "Groceries", "match_type": "contains",
     "exclude_if_contains": ["GAS", "TIRE", "OPTICAL", "PHARMACY"]},
    {"keyword": "FRED MEYER", "category": "Groceries", "match_type": "contains",
     "exclude_if_contains": ["GAS", "FUEL"]},
    {"keyword": "AMAZON", "category": "Home Supplies", "match_type": "contains",
     "exclude_if_contains": ["PRIME"]},
    # Short keyword — whole-word matching applied automatically
    {"keyword": "PSE", "category": "Electric", "match_type": "contains", "priority": 90},
    # Standard rules
    {"keyword": "STARBUCKS", "category": "Coffee Shops", "match_type": "contains"},
    {"keyword": "NETFLIX", "category": "Subscription", "match_type": "contains"},
    {"keyword": "HOME DEPOT", "category": "Home Improvements", "match_type": "contains"},
    {"keyword": "SHELL", "category": "Gas", "match_type": "contains"},
    {"keyword": "WHOLE FOODS", "category": "Groceries", "match_type": "contains"},
]


# --- Fixtures ---

@pytest.fixture
def sample_categories(db):
    """
    Insert a standard set of categories into the test database.
    Returns a dict mapping category name to Category object for easy lookup.
    """
    names = [
        "Coffee Shops", "Groceries", "Subscription", "Gas",
        "Restaurants", "Home Improvements", "Misc", "Electric",
        "Home Supplies",
    ]
    categories = {}
    for name in names:
        category = Category(name=name)
        db.add(category)
        db.commit()
        db.refresh(category)
        categories[name] = category
    return categories


@pytest.fixture
def sample_account(db):
    """Insert a test account for creating transactions."""
    account = Account(name="chase", type="imported")
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def make_transaction(db, account, description, category_id=None, amount=-10.00):
    """
    Helper to create and insert a transaction into the test database.
    Returns the created Transaction object.
    """
    t = Transaction(
        date=date(2026, 1, 15),
        amount=amount,
        description=description,
        account_id=account.id,
        category_id=category_id,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


# --- Tests for match_by_keywords() ---

class TestMatchByKeywords:

    def test_matches_exact_keyword(self):
        """A description containing a keyword should return the mapped category."""
        result = match_by_keywords("STARBUCKS #1234", SAMPLE_KEYWORDS)
        assert result == "Coffee Shops"

    def test_matching_is_case_insensitive(self):
        """Keyword matching should work regardless of description case."""
        result = match_by_keywords("starbucks downtown", SAMPLE_KEYWORDS)
        assert result == "Coffee Shops"

    def test_matches_keyword_anywhere_in_description(self):
        """A keyword appearing anywhere in the description should match."""
        result = match_by_keywords("PURCHASE AT WHOLE FOODS MARKET", SAMPLE_KEYWORDS)
        assert result == "Groceries"

    def test_returns_none_for_no_match(self):
        """A description with no matching keyword should return None."""
        result = match_by_keywords("UNKNOWN MERCHANT XYZ", SAMPLE_KEYWORDS)
        assert result is None

    def test_returns_none_for_empty_description(self):
        """An empty description string should return None."""
        result = match_by_keywords("", SAMPLE_KEYWORDS)
        assert result is None

    def test_returns_none_for_empty_keyword_list(self):
        """An empty keyword list should always return None."""
        result = match_by_keywords("STARBUCKS", [])
        assert result is None

    def test_longer_keyword_beats_shorter_keyword(self):
        """
        Under specificity ordering, a longer keyword should win over a shorter
        one regardless of their order in the list. This replaces the old
        'first match wins' behavior.

        Previously: "STAR" beat "STARBUCKS" because it came first.
        Now: "STARBUCKS" beats "STAR" because it is more specific (longer).
        """
        keywords = [
            {"keyword": "STAR", "category": "Misc", "match_type": "contains"},
            {"keyword": "STARBUCKS", "category": "Coffee Shops", "match_type": "contains"},
        ]
        result = match_by_keywords("STARBUCKS", keywords)
        assert result == "Coffee Shops"  # longer keyword wins

    def test_matches_tst_prefix(self):
        """TST* prefix used by Toast POS restaurant transactions should match Restaurants."""
        result = match_by_keywords("TST* PEACE OF MIND CAFE", SAMPLE_KEYWORDS)
        assert result == "Restaurants"

    def test_matches_partial_keyword(self):
        """A keyword that is a substring of a longer word should still match."""
        result = match_by_keywords("NETFLIX.COM", SAMPLE_KEYWORDS)
        assert result == "Subscription"


# --- Tests for match_by_history() ---

class TestMatchByHistory:

    def test_returns_category_with_sufficient_confident_history(
        self, db, sample_account, sample_categories
    ):
        """
        When enough transactions share the same description and category,
        match_by_history() should return that category name.
        """
        category = sample_categories["Coffee Shops"]
        for _ in range(HISTORY_MIN_MATCHES):
            make_transaction(db, sample_account, "LOCAL CAFE", category_id=category.id)

        result = match_by_history("LOCAL CAFE", db)
        assert result == "Coffee Shops"

    def test_returns_none_when_below_min_matches(
        self, db, sample_account, sample_categories
    ):
        """
        When there are fewer than HISTORY_MIN_MATCHES previous transactions,
        match_by_history() should return None even if they all share a category.
        """
        category = sample_categories["Groceries"]
        for _ in range(HISTORY_MIN_MATCHES - 1):
            make_transaction(db, sample_account, "LOCAL MARKET", category_id=category.id)

        result = match_by_history("LOCAL MARKET", db)
        assert result is None

    def test_returns_none_when_history_is_mixed(
        self, db, sample_account, sample_categories
    ):
        """
        When previous transactions for the same description are split across
        multiple categories below the confidence threshold, return None.
        """
        coffee = sample_categories["Coffee Shops"]
        misc = sample_categories["Misc"]

        # 50/50 split — below confidence threshold
        make_transaction(db, sample_account, "CORNER STORE", category_id=coffee.id)
        make_transaction(db, sample_account, "CORNER STORE", category_id=coffee.id)
        make_transaction(db, sample_account, "CORNER STORE", category_id=misc.id)
        make_transaction(db, sample_account, "CORNER STORE", category_id=misc.id)

        result = match_by_history("CORNER STORE", db)
        assert result is None

    def test_returns_none_for_uncategorized_history(
        self, db, sample_account
    ):
        """
        Transactions with no category assigned should not count toward history.
        """
        for _ in range(HISTORY_MIN_MATCHES + 2):
            make_transaction(db, sample_account, "MYSTERY MERCHANT", category_id=None)

        result = match_by_history("MYSTERY MERCHANT", db)
        assert result is None

    def test_returns_none_for_empty_database(self, db):
        """match_by_history() should return None when no transactions exist."""
        result = match_by_history("STARBUCKS", db)
        assert result is None

    def test_returns_dominant_category_above_threshold(
        self, db, sample_account, sample_categories
    ):
        """
        When one category accounts for >= HISTORY_CONFIDENCE_THRESHOLD of matches,
        it should be returned even if other categories are also present.
        """
        gas = sample_categories["Gas"]
        misc = sample_categories["Misc"]

        # 4 gas, 1 misc = 80% confidence — at threshold
        for _ in range(4):
            make_transaction(db, sample_account, "CHEVRON STATION", category_id=gas.id)
        make_transaction(db, sample_account, "CHEVRON STATION", category_id=misc.id)

        result = match_by_history("CHEVRON STATION", db)
        assert result == "Gas"


# --- Tests for get_category_by_name() ---

class TestGetCategoryByName:

    def test_returns_category_for_valid_name(self, db, sample_categories):
        """Should return the Category object when the name exists."""
        result = get_category_by_name("Groceries", db)
        assert result is not None
        assert result.name == "Groceries"

    def test_returns_none_for_unknown_name(self, db):
        """Should return None when the category name does not exist."""
        result = get_category_by_name("Nonexistent Category", db)
        assert result is None

    def test_matching_is_case_sensitive(self, db, sample_categories):
        """Category name lookup should be case sensitive."""
        result = get_category_by_name("groceries", db)
        assert result is None


# --- Tests for categorize_transaction() ---

class TestCategorizeTransaction:

    def test_assigns_category_via_keyword_match(
        self, db, sample_account, sample_categories
    ):
        """
        A transaction whose description matches a keyword should be assigned
        the corresponding category automatically.
        """
        transaction = make_transaction(db, sample_account, "STARBUCKS #4521")
        with patch("categorizer.load_keywords", return_value=SAMPLE_KEYWORDS):
            result = categorize_transaction(transaction, db)
        assert result is True
        assert transaction.category_id == sample_categories["Coffee Shops"].id

    def test_assigns_category_via_history_match(
        self, db, sample_account, sample_categories
    ):
        """
        When no keyword matches but sufficient history exists, the transaction
        should be categorized based on history.
        """
        category = sample_categories["Electric"]
        for _ in range(HISTORY_MIN_MATCHES):
            make_transaction(db, sample_account, "PUGET SOUND ENERGY", category_id=category.id)

        new_transaction = make_transaction(db, sample_account, "PUGET SOUND ENERGY")
        with patch("categorizer.load_keywords", return_value=[]):  # disable keyword matching
            result = categorize_transaction(new_transaction, db)
        assert result is True
        assert new_transaction.category_id == category.id

    def test_returns_false_when_no_match_found(
        self, db, sample_account, sample_categories
    ):
        """
        When neither keyword nor history matching produces a result,
        the transaction should remain uncategorized and return False.
        """
        transaction = make_transaction(db, sample_account, "TOTALLY UNKNOWN VENDOR 9999")
        with patch("categorizer.load_keywords", return_value=[]):
            result = categorize_transaction(transaction, db)
        assert result is False
        assert transaction.category_id is None

    def test_keyword_match_takes_priority_over_history(
        self, db, sample_account, sample_categories
    ):
        """
        Keyword matching should take priority over history matching.
        Even if history suggests a different category, the keyword match wins.
        """
        # Build history pointing to Misc
        misc = sample_categories["Misc"]
        for _ in range(HISTORY_MIN_MATCHES):
            make_transaction(db, sample_account, "STARBUCKS RESERVE", category_id=misc.id)

        # Keyword says Coffee Shops
        new_transaction = make_transaction(db, sample_account, "STARBUCKS RESERVE")
        with patch("categorizer.load_keywords", return_value=SAMPLE_KEYWORDS):
            result = categorize_transaction(new_transaction, db)
        assert result is True
        assert new_transaction.category_id == sample_categories["Coffee Shops"].id


# --- Tests for categorize_all_uncategorized() ---

class TestCategorizeAllUncategorized:

    def test_returns_summary_dict(self, db, sample_account, sample_categories):
        """categorize_all_uncategorized() should return a dict with count keys."""
        with patch("categorizer.load_keywords", return_value=SAMPLE_KEYWORDS):
            result = categorize_all_uncategorized(db)
        assert "auto_assigned" in result
        assert "needs_review" in result
        assert "total_processed" in result

    def test_categorizes_matching_transactions(
        self, db, sample_account, sample_categories
    ):
        """Uncategorized transactions with keyword matches should be assigned."""
        make_transaction(db, sample_account, "NETFLIX MONTHLY")
        make_transaction(db, sample_account, "SHELL GAS STATION")

        with patch("categorizer.load_keywords", return_value=SAMPLE_KEYWORDS):
            result = categorize_all_uncategorized(db)

        assert result["auto_assigned"] == 2
        assert result["needs_review"] == 0
        assert result["total_processed"] == 2

    def test_leaves_unmatched_transactions_uncategorized(
        self, db, sample_account, sample_categories
    ):
        """Transactions with no keyword or history match should remain uncategorized."""
        make_transaction(db, sample_account, "MYSTERY VENDOR ABC")
        make_transaction(db, sample_account, "UNKNOWN CHARGE 999")

        with patch("categorizer.load_keywords", return_value=[]):
            result = categorize_all_uncategorized(db)

        assert result["needs_review"] == 2
        assert result["auto_assigned"] == 0

    def test_skips_already_categorized_transactions(
        self, db, sample_account, sample_categories
    ):
        """
        Transactions that already have a category should not be processed
        or counted in the totals.
        """
        category = sample_categories["Groceries"]
        make_transaction(db, sample_account, "SAFEWAY", category_id=category.id)
        make_transaction(db, sample_account, "NETFLIX MONTHLY")  # uncategorized

        with patch("categorizer.load_keywords", return_value=SAMPLE_KEYWORDS):
            result = categorize_all_uncategorized(db)

        # Only the uncategorized Netflix transaction should be processed
        assert result["total_processed"] == 1
        assert result["auto_assigned"] == 1

    def test_returns_zero_counts_when_nothing_to_process(self, db):
        """When there are no uncategorized transactions, all counts should be zero."""
        with patch("categorizer.load_keywords", return_value=SAMPLE_KEYWORDS):
            result = categorize_all_uncategorized(db)

        assert result["total_processed"] == 0
        assert result["auto_assigned"] == 0
        assert result["needs_review"] == 0


# --- Tests for normalize_description() --- (Phase 1) ---

class TestNormalizeDescription:

    def test_strips_store_number(self):
        """Store numbers like #0731 should be removed."""
        assert "#" not in normalize_description("COSTCO WHSE #0731")

    def test_strips_large_numeric_codes(self):
        """Standalone numeric codes of 4+ digits should be removed."""
        result = normalize_description("TRANSFER REF 16366448395")
        assert "16366448395" not in result

    def test_uppercases_output(self):
        """Output should always be uppercased."""
        assert normalize_description("starbucks") == "STARBUCKS"

    def test_collapses_whitespace(self):
        """Multiple spaces left by stripping should be collapsed to one."""
        result = normalize_description("COSTCO  WHSE   #0731")
        assert "  " not in result

    def test_preserves_merchant_name(self):
        """The core merchant name should survive normalization."""
        assert "COSTCO" in normalize_description("COSTCO WHSE #0731 SEATTLE WA")

    def test_wholefds_normalized(self):
        """WHOLEFDS with store number should still contain WHOLEFDS after normalization."""
        assert "WHOLEFDS" in normalize_description("WHOLEFDS #0421 SEATTLE WA")


# --- Tests for Phase 1 specificity ordering --- (Phase 1) ---

class TestSpecificityOrdering:

    def test_costco_gas_beats_costco(self):
        """
        'COSTCO GAS' (length 10) should be matched before 'COSTCO' (length 6)
        regardless of their order in the keyword list.
        """
        result = match_by_keywords("COSTCO GAS #0731", PHASE1_KEYWORDS)
        assert result == "Gas", f"Expected Gas, got {result}"

    def test_costco_without_gas_is_groceries(self):
        """A plain COSTCO transaction without gas markers should be Groceries."""
        result = match_by_keywords("COSTCO WHSE #0731", PHASE1_KEYWORDS)
        assert result == "Groceries", f"Expected Groceries, got {result}"

    def test_amazon_prime_beats_amazon(self):
        """
        'AMAZON PRIME' should be matched before 'AMAZON' due to greater length
        and explicit priority=10.
        """
        result = match_by_keywords("AMAZON PRIME", PHASE1_KEYWORDS)
        assert result == "Subscription", f"Expected Subscription, got {result}"

    def test_amazon_without_prime_is_home_supplies(self):
        """A plain AMAZON transaction should fall through to Home Supplies."""
        result = match_by_keywords("AMAZON.COM PURCHASE", PHASE1_KEYWORDS)
        assert result == "Home Supplies", f"Expected Home Supplies, got {result}"

    def test_fred_meyer_gas_beats_fred_meyer(self):
        """'FRED MEYER GAS' should be matched before 'FRED MEYER'."""
        result = match_by_keywords("FRED MEYER GAS #1234", PHASE1_KEYWORDS)
        assert result == "Gas", f"Expected Gas, got {result}"

    def test_fred_meyer_without_gas_is_groceries(self):
        """A plain FRED MEYER transaction should be Groceries."""
        result = match_by_keywords("FRED MEYER #1234", PHASE1_KEYWORDS)
        assert result == "Groceries", f"Expected Groceries, got {result}"

    def test_store_number_does_not_affect_match(self):
        """
        Normalization should strip store numbers so 'COSTCO WHSE #0731' and
        'COSTCO WHSE #0042' match identically.
        """
        kws = PHASE1_KEYWORDS
        r1 = match_by_keywords("COSTCO WHSE #0731", kws)
        r2 = match_by_keywords("COSTCO WHSE #0042", kws)
        assert r1 == r2 == "Groceries"


# --- Tests for Phase 1 negative keywords --- (Phase 1) ---

class TestNegativeKeywords:

    def test_costco_tire_not_groceries(self):
        """
        COSTCO TIRE CENTER should not match the COSTCO → Groceries rule
        because 'TIRE' is in exclude_if_contains.
        """
        result = match_by_keywords("COSTCO TIRE CENTER", PHASE1_KEYWORDS)
        assert result != "Groceries", "COSTCO TIRE should not be Groceries"

    def test_costco_optical_not_groceries(self):
        """COSTCO OPTICAL should not match COSTCO → Groceries."""
        result = match_by_keywords("COSTCO OPTICAL", PHASE1_KEYWORDS)
        assert result != "Groceries"

    def test_costco_pharmacy_not_groceries(self):
        """COSTCO PHARMACY should not match COSTCO → Groceries."""
        result = match_by_keywords("COSTCO PHARMACY", PHASE1_KEYWORDS)
        assert result != "Groceries"

    def test_amazon_prime_not_home_supplies(self):
        """
        AMAZON PRIME should not match AMAZON → Home Supplies because 'PRIME'
        is in exclude_if_contains for that rule. It should match the
        AMAZON PRIME → Subscription rule instead.
        """
        result = match_by_keywords("AMAZON PRIME", PHASE1_KEYWORDS)
        assert result == "Subscription"
        assert result != "Home Supplies"

    def test_fred_meyer_fuel_not_groceries(self):
        """FRED MEYER with FUEL in description should not be Groceries."""
        result = match_by_keywords("FRED MEYER FUEL CENTER", PHASE1_KEYWORDS)
        assert result != "Groceries"


# --- Tests for Phase 1 short keyword whole-word matching --- (Phase 1) ---

class TestShortKeywordMatching:

    def test_pse_does_not_match_inside_word(self):
        """
        'PSE' is below the short keyword threshold and should only match
        as a whole word. It should not match 'EXPENSE' or similar.
        """
        result = match_by_keywords("EXPENSE REIMBURSEMENT", PHASE1_KEYWORDS)
        assert result != "Electric", "PSE should not match inside EXPENSE"

    def test_pse_matches_as_standalone_token(self):
        """PSE appearing as a standalone token should match Electric."""
        result = match_by_keywords("PSE PUGET SOUND", PHASE1_KEYWORDS)
        assert result == "Electric", f"Expected Electric, got {result}"

    def test_pse_matches_at_start_of_description(self):
        """PSE at the start of a description should match as a whole word."""
        result = match_by_keywords("PSE MONTHLY BILL", PHASE1_KEYWORDS)
        assert result == "Electric", f"Expected Electric, got {result}"
