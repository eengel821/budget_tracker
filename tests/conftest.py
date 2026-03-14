"""
conftest.py - Shared fixtures for all test modules.

Two levels of database fixture are provided:

  db     — raw SQLAlchemy session for unit tests that call helpers directly
  client — FastAPI TestClient wired to the same in-memory DB for API tests

The critical pattern for SQLite :memory: testing is that create_all,
the test session, and the app route handlers must ALL share the same
underlying connection object. SQLite creates a fresh empty database for
every new connection to :memory:, so if the session or the route handler
opens a new connection, they see an empty schema.

We solve this by:
  1. Creating one engine with a static pool (one connection, never closed)
  2. Running create_all on that engine
  3. Binding the test session to that engine
  4. Patching database.engine so init_db() and get_db() use the same engine
"""

import json
import os
import sys

import pytest
from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Ensure src/ is on the path so all src modules are importable from tests/
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from base import Base
import database as database_module
from database import get_db
from main import app
from models import Account, Category, Transaction


# ── Database fixtures ────────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def db():
    """
    Create a temporary in-memory SQLite database for each test.

    Uses StaticPool so that every request to this engine reuses the same
    underlying connection. This is required for SQLite :memory: databases —
    without it, each new connection sees a fresh empty database, so tables
    created in one connection are invisible to another.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False)
    session = SessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def client(db):
    """
    FastAPI TestClient wired to the test's in-memory database.

    Patches database.engine and database.SessionLocal so that:
      - init_db() in the lifespan creates tables on the test engine
      - get_db() yields a session bound to the same test engine

    The test session (db) and the app route handlers share the same
    StaticPool engine, so they all see the same in-memory database.
    """
    test_engine = db.bind
    TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False)

    original_engine = database_module.engine
    original_session = database_module.SessionLocal
    database_module.engine = test_engine
    database_module.SessionLocal = TestSessionLocal

    def override_get_db():
        try:
            yield db
        finally:
            pass  # lifecycle managed by db fixture

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c

    database_module.engine = original_engine
    database_module.SessionLocal = original_session
    app.dependency_overrides.clear()


# ── Seed fixtures ────────────────────────────────────────────────────────────

@pytest.fixture(scope="function")
def seed(db):
    """
    Seed the minimal categories and account needed by budget aggregation tests.
    Returns a dict of named records.
    """
    acct = Account(name="chase", type="imported")
    db.add(acct)

    groceries = Category(name="Groceries", monthly_budget=500.0)
    dining    = Category(name="Dining",    monthly_budget=200.0)
    savings   = Category(name="Emergency Fund", monthly_budget=0.0, is_savings=True)
    income    = Category(name="Salary",    monthly_budget=0.0, is_income=True)
    db.add_all([groceries, dining, savings, income])
    db.commit()

    return {
        "acct":      acct,
        "groceries": groceries,
        "dining":    dining,
        "savings":   savings,
        "income":    income,
    }


@pytest.fixture(scope="function")
def api_seed(db):
    """
    Seed standard account, categories, and one transaction for API tests.
    Returns a dict of named records.
    """
    acct = Account(name="testbank", type="imported")
    db.add(acct)

    groceries = Category(name="Groceries", monthly_budget=500.0)
    dining    = Category(name="Dining",    monthly_budget=200.0)
    income    = Category(name="Salary",    monthly_budget=0.0, is_income=True)
    savings   = Category(name="Emergency Fund", monthly_budget=0.0, is_savings=True)
    db.add_all([groceries, dining, income, savings])
    db.commit()

    txn = Transaction(
        date=date(2025, 3, 15),
        amount=-50.0,
        description="SAFEWAY",
        notes=None,
        excluded=False,
        account_id=acct.id,
        category_id=None,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)

    return {
        "acct":      acct,
        "groceries": groceries,
        "dining":    dining,
        "income":    income,
        "savings":   savings,
        "txn":       txn,
    }


# ── Legacy fixtures (kept for test_formats.py compatibility) ─────────────────

@pytest.fixture(scope="function")
def sample_account(db):
    """Create and return a sample Account for duplicate detection tests."""
    account = Account(name="chase", type="imported")
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@pytest.fixture(scope="function")
def sample_transaction(db, sample_account):
    """Create and return a sample Transaction for duplicate detection tests."""
    transaction = Transaction(
        date=date(2026, 2, 18),
        amount=-7.00,
        description="SDOT PAYBYPHONE PARKING",
        notes="Travel",
        account_id=sample_account.id,
    )
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    return transaction


@pytest.fixture(scope="session")
def formats():
    """Load and return the formats dictionary from formats.json."""
    formats_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "formats.json")
    )
    with open(formats_path) as f:
        return json.load(f)


@pytest.fixture(scope="function")
def tmp_csv(tmp_path):
    """Return a helper that writes a CSV string to a temporary file."""
    def _write(filename, content):
        filepath = tmp_path / filename
        filepath.write_text(content, encoding="utf-8")
        return filepath
    return _write