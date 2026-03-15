"""
schemas.py — Pydantic request/response models for Budget Tracker.

All request body models used by the API routes are defined here so they
can be imported by any router without creating circular dependencies.
"""

from typing import Optional
from pydantic import BaseModel


class CategoryAssignment(BaseModel):
    """Assign a category to a transaction."""
    category_id: int


class BudgetUpdate(BaseModel):
    """Update the monthly budget for a category."""
    monthly_budget: float


class CategoryCreate(BaseModel):
    """Create a new budget category."""
    name: str
    monthly_budget: float = 0.0


class CategoryRename(BaseModel):
    """Rename an existing category."""
    name: str


class TransactionPatch(BaseModel):
    """Partial update for a transaction's description or notes."""
    description: Optional[str] = None
    notes: Optional[str] = None


class SplitItem(BaseModel):
    """A single line in a split transaction request."""
    amount: float
    category_id: Optional[int] = None


class SplitRequest(BaseModel):
    """Request body for splitting a transaction into multiple categories."""
    splits: list[SplitItem]
