"""
models.py - SQLAlchemy ORM models for Budget Tracker.

Defines the Account, Category, and Transaction tables.
"""

from sqlalchemy import Boolean, Column, Date, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from base import Base


class Account(Base):
    __tablename__ = "accounts"

    id   = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    type = Column(String, nullable=True)

    transactions = relationship("Transaction", back_populates="account")


class Category(Base):
    __tablename__ = "categories"

    id             = Column(Integer, primary_key=True, index=True)
    name           = Column(String, unique=True, nullable=False)
    monthly_budget = Column(Float, default=0.0)
    is_income      = Column(Boolean, default=False, nullable=False)

    transactions = relationship("Transaction", back_populates="category")


class Transaction(Base):
    __tablename__ = "transactions"

    id          = Column(Integer, primary_key=True, index=True)
    date        = Column(Date, nullable=False)
    amount      = Column(Float, nullable=False)
    description = Column(String, nullable=False)
    notes       = Column(String, nullable=True)
    excluded    = Column(Boolean, default=False, nullable=False)
    account_id  = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)

    account  = relationship("Account", back_populates="transactions")
    category = relationship("Category", back_populates="transactions")
