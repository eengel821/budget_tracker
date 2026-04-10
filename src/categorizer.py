"""
categorizer.py - Automatic transaction categorization engine.

Provides two public interfaces:

  suggest_category(transaction, db)
      Returns a (category_id, confidence, source) tuple representing the
      engine's best prediction. Does NOT write to the transaction — the
      caller stores the suggestion. Used at import time to pre-fill the
      review queue.

  confirm_category(transaction, category_id, db)
      Called when the user confirms or corrects a suggestion in the review
      queue. Assigns category_id, clears suggestion columns, and triggers
      an ML model retrain so the correction is learned immediately.

Three strategies are tried in order:

  1. Keyword matching — checks the normalized description against keywords.json.
     Rules are sorted by specificity (longest first) so "COSTCO GAS" always
     beats "COSTCO". Supports negative keywords via exclude_if_contains.
     Source: "keyword", confidence: None (deterministic).

  2. History matching — looks at previously confirmed transactions with the
     same description. If one category dominates above the confidence threshold
     with enough samples, it wins.
     Source: "history", confidence: None (deterministic).

  3. ML model — TF-IDF + Logistic Regression trained on all confirmed
     transactions. Returns a softmax probability as the confidence score.
     Source: "ml", confidence: float 0.0-1.0.

Phase 1 keyword improvements:
  - Keywords sorted by specificity (longest first within same priority level)
  - Merchant normalization strips store numbers and noise before matching
  - Negative keywords via exclude_if_contains field
  - Short keywords (<4 chars) matched as whole words only
"""

import json
import re
import logging
from pathlib import Path
from collections import Counter
from typing import Optional

from sqlalchemy.orm import Session

from models import Transaction, Category

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent

KEYWORDS_FILE = (
    _ROOT / "keywords.json"
    if (_ROOT / "keywords.json").exists()
    else _ROOT / "keywords.example.json"
)

MODEL_PATH = _ROOT / "data" / "categorizer_model.pkl"

# History matching thresholds
HISTORY_CONFIDENCE_THRESHOLD = 0.8
HISTORY_MIN_MATCHES = 3

# ML confidence threshold — predictions below this are shown in the review
# queue but not pre-ticked for confirmation.
ML_CONFIDENCE_THRESHOLD = 0.75

# Minimum labeled examples per category before ML training is attempted.
ML_MIN_EXAMPLES_PER_CATEGORY = 3

# Short keywords below this length are matched as whole words only.
SHORT_KEYWORD_THRESHOLD = 4

# Noise patterns stripped from descriptions before keyword matching.
_NOISE_PATTERNS = [
    r"#\d+",             # store/branch numbers: #0731
    r"\b\d{4,}\b",       # standalone numeric codes 4+ digits
    r"\*+\d+",           # starred codes: *1234
    r"\bREF\s*\d+\b",    # reference numbers
    r"\b[A-Z]{2}\b$",    # trailing 2-letter state codes
]
_NOISE_RE = re.compile("|".join(_NOISE_PATTERNS))


# ── Description normalization ─────────────────────────────────────────────────

def normalize_description(description: str) -> str:
    """
    Strip store numbers, branch codes, and other noise from a transaction
    description before keyword matching.

    Normalization makes matching robust to bank formatting variations.
    The original description is never modified — normalization is applied
    only during matching and not persisted to the database.

    Args:
        description: Raw transaction description string.

    Returns:
        Normalized description with noise stripped and whitespace collapsed.
    """
    normalized = _NOISE_RE.sub(" ", description.upper())
    normalized = re.sub(r"\s{2,}", " ", normalized).strip()
    return normalized


# ── Keyword engine ────────────────────────────────────────────────────────────

def load_keywords() -> list[dict]:
    """
    Load keyword-to-category mappings from keywords.json, pre-sorted by
    priority and specificity.

    Pre-sorts for efficiency, though match_by_keywords() also sorts
    defensively in case keywords are passed directly (e.g. in tests).
    Sort key:
        1. Explicit priority field ascending (lower = checked first), default 50
        2. Keyword length descending (longer = more specific = checked first)

    Returns:
        Sorted list of keyword rule dicts, or empty list if file not found.
    """
    if not KEYWORDS_FILE.exists():
        logger.warning("keywords.json not found at %s. Skipping keyword matching.", KEYWORDS_FILE)
        return []
    with open(KEYWORDS_FILE, "r") as f:
        data = json.load(f)
    keywords = data["keywords"]
    keywords.sort(key=lambda e: (e.get("priority", 50), -len(e["keyword"])))
    return keywords


def match_by_keywords(description: str, keywords: list[dict]) -> str | None:
    """
    Attempt to match a transaction description against the keyword list.

    Sorts keywords defensively before matching so results are correct
    regardless of whether the caller pre-sorted (load_keywords) or
    passed a raw list (tests).

    Matching rules:
    - Keywords sorted by priority/specificity before matching.
    - Description normalized before matching (store numbers stripped).
    - Short keywords matched as whole words only to avoid false positives.
    - Rules with exclude_if_contains are skipped if any exclusion term
      appears in the normalized description (negative keywords).

    Args:
        description: Raw transaction description string.
        keywords: List of keyword rule dicts.

    Returns:
        Matched category name, or None if no rule matched.
    """
    keywords = sorted(keywords, key=lambda e: (e.get("priority", 50), -len(e["keyword"])))
    normalized = normalize_description(description)

    for entry in keywords:
        keyword = entry["keyword"].upper()
        match_type = entry.get("match_type", "contains")

        if match_type != "contains":
            continue

        exclusions = entry.get("exclude_if_contains", [])
        if any(excl.upper() in normalized for excl in exclusions):
            continue

        if len(keyword) < SHORT_KEYWORD_THRESHOLD:
            if re.search(r"\b" + re.escape(keyword) + r"\b", normalized):
                return entry["category"]
        else:
            if keyword in normalized:
                return entry["category"]

    return None


# ── History matching ──────────────────────────────────────────────────────────

def match_by_history(description: str, db: Session) -> str | None:
    """
    Attempt to assign a category based on previously confirmed transactions
    with the same description.

    Only transactions with category_id set (user-confirmed) are counted.
    Returns the dominant category if it meets the confidence threshold and
    minimum match count.

    Args:
        description: Raw transaction description.
        db: Active SQLAlchemy session.

    Returns:
        Most common category name if thresholds are met, else None.
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


# ── ML model ──────────────────────────────────────────────────────────────────

class CategorizationModel:
    """
    TF-IDF + Logistic Regression classifier for transaction categorization.

    Converts transaction descriptions to TF-IDF feature vectors, optionally
    augmented with log-transformed amount and month, then fits a multinomial
    logistic regression model. The softmax output provides a calibrated
    confidence score for each prediction.

    The model is serialized to disk at MODEL_PATH after each training run
    and loaded on first use. If no saved model exists or insufficient labeled
    data is available, predict() returns (None, 0.0).

    Retraining from scratch on every correction is intentional — at the
    current data scale (<1000 transactions) it takes milliseconds and always
    produces globally optimal weights given all available labels.
    """

    def __init__(self):
        self._pipeline = None
        self._label_encoder = None
        self._trained = False

    def _load(self) -> bool:
        """
        Load a previously saved model from disk.

        Returns:
            True if a model was loaded successfully, False otherwise.
        """
        try:
            import joblib
            if MODEL_PATH.exists():
                saved = joblib.load(MODEL_PATH)
                self._pipeline = saved["pipeline"]
                self._label_encoder = saved["label_encoder"]
                self._trained = True
                return True
        except Exception as e:
            logger.warning("Failed to load saved model: %s", e)
        return False

    def train(self, db: Session) -> bool:
        """
        Train the model on all confirmed (user-assigned) transactions in the
        database. Retrains from scratch on each call.

        Feature construction:
          - TF-IDF on normalized description text (char 2-4 grams, max 5000 features).
            Character n-grams outperform word n-grams on bank descriptions, which
            are heavily abbreviated (WHOLEFDS, TST*, ARCO) and lack word boundaries.
          - Log-transformed absolute amount appended as a numeric feature.
            log1p(|amount|) compresses the range so a $3000 charge does not
            dominate $30 charges by a factor of 100.
          - Month of year (1-12) appended to capture seasonal patterns.

        Only categories with at least ML_MIN_EXAMPLES_PER_CATEGORY confirmed
        transactions are included. Categories with too few examples would
        produce unreliable predictions and inflate false positive rates.

        Args:
            db: Active SQLAlchemy session.

        Returns:
            True if training succeeded, False if insufficient data.
        """
        try:
            import numpy as np
            import joblib
            from sklearn.linear_model import LogisticRegression
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.preprocessing import LabelEncoder
            from scipy.sparse import hstack, csr_matrix
        except ImportError:
            logger.warning("scikit-learn not installed. ML categorization unavailable.")
            return False

        # Fetch all confirmed transactions (category_id set, not excluded, not split children)
        labeled = db.query(Transaction).filter(
            Transaction.category_id.isnot(None),
            Transaction.excluded == False,       # noqa: E712
            Transaction.parent_id.is_(None),
        ).all()

        if not labeled:
            logger.info("No labeled transactions available for ML training.")
            return False

        # Drop categories below the minimum example threshold
        cat_counts = Counter(t.category_id for t in labeled)
        valid_cat_ids = {
            cat_id for cat_id, count in cat_counts.items()
            if count >= ML_MIN_EXAMPLES_PER_CATEGORY
        }
        labeled = [t for t in labeled if t.category_id in valid_cat_ids]

        if len(valid_cat_ids) < 2:
            logger.info(
                "Fewer than 2 categories meet the minimum example threshold "
                "(%d per category). Skipping ML training.", ML_MIN_EXAMPLES_PER_CATEGORY
            )
            return False

        # Resolve category names (more robust than IDs across DB rebuilds)
        cat_id_to_name = {}
        for t in labeled:
            if t.category_id not in cat_id_to_name:
                cat = db.query(Category).filter(Category.id == t.category_id).first()
                if cat:
                    cat_id_to_name[t.category_id] = cat.name

        descriptions = [normalize_description(t.description) for t in labeled]
        amounts      = np.array([np.log1p(abs(t.amount)) for t in labeled]).reshape(-1, 1)
        months       = np.array([t.date.month for t in labeled]).reshape(-1, 1)

        le     = LabelEncoder()
        labels = le.fit_transform([cat_id_to_name.get(t.category_id, "") for t in labeled])

        tfidf = TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(2, 4),
            max_features=5000,
            sublinear_tf=True,
        )
        X_text    = tfidf.fit_transform(descriptions)
        X_numeric = csr_matrix(np.hstack([amounts, months]))
        X         = hstack([X_text, X_numeric])

        # L2 regularization (C=1.0). Lower C = stronger regularization = less
        # overfitting, which matters more as dataset size grows.
        clf = LogisticRegression(
            C=1.0,
            max_iter=1000,
            multi_class="multinomial",
            solver="lbfgs",
        )
        clf.fit(X, labels)

        self._pipeline      = {"tfidf": tfidf, "clf": clf}
        self._label_encoder = le
        self._trained       = True

        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"pipeline": self._pipeline, "label_encoder": le}, MODEL_PATH)

        logger.info(
            "ML model trained on %d transactions across %d categories.",
            len(labeled), len(valid_cat_ids)
        )
        return True

    def predict(self, description: str, amount: float, month: int) -> tuple[str | None, float]:
        """
        Predict the category for a transaction and return a confidence score.

        If the model is not trained or fails to load, returns (None, 0.0).

        Args:
            description: Raw transaction description.
            amount: Transaction amount (signed float).
            month: Month of transaction (1-12).

        Returns:
            Tuple of (predicted_category_name, confidence) where confidence
            is the softmax probability of the top prediction (0.0-1.0).
        """
        if not self._trained:
            if not self._load():
                return None, 0.0

        try:
            import numpy as np
            from scipy.sparse import hstack, csr_matrix

            tfidf = self._pipeline["tfidf"]
            clf   = self._pipeline["clf"]
            le    = self._label_encoder

            normalized = normalize_description(description)
            X_text     = tfidf.transform([normalized])
            X_numeric  = csr_matrix(np.array([[np.log1p(abs(amount)), month]]))
            X          = hstack([X_text, X_numeric])

            proba         = clf.predict_proba(X)[0]
            top_idx       = int(proba.argmax())
            confidence    = float(proba[top_idx])
            category_name = le.inverse_transform([top_idx])[0]

            return category_name, confidence

        except Exception as e:
            logger.warning("ML prediction failed: %s", e)
            return None, 0.0


# Module-level model instance — loaded/trained once per process lifetime.
_model = CategorizationModel()


def retrain_model(db: Session) -> None:
    """
    Retrain the ML model from scratch on all confirmed transactions.

    Called automatically after each user confirmation in the review queue
    so corrections are learned immediately. At the current data scale this
    takes milliseconds.

    Args:
        db: Active SQLAlchemy session.
    """
    global _model
    _model = CategorizationModel()
    success = _model.train(db)
    if not success:
        logger.info("Model retrain skipped — insufficient labeled data.")


# ── Core public interface ─────────────────────────────────────────────────────

def get_category_by_name(name: str, db: Session) -> Category | None:
    """
    Look up a Category record by name.

    Args:
        name: Category name string.
        db: Active SQLAlchemy session.

    Returns:
        Matching Category object, or None if not found.
    """
    return db.query(Category).filter(Category.name == name).first()


def suggest_category(
    transaction: Transaction,
    db: Session,
) -> tuple[Optional[int], Optional[float], Optional[str]]:
    """
    Predict the best category for a transaction without assigning it.

    Tries three strategies in order and returns on the first successful result:
      1. Keyword matching  (source="keyword",  confidence=None)
      2. History matching  (source="history",  confidence=None)
      3. ML model          (source="ml",       confidence=float)

    Nothing is written to the database by this function.

    Args:
        transaction: The Transaction to categorize (not yet modified).
        db: Active SQLAlchemy session.

    Returns:
        Tuple of (category_id, confidence, source) where:
          - category_id is the int FK, or None if no suggestion
          - confidence is a float 0.0-1.0 for ML predictions, None otherwise
          - source is "keyword", "history", "ml", or None
    """
    keywords = load_keywords()

    # Strategy 1: keyword matching
    category_name = match_by_keywords(transaction.description, keywords)
    if category_name:
        category = get_category_by_name(category_name, db)
        if category:
            return category.id, None, "keyword"

    # Strategy 2: history matching
    category_name = match_by_history(transaction.description, db)
    if category_name:
        category = get_category_by_name(category_name, db)
        if category:
            return category.id, None, "history"

    # Strategy 3: ML model
    if not _model._trained:
        _model._load()

    category_name, confidence = _model.predict(
        transaction.description,
        transaction.amount,
        transaction.date.month,
    )
    if category_name and confidence > 0:
        category = get_category_by_name(category_name, db)
        if category:
            return category.id, round(confidence, 4), "ml"

    return None, None, None


def apply_suggestion(transaction: Transaction, db: Session) -> bool:
    """
    Run suggest_category() and store the result on the transaction.

    Writes suggested_category_id, suggestion_confidence, and suggestion_source
    to the transaction and flushes to the session. Does NOT commit — the caller
    is responsible for committing.

    Args:
        transaction: The Transaction to annotate with a suggestion.
        db: Active SQLAlchemy session.

    Returns:
        True if a suggestion was stored, False if no prediction was made.
    """
    cat_id, confidence, source = suggest_category(transaction, db)

    if cat_id is not None:
        transaction.suggested_category_id = cat_id
        transaction.suggestion_confidence  = confidence
        transaction.suggestion_source      = source
        db.flush()
        return True

    return False


def confirm_category(
    transaction: Transaction,
    category_id: int,
    db: Session,
) -> None:
    """
    Confirm or correct a category suggestion in the review queue.

    Assigns the confirmed category_id, clears all suggestion columns, and
    triggers an ML model retrain so the correction is learned immediately.

    Args:
        transaction: The Transaction being confirmed.
        category_id: The confirmed category ID (may differ from suggestion).
        db: Active SQLAlchemy session.
    """
    transaction.category_id           = category_id
    transaction.suggested_category_id = None
    transaction.suggestion_confidence = None
    transaction.suggestion_source     = None
    db.commit()
    retrain_model(db)


# ── Bulk operations ───────────────────────────────────────────────────────────

def suggest_all_unprocessed(db: Session) -> dict:
    """
    Run apply_suggestion() on all transactions that have no category and no
    existing suggestion.

    Used at import time after committing new transactions, and as the backend
    for the "Auto-categorize All" button in the review queue.

    Args:
        db: Active SQLAlchemy session.

    Returns:
        Dict with keys: suggested, no_suggestion, total_processed.
    """
    unprocessed = db.query(Transaction).filter(
        Transaction.category_id.is_(None),
        Transaction.suggested_category_id.is_(None),
        Transaction.excluded == False,       # noqa: E712
        Transaction.parent_id.is_(None),
    ).all()

    suggested     = 0
    no_suggestion = 0

    for transaction in unprocessed:
        result = apply_suggestion(transaction, db)
        if result:
            suggested += 1
        else:
            no_suggestion += 1

    db.commit()

    return {
        "suggested":       suggested,
        "no_suggestion":   no_suggestion,
        "total_processed": len(unprocessed),
    }


def categorize_all_uncategorized(db: Session) -> dict:
    """
    Legacy entry point for the "Auto-categorize All" button.

    Delegates to suggest_all_unprocessed() and returns a compatible
    response shape so existing callers in imports.py do not break.

    Args:
        db: Active SQLAlchemy session.

    Returns:
        Dict with auto_assigned, needs_review, total_processed keys.
    """
    result = suggest_all_unprocessed(db)
    return {
        "auto_assigned":   result["suggested"],
        "needs_review":    result["no_suggestion"],
        "total_processed": result["total_processed"],
    }
