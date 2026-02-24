"""
conftest.py - Shared fixtures for all test modules.

pytest automatically loads this file before running any tests. Fixtures defined
here are available to every test in the tests/ folder without needing to import them.
"""

import json
import pytest
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# We need to import Base and models so create_all knows about all tables
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from base import Base
from models import Account, Transaction


@pytest.fixture(scope="function")
def db():
    """
    Create a temporary in-memory SQLite database for each test.

    Uses SQLite's :memory: mode so no files are written to disk and each
    test starts with a completely clean, empty database. The session is
    closed and the database is discarded automatically after each test.
    """
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def sample_account(db):
    """
    Create and return a sample Account record for use in tests.

    Inserts a single account named 'chase' into the test database so that
    transactions can be created against it without needing to set one up
    in every individual test.
    """
    account = Account(name="chase", type="imported")
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@pytest.fixture(scope="function")
def sample_transaction(db, sample_account):
    """
    Create and return a sample Transaction record for use in duplicate detection tests.

    Inserts a single known transaction so that tests can verify whether
    is_duplicate() correctly identifies it as a duplicate.
    """
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
    """
    Load and return the formats dictionary from formats.json.

    Reads the real formats.json file from the project root so that parsing
    tests use the same format definitions as the production importer.
    Scoped to the session so the file is only read once across all tests.
    """
    formats_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "formats.json"))
    with open(formats_path, "r") as f:
        return json.load(f)


@pytest.fixture(scope="function")
def tmp_csv(tmp_path):
    """
    Return a helper function that writes a CSV string to a temporary file.

    Uses pytest's built-in tmp_path fixture to create a temporary directory
    that is automatically cleaned up after each test. The returned function
    accepts a filename and CSV content string and returns the full Path to
    the created file.

    Usage:
        def test_something(tmp_csv):
            filepath = tmp_csv("chase.csv", "header1,header2\\nval1,val2")
    """
    def _write(filename, content):
        filepath = tmp_path / filename
        filepath.write_text(content, encoding="utf-8")
        return filepath
    return _write
