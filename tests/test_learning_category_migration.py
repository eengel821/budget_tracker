"""Tests for the learning-category data migration."""

import importlib.util
from pathlib import Path
from datetime import date

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

from categorizer import CategorizationModel, match_by_history
from models import Account, Category, Transaction


def test_history_uses_learning_category_not_budget_category(db):
    account = Account(name="testbank", type="imported")
    budget_category = Category(name="Family Travel")
    learning_category = Category(name="Dining")
    db.add_all([account, budget_category, learning_category])
    db.commit()

    db.add_all([
        Transaction(
            date=date(2026, 6, day),
            amount=-25.0,
            description="VACATION CAFE",
            account_id=account.id,
            category_id=budget_category.id,
            learning_category_id=learning_category.id,
        )
        for day in (1, 2, 3)
    ])
    db.commit()

    assert match_by_history("VACATION CAFE", db) == "Dining"


def test_model_training_uses_learning_labels_not_budget_categories(db, monkeypatch, tmp_path):
    pytest.importorskip("sklearn")

    account = Account(name="testbank", type="imported")
    budget_category = Category(name="Family Travel")
    dining = Category(name="Dining")
    lodging = Category(name="Lodging")
    db.add_all([account, budget_category, dining, lodging])
    db.commit()

    transactions = []
    for category, description in ((dining, "VACATION RESTAURANT"), (lodging, "VACATION HOTEL")):
        for day in (1, 2, 3):
            transactions.append(Transaction(
                date=date(2026, 6, day),
                amount=-50.0,
                description=description,
                account_id=account.id,
                category_id=budget_category.id,
                learning_category_id=category.id,
            ))
    db.add_all(transactions)
    db.commit()

    import categorizer
    monkeypatch.setattr(categorizer, "MODEL_PATH", tmp_path / "model.pkl")
    model = CategorizationModel()

    assert model.train(db)
    assert set(model._label_encoder.classes_) == {"Dining", "Lodging"}

def test_migration_backfills_existing_budget_categories():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "add_learning_category.py"
    )
    spec = importlib.util.spec_from_file_location("add_learning_category", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE transactions (id INTEGER PRIMARY KEY, category_id INTEGER)"
        ))
        connection.execute(text(
            "INSERT INTO transactions (id, category_id) VALUES (1, 4), (2, NULL)"
        ))

        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

        rows = connection.execute(text(
            "SELECT id, category_id, learning_category_id "
            "FROM transactions ORDER BY id"
        )).all()

    engine.dispose()
    assert rows == [(1, 4, 4), (2, None, None)]