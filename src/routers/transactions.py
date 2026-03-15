"""
routers/transactions.py — Transaction API routes for Budget Tracker.

Handles CRUD operations on transactions including category assignment,
description/notes editing, deletion, exclusion toggling, and splitting.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Category, Transaction
from schemas import CategoryAssignment, SplitRequest, TransactionPatch

router = APIRouter()


# ── Shared helper ─────────────────────────────────────────────────────────────

def get_transaction_or_404(db: Session, transaction_id: int) -> Transaction:
    """
    Fetch a Transaction by ID or raise HTTP 404.

    Args:
        db: An active SQLAlchemy database session.
        transaction_id: The primary key of the transaction to fetch.

    Returns:
        The Transaction object if found.

    Raises:
        HTTPException: 404 if the transaction does not exist.
    """
    txn = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return txn


# ── Read routes ───────────────────────────────────────────────────────────────

@router.get("/api/transactions")
def get_transactions(db: Session = Depends(get_db)):
    """Return all transactions ordered by date descending as JSON."""
    return db.query(Transaction).order_by(Transaction.date.desc()).all()


@router.get("/api/transactions/uncategorized")
def get_uncategorized(db: Session = Depends(get_db)):
    """Return all uncategorized transactions as JSON."""
    return db.query(Transaction).filter(
        Transaction.category_id.is_(None)
    ).order_by(Transaction.date.desc()).all()


# ── Update routes ─────────────────────────────────────────────────────────────

@router.put("/transactions/{transaction_id}/category")
def assign_category(
    transaction_id: int,
    body: CategoryAssignment,
    db: Session = Depends(get_db),
):
    """
    Assign or override the category on a transaction.

    Returns 404 if the transaction or category does not exist.
    """
    transaction = get_transaction_or_404(db, transaction_id)

    category = db.query(Category).filter(Category.id == body.category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    transaction.category_id = body.category_id
    db.commit()

    return {
        "message":       f"Category '{category.name}' assigned",
        "transaction_id": transaction_id,
        "category_id":    category.id,
        "category_name":  category.name,
    }


@router.patch("/api/transactions/{transaction_id}")
def patch_transaction(
    transaction_id: int,
    body: TransactionPatch,
    db: Session = Depends(get_db),
):
    """
    Partially update a transaction's description or notes.

    Only fields included in the request body are updated.
    Returns 404 if the transaction does not exist.
    """
    transaction = get_transaction_or_404(db, transaction_id)

    if body.description is not None:
        transaction.description = body.description
    if body.notes is not None:
        transaction.notes = body.notes

    db.commit()
    db.refresh(transaction)

    return {
        "message":        "Transaction updated",
        "transaction_id": transaction_id,
        "description":    transaction.description,
        "notes":          transaction.notes,
    }


@router.put("/api/transactions/{transaction_id}/exclude")
def set_transaction_excluded(
    transaction_id: int,
    db: Session = Depends(get_db),
):
    """
    Mark a transaction as excluded from reports and budget calculations.

    Excluded transactions are hidden on the transactions page by default
    but can still be viewed using the 'show excluded' toggle.
    Returns 404 if the transaction does not exist.
    """
    transaction = get_transaction_or_404(db, transaction_id)
    transaction.excluded = True
    db.commit()
    return {"message": "Transaction excluded", "transaction_id": transaction_id}


@router.put("/api/transactions/{transaction_id}/unexclude")
def set_transaction_unexcluded(
    transaction_id: int,
    db: Session = Depends(get_db),
):
    """
    Re-include a previously excluded transaction in reports.

    Returns 404 if the transaction does not exist.
    """
    transaction = get_transaction_or_404(db, transaction_id)
    transaction.excluded = False
    db.commit()
    return {"message": "Transaction unexcluded", "transaction_id": transaction_id}


# ── Delete routes ─────────────────────────────────────────────────────────────

@router.delete("/api/transactions/{transaction_id}")
def delete_transaction(
    transaction_id: int,
    db: Session = Depends(get_db),
):
    """
    Permanently delete a transaction by ID.

    Returns 404 if the transaction does not exist.
    """
    transaction = get_transaction_or_404(db, transaction_id)
    db.delete(transaction)
    db.commit()
    return {"message": f"Transaction {transaction_id} deleted"}


# ── Split routes ──────────────────────────────────────────────────────────────

@router.post("/api/transactions/{transaction_id}/split")
def split_transaction(
    transaction_id: int,
    body: SplitRequest,
    db: Session = Depends(get_db),
):
    """
    Split a transaction into multiple child transactions by category and amount.

    Validation rules:
      - At least 2 split lines are required.
      - Sum of abs(child amounts) must equal abs(parent amount).
      - Child amounts must match the sign of the parent.
      - Debit (negative) transactions cannot be split into income categories.
      - Cannot split a child transaction (one that already has a parent_id).

    If the parent is already split, existing children are deleted first (re-split).
    Children are marked excluded=True so they don't double-count in budget totals.
    Returns 404 if the transaction does not exist.
    """
    parent = get_transaction_or_404(db, transaction_id)

    if parent.parent_id is not None:
        raise HTTPException(status_code=400, detail="Cannot split a child transaction")

    if len(body.splits) < 2:
        raise HTTPException(status_code=400, detail="At least 2 split lines are required")

    split_total  = round(sum(abs(s.amount) for s in body.splits), 2)
    parent_total = round(abs(parent.amount), 2)
    if abs(split_total - parent_total) > 0.01:
        raise HTTPException(
            status_code=400,
            detail=f"Split amounts ({split_total}) must equal transaction total ({parent_total})"
        )

    # Validate sign and income-category rules per child
    parent_sign = 1 if parent.amount >= 0 else -1
    for item in body.splits:
        child_sign = 1 if item.amount >= 0 else -1
        if child_sign != parent_sign:
            raise HTTPException(
                status_code=400,
                detail="Child amounts must match the sign of the parent transaction"
            )
        if parent_sign < 0 and item.category_id:
            cat = db.query(Category).filter(Category.id == item.category_id).first()
            if cat and cat.is_income:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot split a debit transaction into income category '{cat.name}'"
                )

    # Re-split: delete existing children first
    if parent.is_split:
        db.query(Transaction).filter(Transaction.parent_id == transaction_id).delete()

    # Create child transactions
    sign = 1 if parent.amount >= 0 else -1
    for item in body.splits:
        db.add(Transaction(
            date=parent.date,
            amount=round(sign * abs(item.amount), 2),
            description=parent.description,
            notes=None,
            excluded=True,
            is_split=False,
            parent_id=parent.id,
            account_id=parent.account_id,
            category_id=item.category_id,
        ))

    parent.is_split = True
    db.commit()
    db.refresh(parent)

    children = db.query(Transaction).filter(Transaction.parent_id == transaction_id).all()
    return {
        "message":   "Transaction split successfully",
        "parent_id": parent.id,
        "is_split":  parent.is_split,
        "splits": [
            {
                "id":            c.id,
                "amount":        c.amount,
                "category_id":   c.category_id,
                "category_name": c.category.name if c.category else None,
            }
            for c in children
        ],
    }


@router.delete("/api/transactions/{transaction_id}/split")
def unsplit_transaction(
    transaction_id: int,
    db: Session = Depends(get_db),
):
    """
    Remove all split children and reset the transaction to unsplit.

    Returns 400 if the transaction is not currently split.
    Returns 404 if the transaction does not exist.
    """
    parent = get_transaction_or_404(db, transaction_id)

    if not parent.is_split:
        raise HTTPException(status_code=400, detail="Transaction is not split")

    deleted = db.query(Transaction).filter(Transaction.parent_id == transaction_id).delete()
    parent.is_split = False
    db.commit()

    return {
        "message":   f"Split removed, {deleted} child transactions deleted",
        "parent_id": parent.id,
        "is_split":  False,
    }
