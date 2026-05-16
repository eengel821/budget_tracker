"""
main.py — FastAPI application entry point for Budget Tracker.

Initialises the app, mounts static files, and registers all routers.
Business logic lives in services/; route handlers live in routers/.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import subprocess
import sys

from database import init_db
from deps import src_path
from routers import categories, imports, pages, savings, transactions


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run database initialisation and backup on startup."""
    init_db()

    # Run a backup every time the server starts (including --reload restarts).
    # backup_db.py lives in the project root (one level above src/).
    backup_script = src_path.parent / "scripts" / "backup_db.py"
    if backup_script.exists():
        subprocess.run([sys.executable, str(backup_script)], check=False)

    yield


app = FastAPI(title="Budget Tracker", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=src_path / "static"), name="static")

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(pages.router)
app.include_router(transactions.router)
app.include_router(categories.router)
app.include_router(savings.router)
app.include_router(imports.router)
