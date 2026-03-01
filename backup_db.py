"""
backup_db.py - Creates a timestamped backup of budget.db.

Backups are stored in the backups/ folder in the project root.
Old backups are automatically pruned to keep only the most recent
MAX_BACKUPS files, preventing the folder from growing indefinitely.

Usage:
    python backup_db.py                  # create a backup
    python backup_db.py --list           # list all existing backups
    python backup_db.py --restore <file> # restore a specific backup
"""

import sys
import shutil
import argparse
from pathlib import Path
from datetime import datetime

# ── Configuration ─────────────────────────────────────────────────────────────

DB_PATH     = Path(__file__).resolve().parent / "data" / "budget.db"
BACKUP_DIR  = Path(__file__).resolve().parent / "backups"
MAX_BACKUPS = 30  # keep the most recent 30 backups


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_existing_backups() -> list[Path]:
    """Return a list of existing backup files sorted oldest to newest."""
    if not BACKUP_DIR.exists():
        return []
    return sorted(BACKUP_DIR.glob("budget_*.db"))


def create_backup() -> Path:
    """
    Create a timestamped backup of budget.db in the backups/ folder.

    The backup filename includes the date and time so backups sort
    chronologically and are easy to identify. Automatically removes
    the oldest backups if the total exceeds MAX_BACKUPS.

    Returns the Path of the newly created backup file.
    """
    if not DB_PATH.exists():
        print(f"Error: Database not found at {DB_PATH}")
        sys.exit(1)

    BACKUP_DIR.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"budget_{timestamp}.db"

    shutil.copy2(DB_PATH, backup_path)
    print(f"Backup created: {backup_path.name}")
    print(f"Size: {backup_path.stat().st_size:,} bytes")

    # Prune old backups
    existing = get_existing_backups()
    if len(existing) > MAX_BACKUPS:
        to_delete = existing[:len(existing) - MAX_BACKUPS]
        for old_backup in to_delete:
            old_backup.unlink()
            print(f"Pruned old backup: {old_backup.name}")

    print(f"\nTotal backups: {len(get_existing_backups())} / {MAX_BACKUPS}")
    return backup_path


def list_backups():
    """Print a numbered list of all existing backups with sizes and dates."""
    backups = get_existing_backups()
    if not backups:
        print("No backups found.")
        return

    print(f"\nExisting backups in {BACKUP_DIR}:\n")
    for i, backup in enumerate(reversed(backups), 1):
        size = backup.stat().st_size
        modified = datetime.fromtimestamp(backup.stat().st_mtime)
        print(f"  {i:2}. {backup.name}  |  {size:>10,} bytes  |  {modified.strftime('%Y-%m-%d %H:%M:%S')}")

    print(f"\nTotal: {len(backups)} backup{'s' if len(backups) != 1 else ''}")


def restore_backup(filename: str):
    """
    Restore a specific backup file over the current budget.db.

    Creates a safety backup of the current database before restoring
    so you can undo the restore if needed.

    Args:
        filename: The backup filename to restore (e.g. budget_20260201_120000.db)
    """
    backup_path = BACKUP_DIR / filename
    if not backup_path.exists():
        print(f"Error: Backup file '{filename}' not found in {BACKUP_DIR}")
        print("\nAvailable backups:")
        list_backups()
        sys.exit(1)

    # Safety backup of current database before restoring
    if DB_PATH.exists():
        safety_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safety_path = BACKUP_DIR / f"budget_{safety_timestamp}_pre_restore.db"
        shutil.copy2(DB_PATH, safety_path)
        print(f"Safety backup created: {safety_path.name}")

    shutil.copy2(backup_path, DB_PATH)
    print(f"Restored: {filename} → {DB_PATH}")
    print("Restart uvicorn to use the restored database.")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Budget database backup utility")
    parser.add_argument("--list", action="store_true", help="List all existing backups")
    parser.add_argument("--restore", metavar="FILENAME", help="Restore a specific backup file")
    args = parser.parse_args()

    if args.list:
        list_backups()
    elif args.restore:
        restore_backup(args.restore)
    else:
        create_backup()