"""
seed_budgets.py - Seeds monthly budget amounts into the categories table.

Safe to re-run at any time — existing amounts will be updated to match
the values defined here. Run this script from the project root.

Usage:
    python seed_budgets.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from database import SessionLocal, init_db
from models import Category

BUDGET_AMOUNTS = {
    "Income":                   0.00,
    "Mortgage":              2000.00,
    "Internet":               150.00,
    "Insurance":              300.00,
    "Gas":                    350.00,
    "Kids":                   400.00,
    "Cash":                     0.00,
    "Coffee Shops":             0.00,
    "Leisure":                 25.00,
    "Subscription":            50.00,
    "Restaurants":            400.00,
    "Groceries":              900.00,
    "Misc":                    75.00,
    "Phones":                 210.00,
    "Doctor":                  50.00,
    "Home Supplies":           75.00,
    "Family Travel":            0.00,
    "Vacation Travel":          0.00,
    "Gifts":                    0.00,
    "Electric":                 0.00,
    "Cars":                     0.00,
    "Home Improvements":        0.00,
    "Water/Sewer/Garbage":      0.00,
    "Property Taxes":           0.00,
}


def seed_budgets():
    """
    Update monthly_budget amounts on all categories defined in BUDGET_AMOUNTS.

    Categories that exist in the database but are not in BUDGET_AMOUNTS are
    left unchanged. Categories in BUDGET_AMOUNTS that don't exist in the
    database are reported as warnings.
    """
    init_db()
    db = SessionLocal()

    updated = 0
    not_found = 0

    for name, amount in BUDGET_AMOUNTS.items():
        category = db.query(Category).filter(Category.name == name).first()
        if category:
            category.monthly_budget = amount
            updated += 1
        else:
            print(f"  Warning: Category '{name}' not found in database — skipping")
            not_found += 1

    db.commit()
    db.close()

    print(f"\n--- Budget Seed Complete ---")
    print(f"  Updated:   {updated}")
    print(f"  Not found: {not_found}")


if __name__ == "__main__":
    seed_budgets()
