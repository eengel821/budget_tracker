"""
models.py - SQLAlchemy ORM models for Budget Tracker.

Defines the Account, Category, Transaction, and Savings tables.
"""

from sqlalchemy import Boolean, Column, Date, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship, backref

from base import Base


class Account(Base):
    """
    A bank or financial institution account from which transactions are imported.

    Each imported CSV file is associated with one Account so transactions can
    be filtered and grouped by their source institution.
    """
    __tablename__ = "accounts"

    id   = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    type = Column(String, nullable=True)

    transactions         = relationship("Transaction", back_populates="account")
    savings_transactions = relationship("SavingsTransaction", back_populates="account")


class Category(Base):
    """
    A budget category used to classify transactions.

    Categories are marked as is_income=True for income sources (e.g. salary),
    is_savings=True for savings jars (zero-budget categories tracked in the
    savings section), or left as standard expense categories with a monthly
    budget amount.
    """
    __tablename__ = "categories"

    id             = Column(Integer, primary_key=True, index=True)
    name           = Column(String, unique=True, nullable=False)
    monthly_budget = Column(Float, default=0.0)
    is_income      = Column(Boolean, default=False, nullable=False)
    is_expense     = Column(Boolean, default=True)
    is_savings     = Column(Boolean, default=False)

    transactions = relationship(
        "Transaction",
        foreign_keys="Transaction.category_id",
        back_populates="category",
    )
    suggested_transactions = relationship(
        "Transaction",
        foreign_keys="Transaction.suggested_category_id",
        back_populates="suggested_category",
    )
    savings_allocations  = relationship("SavingsAllocation", back_populates="category")
    template_items       = relationship("AllocationTemplateItem", back_populates="category")


class Transaction(Base):
    """
    A single financial transaction imported from a bank CSV or entered manually.

    Transactions can be excluded from reports (excluded=True), split into
    child transactions (is_split=True), or left as normal uncategorized
    entries pending review. Split children reference their parent via
    parent_id and are marked excluded=True to prevent double-counting.

    The suggestion columns store the categorization engine's prediction prior
    to user confirmation in the review queue:

      suggested_category_id — FK to the predicted Category (nullable)
      suggestion_confidence — float 0.0–1.0; None for keyword/history matches
                              since those are deterministic rather than probabilistic
      suggestion_source     — "keyword", "history", or "ml"; used by the review
                              queue UI to show the appropriate badge and pre-tick
                              rows that are likely correct

    Once the user confirms a suggestion in the review queue, category_id is set
    and all three suggestion columns are cleared.
    """
    __tablename__ = "transactions"

    id          = Column(Integer, primary_key=True, index=True)
    date        = Column(Date, nullable=False)
    amount      = Column(Float, nullable=False)
    description = Column(String, nullable=False)
    notes       = Column(String, nullable=True)
    excluded    = Column(Boolean, default=False, nullable=False)
    is_split    = Column(Boolean, default=False, nullable=False)
    parent_id   = Column(Integer, ForeignKey("transactions.id"), nullable=True)
    account_id  = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)

    # Optional budget month override — when set, the budget page uses this
    # instead of transaction.date for month attribution. The transactions page
    # always uses the real date. Supports accrual-style reimbursement tracking.
    budget_month = Column(Date, nullable=True)

    # Categorization engine suggestion — populated at import time, cleared on confirm
    suggested_category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    suggestion_confidence  = Column(Float, nullable=True)
    suggestion_source      = Column(String, nullable=True)

    account            = relationship("Account", back_populates="transactions")
    category           = relationship(
        "Category",
        foreign_keys=[category_id],
        back_populates="transactions",
    )
    suggested_category = relationship(
        "Category",
        foreign_keys=[suggested_category_id],
        back_populates="suggested_transactions",
    )
    splits = relationship(
        "Transaction",
        backref=backref("parent", remote_side="Transaction.id"),
        foreign_keys="Transaction.parent_id",
    )


class SavingsTransaction(Base):
    """
    One row per transaction in a savings account (deposit, withdrawal, interest).
    Imported from CSV or entered manually.
    is_allocated is False until the full amount has been split across jars
    (SavingsAllocation rows) and those allocations sum to the transaction amount.
    """
    __tablename__ = "savings_transactions"

    id           = Column(Integer, primary_key=True, index=True)
    date         = Column(Date, nullable=False)
    amount       = Column(Float, nullable=False)   # positive = deposit, negative = withdrawal
    description  = Column(String, nullable=False)
    notes        = Column(String, nullable=True)
    is_allocated = Column(Boolean, default=False, nullable=False)
    account_id   = Column(Integer, ForeignKey("accounts.id"), nullable=True)

    account     = relationship("Account", back_populates="savings_transactions")
    allocations = relationship("SavingsAllocation", back_populates="savings_transaction",
                               cascade="all, delete-orphan")


class SavingsAllocation(Base):
    """
    One row per jar split on a SavingsTransaction.
    Example: a $1000 withdrawal might have three SavingsAllocation rows:
      Cars       -$250
      Life Ins   -$500
      Gifts      -$250
    The sum of all allocation amounts must equal the parent transaction amount.
    Amount can be negative (withdrawal from jar) or positive (deposit into jar).
    A jar balance can go negative — this is allowed by design.
    """
    __tablename__ = "savings_allocations"

    id                      = Column(Integer, primary_key=True, index=True)
    savings_transaction_id  = Column(Integer, ForeignKey("savings_transactions.id"), nullable=False)
    category_id             = Column(Integer, ForeignKey("categories.id"), nullable=False)
    amount                  = Column(Float, nullable=False)

    savings_transaction = relationship("SavingsTransaction", back_populates="allocations")
    category            = relationship("Category", back_populates="savings_allocations")


class AllocationTemplate(Base):
    """
    A saved default allocation pattern for deposits (e.g. 'Paycheck').
    When a new deposit is being allocated, the default template pre-fills
    the jar split amounts so you don't have to enter them from scratch each time.
    Only one template can be the default (is_default=True) at a time.
    """
    __tablename__ = "allocation_templates"

    id         = Column(Integer, primary_key=True, index=True)
    name       = Column(String, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)

    items = relationship("AllocationTemplateItem", back_populates="template",
                         cascade="all, delete-orphan")


class AllocationTemplateItem(Base):
    """
    One row per jar in an AllocationTemplate.
    Example: the 'Paycheck' template might have items for Cars=$100,
    Life Insurance=$200, Home Repair=$200, etc.
    These amounts are used to pre-fill the allocation modal for deposits.
    """
    __tablename__ = "allocation_template_items"

    id          = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("allocation_templates.id"), nullable=False)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)
    amount      = Column(Float, nullable=False)

    template = relationship("AllocationTemplate", back_populates="items")
    category = relationship("Category", back_populates="template_items")
