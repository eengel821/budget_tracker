"""
seed_categories.py - Populates the categories table from categories.json.

Safe to re-run at any time — existing categories will not be duplicated.
New categories added to categories.json will be inserted on the next run.
Run this script once after setting up the database, and again any time
you add or rename categories in categories.json.

Usage:
    python seed_categories.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from database import SessionLocal, init_db
from models import Category

CATEGORIES_FILE = Path(__file__).resolve().parent / "categories.json"


def load_categories():
    """
    Load the category list from categories.json.

    Returns a list of category name strings. Exits the program with an
    error message if categories.json cannot be found.
    """
    if not CATEGORIES_FILE.exists():
        print(f"Error: categories.json not found at {CATEGORIES_FILE}")
        sys.exit(1)
    with open(CATEGORIES_FILE, "r") as f:
        data = json.load(f)
    return data["categories"]


def seed_categories():
    """
    Insert categories from categories.json into the database.

    Skips any category that already exists by name so the script is safe
    to re-run without creating duplicates. Prints a summary of how many
    categories were inserted vs already existed.
    """
    init_db()
    db = SessionLocal()
    categories = load_categories()

    inserted = 0
    skipped = 0

    for name in categories:
        existing = db.query(Category).filter(Category.name == name).first()
        if existing:
            skipped += 1
        else:
            db.add(Category(name=name))
            inserted += 1

    db.commit()
    db.close()

    print(f"\n--- Category Seed Complete ---")
    print(f"  Inserted: {inserted}")
    print(f"  Skipped (already existed): {skipped}")
    print(f"  Total categories in database: {inserted + skipped}")


if __name__ == "__main__":
    seed_categories()
