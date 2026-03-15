"""
database.py — SQLAlchemy engine and session configuration for Budget Tracker.

Provides the database engine, session factory, and FastAPI dependency used
throughout the application. The database file is stored at data/budget.db
relative to the project root.
"""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import Base

DB_PATH     = Path(__file__).resolve().parent.parent / "data" / "budget.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine       = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)


def init_db() -> None:
    """
    Create all database tables defined in the SQLAlchemy models.

    Runs on application startup via the FastAPI lifespan event. Uses
    Base.metadata.create_all so existing tables are never dropped —
    only missing tables are created. Schema migrations are handled
    separately by Alembic.
    """
    Base.metadata.create_all(bind=engine)


def get_db():
    """
    FastAPI dependency that provides a database session per request.

    Opens a new SQLAlchemy session at the start of each request and
    closes it when the request completes, regardless of whether an
    exception was raised. Use with FastAPI's Depends():

        @router.get("/example")
        def example(db: Session = Depends(get_db)):
            ...

    Yields:
        Session: An active SQLAlchemy database session.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()