"""
categorizer.py - Automatic transaction categorization engine.

Attempts to assign a category to a transaction using two strategies in order:

1. Keyword matching — checks the normalized transaction description against
   keywords.json. Rules are sorted by specificity (longest keyword first) so
   more specific rules always win over general ones. Supports negative keywords
   to express exceptions (e.g. COSTCO → Groceries unless description contains GAS).

2. History matching — if no keyword match is found, looks at previously
   categorized transactions with the same description. If a single category
   accounts for the majority of those matches, it is assigned automatically.

If neither strategy produces a confident match, the transaction is left
uncategorized for manual review via the FastAPI browser interface.

Phase 1 improvements over the original implementation:
  - Keywords are sorted by length descending before matching, so "COSTCO GAS"
    always beats "COSTCO" regardless of order in keywords.json.
  - Optional `priority` field in keyword rules allows manual override of ordering
    for edge cases where length alone is insufficient.
  - Optional `exclude_if_contains` field supports negative keywords — a rule is
    skipped if any of those strings appear in the description.
  - Description normalization strips store numbers, branch codes, and trailing
    noise before matching, so "COSTCO WHSE #0731" and "COSTCO WHSE #0042"
    both match the same rules.
  - Keywords below a configurable minimum length are matched as whole words only
    (not substring) to reduce false positives from short tokens like "PSE".
"""

import json
import re
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

# Keywords shorter than this length are matched as whole words only,
# not as substrings. Prevents short tokens like "PSE" matching "EXPENSE".
SHORT_KEYWORD_THRESHOLD = 4

# Regex patterns for normalization — stripped from descriptions before matching.
# Order matters: more specific patterns should come first.
_NOISE_PATTERNS = [
    r"#\d+",             # store/branch numbers: #0731, #042
    r"\b\d{4,}\b",       # standalone numeric codes of 4+ digits
    r"\*+\d+",           # starred codes: *1234
    r"\bREF\s*\d+\b",    # reference numbers: REF 16366448395
    r"\b[A-Z]{2}\b$",    # trailing 2-letter state codes at end of string
]
_NOISE_RE = re.compile("|".join(_NOISE_PATTERNS))


def normalize_description(description: str) -> str:
    """
    Strip store numbers, branch codes, and other noise from a transaction
    description before keyword matching.

    Normalization makes matching more robust to formatting variations across
    banks and merchants. For example:
        "COSTCO WHSE #0731 SEATTLE WA" → "COSTCO WHSE SEATTLE"
        "WHOLEFDS #0421 SEATTLE WA"    → "WHOLEFDS SEATTLE"
        "STARBUCKS #12345"             → "STARBUCKS"

    The original description is never modified — normalization is applied only
    during matching and not persisted to the database.

    Args:
        description: Raw transaction description string.

    Returns:
        Normalized description with noise stripped and excess whitespace collapsed.
    """
    normalized = _NOISE_RE.sub(" ", description.upper())
    # Collapse multiple spaces left by substitution
    normalized = re.sub(r"\s{2,}", " ", normalized).strip()
    return normalized


def load_keywords() -> list[dict]:
    """
    Load keyword-to-category mappings from keywords.json and sort them by
    effective matching priority.

    Pre-sorts the list for efficiency, though match_by_keywords() also sorts
    defensively in case keywords are passed directly (e.g. in tests). Sort key is:

        1. Explicit `priority` field (lower number = checked first), default 50
        2. Keyword length descending (longer = more specific = checked first)

    This means "COSTCO GAS" (length 10) is always checked before "COSTCO"
    (length 6), and "AMAZON PRIME" (length 12) is always checked before
    "AMAZON" (length 6).

    Returns:
        Sorted list of keyword rule dicts. Returns an empty list if the file
        cannot be found, allowing the categorizer to fall back to history matching.
    """
    if not KEYWORDS_FILE.exists():
        print(f"Warning: keywords.json not found at {KEYWORDS_FILE}. Skipping keyword matching.")
        return []
    with open(KEYWORDS_FILE, "r") as f:
        data = json.load(f)

    keywords = data["keywords"]

    # Sort by priority ascending, then keyword length descending.
    # This ensures explicit priority overrides take precedence, and within
    # the same priority level, longer (more specific) keywords win.
    keywords.sort(key=lambda e: (e.get("priority", 50), -len(e["keyword"])))
    return keywords


def match_by_keywords(description: str, keywords: list[dict]) -> str | None:
    """
    Attempt to match a normalized transaction description against the keyword list.

    Matching rules:
    - Keywords are sorted by priority/specificity before matching so the best
      match always wins, regardless of the order they were passed in.
    - The description is normalized before matching (store numbers etc. stripped).
    - Short keywords (below SHORT_KEYWORD_THRESHOLD characters) are matched as
      whole words only, not as substrings, to avoid false positives.
    - If a rule has an `exclude_if_contains` list, the match is skipped if any
      of those strings appear in the description — this implements negative keywords.

    Args:
        description: The raw transaction description string.
        keywords: Sorted list of keyword rule dicts from load_keywords().

    Returns:
        The matched category name, or None if no rule matched.
    """
    # Sort here so ordering is correct regardless of whether the caller
    # pre-sorted (e.g. load_keywords) or passed a raw list (e.g. tests).
    keywords = sorted(keywords, key=lambda e: (e.get("priority", 50), -len(e["keyword"])))

    normalized = normalize_description(description)

    for entry in keywords:
        keyword = entry["keyword"].upper()
        match_type = entry.get("match_type", "contains")

        if match_type != "contains":
            continue

        # Check negative keywords first — skip this rule if any exclusion term matches.
        exclusions = entry.get("exclude_if_contains", [])
        if any(excl.upper() in normalized for excl in exclusions):
            continue

        # Short keywords use whole-word matching to avoid false positives.
        # e.g. "PSE" should not match "EXPENSE" or "IPSE".
        if len(keyword) < SHORT_KEYWORD_THRESHOLD:
            pattern = r"\b" + re.escape(keyword) + r"\b"
            if re.search(pattern, normalized):
                return entry["category"]
        else:
            if keyword in normalized:
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
        description: The raw transaction description to look up in history.
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

    Runs keyword matching first (with normalization and specificity ordering),
    then falls back to history matching if no keyword match is found. If a
    category is successfully identified, it is assigned to the transaction and
    the change is flushed to the session (but not committed — the caller is
    responsible for committing).

    Args:
        transaction: The Transaction object to categorize.
        db: An active SQLAlchemy database session.

    Returns:
        True if a category was assigned, False if the transaction was left
        uncategorized for manual review.
    """
    keywords = load_keywords()

    # Strategy 1: keyword matching (with normalization + specificity ordering)
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
