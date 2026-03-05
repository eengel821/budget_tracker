"""
migrate_add_is_income.py - Adds the `is_income` column to the categories table.

Safe to run on an existing database. If the column already exists the script
exits cleanly without making any changes.

Usage:
    python migrate_add_is_income.py
"""

import sys
from pathlib import Path
import sqlalchemy

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from database import engine


def migrate():
    with engine.connect() as conn:
        result = conn.execute(sqlalchemy.text("PRAGMA table_info(categories)"))
        columns = [row[1] for row in result]

        if "is_income" in columns:
            print("Column 'is_income' already exists — nothing to do.")
            return

        conn.execute(sqlalchemy.text(
            "ALTER TABLE categories ADD COLUMN is_income BOOLEAN NOT NULL DEFAULT 0"
        ))
        conn.commit()
        print("Migration complete — 'is_income' column added to categories table.")


if __name__ == "__main__":
    migrate()
