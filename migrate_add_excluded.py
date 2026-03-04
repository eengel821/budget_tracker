"""
migrate_add_excluded.py - Adds the `excluded` column to the transactions table.

Safe to run on an existing database. If the column already exists the script
exits cleanly without making any changes.

Usage:
    python migrate_add_excluded.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from database import engine


def migrate():
    with engine.connect() as conn:
        # Check if column already exists
        result = conn.execute(
            __import__("sqlalchemy").text("PRAGMA table_info(transactions)")
        )
        columns = [row[1] for row in result]

        if "excluded" in columns:
            print("Column 'excluded' already exists — nothing to do.")
            return

        conn.execute(
            __import__("sqlalchemy").text(
                "ALTER TABLE transactions ADD COLUMN excluded BOOLEAN NOT NULL DEFAULT 0"
            )
        )
        conn.commit()
        print("Migration complete — 'excluded' column added to transactions table.")


if __name__ == "__main__":
    migrate()
