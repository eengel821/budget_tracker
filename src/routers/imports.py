"""
routers/imports.py — CSV import and auto-categorization routes for Budget Tracker.

Handles uploading and parsing CSV files for both regular transactions and
savings account transactions. Also handles the auto-categorize-all action
from the review queue.
"""

import csv as csvlib
import io
import json
import os
import tempfile
from datetime import datetime as dt
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from categorizer import categorize_all_uncategorized
from database import get_db
from deps import src_path
from import_transactions import load_exclude_keywords
from models import Account, SavingsTransaction, Transaction
from services.aggregations import get_uncategorized_count

router = APIRouter()


# ── Savings format definitions ────────────────────────────────────────────────
# Kept here rather than in formats.json since savings imports are separate
# from the main bank transaction imports and have different column structures.

SAVINGS_FORMATS: dict = {
    "etrade": {
        "date_col":        "TransactionDate",
        "description_col": "Description",
        "amount_col":      "Amount",
        "date_format":     "%m/%d/%y",
        "header_marker":   "TransactionDate",  # skip preamble rows
    },
    "becu": {
        "date_col":        "Date",
        "description_col": "Description",
        "amount_col":      "Amount",
        "date_format":     "%m/%d/%Y",
        "header_marker":   None,
    },
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_amount(row: dict, fmt: dict) -> float:
    """
    Extract and normalise a transaction amount from a CSV row.

    Handles both single-column (amount_col) and split-column (debit_col /
    credit_col) formats. Returns a negative float for debits and a positive
    float for credits.

    Args:
        row: A CSV row dict.
        fmt: The bank format definition.

    Returns:
        Normalised float amount.
    """
    if fmt["amount_col"]:
        return float(row[fmt["amount_col"]])
    debit  = row[fmt["debit_col"]].strip()
    credit = row[fmt["credit_col"]].strip()
    if debit:  return -abs(float(debit))
    if credit: return  abs(float(credit))
    return 0.0


def _parse_date(row: dict, fmt: dict):
    """
    Parse the transaction date from a CSV row.

    Args:
        row: A CSV row dict.
        fmt: The bank format definition.

    Returns:
        A datetime.date object.
    """
    return dt.strptime(row[fmt["date_col"]].strip(), fmt["date_format"]).date()


def _get_or_create_account(db: Session, name: str, account_type: str) -> Account:
    """
    Fetch an existing Account by name or create a new one.

    Args:
        db: An active SQLAlchemy database session.
        name: The account name (typically the bank name).
        account_type: The type to assign if creating ('imported' or 'savings').

    Returns:
        The existing or newly created Account object.
    """
    account = db.query(Account).filter(Account.name == name).first()
    if not account:
        account = Account(name=name, type=account_type)
        db.add(account)
        db.commit()
        db.refresh(account)
    return account


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/api/import")
async def import_transactions_endpoint(
    file: UploadFile = File(...),
    bank: str = Form(...),
    db: Session = Depends(get_db),
):
    """
    Accept a CSV file upload and import transactions for the given bank.

    Reads the uploaded file, parses rows according to the bank's format
    definition in formats.json, deduplicates, and auto-excludes transactions
    matching keywords in exclude_keywords.json.

    Returns a JSON summary with counts of imported, auto_excluded,
    duplicates_skipped, skipped, and uncategorized_count.

    Returns 400 for non-CSV files or unknown bank names.
    Returns 500 if formats.json is not found on the server.
    """
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported")

    formats_path = src_path.parent / "formats.json"
    if not formats_path.exists():
        raise HTTPException(status_code=500, detail="formats.json not found on server")

    with open(formats_path) as f:
        formats = json.load(f)

    if bank not in formats:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown bank '{bank}'. Available: {', '.join(formats.keys())}"
        )

    fmt         = formats[bank]
    exclude_kws = load_exclude_keywords()
    contents    = await file.read()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        tmp.write(contents)
        tmp_path = Path(tmp.name)

    try:
        account  = _get_or_create_account(db, bank, "imported")
        imported = skipped = auto_excluded = duplicates_skipped = 0

        with open(tmp_path, newline="", encoding="utf-8-sig") as csvfile:
            reader = csvlib.DictReader(csvfile)
            reader.fieldnames = [f.strip().strip('"') for f in reader.fieldnames]

            for row in reader:
                row = {k: v.strip().strip('"') for k, v in row.items()}
                if not row.get(fmt["date_col"], "").strip():
                    skipped += 1
                    continue
                try:
                    txn_date = _parse_date(row, fmt)
                    amount   = _parse_amount(row, fmt)
                    desc     = row[fmt["description_col"]].strip()
                    cat_note = row.get(fmt.get("category_col") or "", "").strip()
                except (ValueError, KeyError):
                    skipped += 1
                    continue

                exists = db.query(Transaction).filter(
                    Transaction.date        == txn_date,
                    Transaction.amount      == amount,
                    Transaction.description == desc,
                ).first()
                if exists:
                    duplicates_skipped += 1
                    continue

                txn = Transaction(
                    date=txn_date, amount=amount, description=desc,
                    notes=cat_note, account_id=account.id,
                )
                if any(kw in desc.upper() for kw in exclude_kws):
                    txn.excluded  = True
                    auto_excluded += 1

                db.add(txn)
                imported += 1

        db.commit()

    finally:
        os.unlink(tmp_path)

    return {
        "imported":            imported,
        "auto_excluded":       auto_excluded,
        "duplicates_skipped":  duplicates_skipped,
        "skipped":             skipped,
        "uncategorized_count": get_uncategorized_count(db),
    }


@router.post("/api/savings/import")
async def import_savings_transactions(
    file: UploadFile = File(...),
    bank: str = Form(...),
    db: Session = Depends(get_db),
):
    """
    Import savings account transactions from a CSV file.

    Supports etrade (with preamble skipping) and becu formats. Deduplicates
    by date + amount + description. New transactions are marked is_allocated=False.

    Returns a JSON summary with imported, duplicates_skipped, and skipped counts.
    Returns 400 for non-CSV files or unsupported bank names.
    """
    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported")

    if bank not in SAVINGS_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown bank '{bank}' for savings import"
        )

    fmt      = SAVINGS_FORMATS[bank]
    contents = await file.read()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        tmp.write(contents)
        tmp_path = tmp.name

    try:
        account  = _get_or_create_account(db, bank, "savings")
        imported = skipped = duplicates_skipped = 0

        with open(tmp_path, newline="", encoding="utf-8-sig") as csvfile:
            raw_lines = csvfile.readlines()

        # Skip preamble rows until the header marker is found (e.g. ETrade)
        header_marker = fmt.get("header_marker")
        if header_marker:
            start_idx = next(
                (i for i, line in enumerate(raw_lines) if line.strip().startswith(header_marker)),
                0
            )
            raw_lines = raw_lines[start_idx:]

        raw_lines = [line for line in raw_lines if line.strip()]
        reader = csvlib.DictReader(io.StringIO("".join(raw_lines)))

        for row in reader:
            row = {k.strip(): v.strip().strip('"') for k, v in row.items() if k}
            if not row.get(fmt["date_col"], "").strip():
                skipped += 1
                continue
            try:
                txn_date = dt.strptime(row[fmt["date_col"]].strip(), fmt["date_format"]).date()
                amount   = float(row[fmt["amount_col"]].replace(",", "").replace("$", ""))
                desc     = row[fmt["description_col"]].strip()
            except (ValueError, KeyError):
                skipped += 1
                continue

            exists = db.query(SavingsTransaction).filter(
                SavingsTransaction.date        == txn_date,
                SavingsTransaction.amount      == amount,
                SavingsTransaction.description == desc,
            ).first()
            if exists:
                duplicates_skipped += 1
                continue

            db.add(SavingsTransaction(
                date=txn_date, amount=amount, description=desc,
                is_allocated=False, account_id=account.id,
            ))
            imported += 1

        db.commit()

    finally:
        os.unlink(tmp_path)

    return {
        "imported":           imported,
        "duplicates_skipped": duplicates_skipped,
        "skipped":            skipped,
    }


@router.post("/categorize-all")
def categorize_all(db: Session = Depends(get_db)):
    """
    Run the auto-categorization engine across all uncategorized transactions.

    Redirects to the review page with a summary message after completion.
    """
    result  = categorize_all_uncategorized(db)
    message = (
        f"Auto-categorized {result['auto_assigned']} transactions. "
        f"{result['needs_review']} still need review."
    )
    return RedirectResponse(url=f"/review?message={message}", status_code=303)
