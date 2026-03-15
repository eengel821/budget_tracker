"""
main.py — FastAPI application entry point for Budget Tracker.

Initialises the app, mounts static files, and registers all routers.
Business logic lives in services/; route handlers live in routers/.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from database import init_db
from deps import src_path
from routers import categories, imports, pages, savings, transactions


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run database initialisation on startup."""
    init_db()
    yield


app = FastAPI(title="Budget Tracker", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=src_path / "static"), name="static")

# ── Routers ───────────────────────────────────────────────────────────────────

app.include_router(pages.router)
app.include_router(transactions.router)
app.include_router(categories.router)
app.include_router(savings.router)
app.include_router(imports.router)
