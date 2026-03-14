"""
categorizer.py - Automatic transaction categorization engine.

Attempts to assign a category to a transaction using two strategies in order:

1. Keyword matching — checks the transaction description against keywords.json.
   If a match is found, the category is assigned immediately.

2. History matching — if no keyword match is found, looks at previously
   categorized transactions with similar descriptions. If a single category
   accounts for the majority of those matches, it is assigned automatically.

If neither strategy produces a confident match, the transaction is left
uncategorized for manual review via the FastAPI browser interface.
"""

import json
from pathlib import Path
from sqlalchemy.orm import Session
from models import Transaction, Category
from collections import Counter

_ROOT = Path(__file__).resolve().parent.parent
KEYWORDS_FILE = (
    _ROOT / "keywords.json"
    if (_ROOT / "keywords.json").exists()
    else _ROOT / "keywords.example.json"
)

# Minimum ratio of history matches required to auto-assign a category.
# e.g. 0.8 means 80% of previous transactions with this description
# must share the same category before it is auto-assigned.
HISTORY_CONFIDENCE_THRESHOLD = 0.8

# Minimum number of historical matches required before auto-assigning.
# Prevents auto-assignment based on just one or two previous transactions.
HISTORY_MIN_MATCHES = 3


def load_keywords() -> list[dict]:
    """
    Load keyword-to-category mappings from keywords.json.

    Returns a list of keyword mapping dicts, each containing a keyword,
    category name, and match_type. Returns an empty list if the file
    cannot be found, allowing the categorizer to fall back to history matching.
    """
    if not KEYWORDS_FILE.exists():
        print(f"Warning: keywords.json not found at {KEYWORDS_FILE}. Skipping keyword matching.")
        return []
    with open(KEYWORDS_FILE, "r") as f:
        data = json.load(f)
    return data["keywords"]


def match_by_keywords(description: str, keywords: list[dict]) -> str | None:
    """
    Attempt to match a transaction description against the keyword list.

    Checks the description (case-insensitively) against each keyword entry.
    Currently supports 'contains' match type, which returns a match if the
    keyword appears anywhere within the description.

    Args:
        description: The transaction description string to match against.
        keywords: The list of keyword mapping dicts loaded from keywords.json.

    Returns:
        The matched category name as a string, or None if no match was found.
    """
    description_upper = description.upper()
    for entry in keywords:
        keyword = entry["keyword"].upper()
        match_type = entry.get("match_type", "contains")
        if match_type == "contains" and keyword in description_upper:
            return entry["category"]
    return None


def match_by_history(description: str, db: Session) -> str | None:
    """
    Attempt to assign a category based on previously categorized transactions
    with the same description.

    Looks up all previously categorized transactions sharing the same description,
    counts how many times each category appears, and returns the most common
    category if it meets the confidence threshold and minimum match count.

    Args:
        description: The transaction description to look up in history.
        db: An active SQLAlchemy database session.

    Returns:
        The most common category name if confidence thresholds are met,
        or None if there is insufficient history to make a confident assignment.
    """
    previous = db.query(Transaction).filter(
        Transaction.description == description,
        Transaction.category_id.isnot(None),
    ).all()

    if len(previous) < HISTORY_MIN_MATCHES:
        return None

    category_counts = Counter(t.category_id for t in previous)
    most_common_id, most_common_count = category_counts.most_common(1)[0]
    confidence = most_common_count / len(previous)

    if confidence >= HISTORY_CONFIDENCE_THRESHOLD:
        category = db.query(Category).filter(Category.id == most_common_id).first()
        return category.name if category else None

    return None


def get_category_by_name(name: str, db: Session) -> Category | None:
    """
    Look up a Category record by name.

    Args:
        name: The category name string to look up.
        db: An active SQLAlchemy database session.

    Returns:
        The matching Category object, or None if not found.
    """
    return db.query(Category).filter(Category.name == name).first()


def categorize_transaction(transaction: Transaction, db: Session) -> bool:
    """
    Attempt to auto-assign a category to a single transaction.

    Runs keyword matching first, then falls back to history matching if no
    keyword match is found. If a category is successfully identified, it is
    assigned to the transaction and the change is flushed to the session
    (but not committed — the caller is responsible for committing).

    Args:
        transaction: The Transaction object to categorize.
        db: An active SQLAlchemy database session.

    Returns:
        True if a category was assigned, False if the transaction was left
        uncategorized for manual review.
    """
    keywords = load_keywords()

    # Strategy 1: keyword matching
    category_name = match_by_keywords(transaction.description, keywords)

    # Strategy 2: history matching
    if not category_name:
        category_name = match_by_history(transaction.description, db)

    if category_name:
        category = get_category_by_name(category_name, db)
        if category:
            transaction.category_id = category.id
            db.flush()
            return True

    return False


def categorize_all_uncategorized(db: Session) -> dict:
    """
    Run the categorization engine across all uncategorized transactions.

    Useful for bulk categorization after initial import or after adding new
    keywords to keywords.json. Processes every transaction that currently
    has no category assigned and attempts to auto-assign one.

    Args:
        db: An active SQLAlchemy database session.

    Returns:
        A dict with counts of how many transactions were auto-assigned
        vs left uncategorized.
    """
    uncategorized = db.query(Transaction).filter(
        Transaction.category_id.is_(None)
    ).all()

    assigned = 0
    unresolved = 0

    for transaction in uncategorized:
        result = categorize_transaction(transaction, db)
        if result:
            assigned += 1
        else:
            unresolved += 1

    db.commit()

    return {
        "auto_assigned": assigned,
        "needs_review": unresolved,
        "total_processed": len(uncategorized),
    }