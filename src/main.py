"""
main.py - FastAPI application entry point.

Defines all API endpoints for the budget tracker including transaction
retrieval, category management, and the categorization review workflow.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

import sys
from pathlib import Path

# Add src/ to the path so all modules can find each other
src_path = Path(__file__).resolve().parent
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from database import init_db, get_db
from models import Transaction, Category
from categorizer import categorize_all_uncategorized


# --- Lifespan ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Budget Tracker",
    description="Personal budget tracking API",
    lifespan=lifespan,
)


# --- Request Models ---

class CategoryAssignment(BaseModel):
    """Request body for assigning or overriding a transaction category."""
    category_id: int


# --- Transaction Endpoints ---

@app.get("/transactions", summary="Get all transactions")
def get_transactions(db: Session = Depends(get_db)):
    """
    Return all transactions in the database, ordered by date descending.
    Each transaction includes its assigned category if one has been set.
    """
    return db.query(Transaction).order_by(Transaction.date.desc()).all()


@app.get("/transactions/uncategorized", summary="Get uncategorized transactions")
def get_uncategorized_transactions(db: Session = Depends(get_db)):
    """
    Return all transactions that have not yet been assigned a category.
    Use this endpoint to build the manual review queue in the browser.
    """
    return db.query(Transaction).filter(
        Transaction.category_id.is_(None)
    ).order_by(Transaction.date.desc()).all()


@app.put("/transactions/{transaction_id}/category", summary="Assign or override a category")
def assign_category(
    transaction_id: int,
    body: CategoryAssignment,
    db: Session = Depends(get_db),
):
    """
    Assign or override the category on a single transaction.

    Accepts a category_id in the request body. Can be used to confirm an
    auto-suggested category or override an incorrectly assigned one.
    Returns a 404 if the transaction or category does not exist.
    """
    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")

    category = db.query(Category).filter(Category.id == body.category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    transaction.category_id = body.category_id
    db.commit()
    db.refresh(transaction)

    return {
        "message": f"Category '{category.name}' assigned to transaction {transaction_id}",
        "transaction_id": transaction_id,
        "category_id": category.id,
        "category_name": category.name,
    }


# --- Category Endpoints ---

@app.get("/categories", summary="Get all categories")
def get_categories(db: Session = Depends(get_db)):
    """
    Return the full list of available categories.
    Use this to populate category dropdowns in the browser interface.
    """
    return db.query(Category).order_by(Category.name).all()


# --- Categorization Endpoints ---

@app.post("/categorize", summary="Auto-categorize all uncategorized transactions")
def run_categorization(db: Session = Depends(get_db)):
    """
    Run the auto-categorization engine across all uncategorized transactions.

    Applies keyword matching first, then history-based matching. Returns a
    summary of how many transactions were auto-assigned vs left for manual review.
    Call this endpoint after importing a new CSV file to categorize as many
    transactions as possible before reviewing the remainder in the browser.
    """
    result = categorize_all_uncategorized(db)
    return {
        "message": "Categorization complete",
        **result,
    }
