"""
routers/categories.py — Category API routes for Budget Tracker.

Handles creating, renaming, toggling flags, and updating budgets for
budget categories. All routes return JSON.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Category
from schemas import BudgetUpdate, CategoryCreate, CategoryRename

router = APIRouter()


def get_category_or_404(db: Session, category_id: int) -> Category:
    """
    Fetch a Category by ID or raise HTTP 404.

    Args:
        db: An active SQLAlchemy database session.
        category_id: The primary key of the category to fetch.

    Returns:
        The Category object if found.

    Raises:
        HTTPException: 404 if the category does not exist.
    """
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    return category


@router.get("/api/categories")
def get_categories(db: Session = Depends(get_db)):
    """Return all categories ordered by name as JSON."""
    return db.query(Category).order_by(Category.name).all()


@router.post("/api/categories")
def create_category(
    body: CategoryCreate,
    db: Session = Depends(get_db),
):
    """
    Create a new budget category.

    Returns 409 if a category with the same name already exists.
    """
    existing = db.query(Category).filter(Category.name == body.name).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Category '{body.name}' already exists")

    category = Category(name=body.name, monthly_budget=body.monthly_budget)
    db.add(category)
    db.commit()
    db.refresh(category)

    return {
        "id":             category.id,
        "name":           category.name,
        "monthly_budget": category.monthly_budget,
    }


@router.put("/api/categories/{category_id}/name")
def rename_category(
    category_id: int,
    body: CategoryRename,
    db: Session = Depends(get_db),
):
    """
    Rename a category.

    Returns 409 if the new name is already used by another category.
    Returns 404 if the category does not exist.
    """
    category = get_category_or_404(db, category_id)

    existing = db.query(Category).filter(
        Category.name == body.name,
        Category.id != category_id,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Category '{body.name}' already exists")

    old_name = category.name
    category.name = body.name
    db.commit()

    return {
        "message":     f"Category renamed from '{old_name}' to '{body.name}'",
        "category_id": category_id,
        "name":        category.name,
    }


@router.put("/api/categories/{category_id}/is_income")
def toggle_category_is_income(
    category_id: int,
    db: Session = Depends(get_db),
):
    """
    Toggle the is_income flag on a category.

    Returns 404 if the category does not exist.
    """
    category = get_category_or_404(db, category_id)
    category.is_income = not category.is_income
    db.commit()
    return {
        "category_id": category_id,
        "is_income":   category.is_income,
    }


@router.put("/api/categories/{category_id}/is_savings")
def toggle_category_is_savings(
    category_id: int,
    db: Session = Depends(get_db),
):
    """
    Toggle the is_savings flag on a category.

    Returns 404 if the category does not exist.
    """
    category = get_category_or_404(db, category_id)
    category.is_savings = not category.is_savings
    db.commit()
    return {
        "category_id": category_id,
        "is_savings":  category.is_savings,
    }


@router.put("/api/categories/{category_id}/budget")
def update_category_budget(
    category_id: int,
    body: BudgetUpdate,
    db: Session = Depends(get_db),
):
    """
    Update the monthly budget amount for a category.

    Returns 404 if the category does not exist.
    """
    category = get_category_or_404(db, category_id)
    category.monthly_budget = body.monthly_budget
    db.commit()

    return {
        "message":        f"Budget updated for '{category.name}'",
        "category_id":    category.id,
        "monthly_budget": category.monthly_budget,
    }
