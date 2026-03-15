"""
routers/savings.py — Savings account API routes for Budget Tracker.

Handles manual transaction entry, CSV imports, jar allocation, rebalancing,
template management, and summary stats for the savings account section.
"""

import calendar
from datetime import date as date_type
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import (
    AllocationTemplate,
    AllocationTemplateItem,
    Category,
    SavingsAllocation,
    SavingsTransaction,
)
from services.aggregations import get_jar_balances

router = APIRouter()


# ── Shared helper ─────────────────────────────────────────────────────────────

def get_savings_txn_or_404(db: Session, txn_id: int) -> SavingsTransaction:
    """
    Fetch a SavingsTransaction by ID or raise HTTP 404.

    Args:
        db: An active SQLAlchemy database session.
        txn_id: The primary key of the savings transaction to fetch.

    Returns:
        The SavingsTransaction object if found.

    Raises:
        HTTPException: 404 if the transaction does not exist.
    """
    txn = db.query(SavingsTransaction).filter(SavingsTransaction.id == txn_id).first()
    if not txn:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return txn


# ── Transaction CRUD ──────────────────────────────────────────────────────────

@router.post("/api/savings/transactions")
def create_savings_transaction(
    body: dict,
    db: Session = Depends(get_db),
):
    """
    Manually create a savings transaction.

    body expects: { "date": str, "amount": float, "description": str, "notes": str? }
    Returns 400 for missing or invalid fields.
    """
    try:
        txn_date = date_type.fromisoformat(body["date"])
        amount   = float(body["amount"])
        desc     = str(body["description"]).strip()
        notes    = body.get("notes")
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid data: {e}")

    if not desc:
        raise HTTPException(status_code=400, detail="Description is required")

    txn = SavingsTransaction(
        date=txn_date, amount=amount, description=desc,
        notes=notes, is_allocated=False,
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)

    return {
        "id":           txn.id,
        "date":         str(txn.date),
        "amount":       txn.amount,
        "description":  txn.description,
        "is_allocated": txn.is_allocated,
    }


@router.delete("/api/savings/transactions/{txn_id}")
def delete_savings_transaction(txn_id: int, db: Session = Depends(get_db)):
    """
    Delete a savings transaction and all its allocations (cascade delete).

    Returns 404 if the transaction does not exist.
    """
    txn = get_savings_txn_or_404(db, txn_id)
    db.delete(txn)
    db.commit()
    return {"message": f"Savings transaction {txn_id} deleted"}


@router.patch("/api/savings/transactions/{txn_id}")
def edit_savings_transaction(txn_id: int, body: dict, db: Session = Depends(get_db)):
    """
    Partially update a savings transaction's date, description, amount, or notes.

    Only fields present in the request body are updated.
    Returns 400 for invalid values. Returns 404 if the transaction does not exist.
    """
    txn = get_savings_txn_or_404(db, txn_id)

    try:
        if "date" in body:
            txn.date = date_type.fromisoformat(body["date"])
        if "description" in body:
            desc = str(body["description"]).strip()
            if not desc:
                raise HTTPException(status_code=400, detail="Description cannot be empty")
            txn.description = desc
        if "amount" in body:
            txn.amount = round(float(body["amount"]), 2)
        if "notes" in body:
            txn.notes = body["notes"] or None
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid data: {e}")

    db.commit()
    db.refresh(txn)

    return {
        "id":           txn.id,
        "date":         str(txn.date),
        "description":  txn.description,
        "amount":       txn.amount,
        "notes":        txn.notes,
        "is_allocated": txn.is_allocated,
    }


# ── Allocation routes ─────────────────────────────────────────────────────────

@router.get("/api/savings/transactions/{txn_id}/allocations")
def get_savings_allocations(txn_id: int, db: Session = Depends(get_db)):
    """
    Return existing allocations for a transaction and current jar balances.

    Used by the allocation modal to pre-fill amounts and show the jar panel.
    Returns 404 if the transaction does not exist.
    """
    txn = get_savings_txn_or_404(db, txn_id)

    existing = db.query(SavingsAllocation)\
                 .filter(SavingsAllocation.savings_transaction_id == txn_id)\
                 .all()

    allocations = [
        {"category_id": a.category_id, "amount": round(a.amount, 2)}
        for a in existing
    ]

    return {
        "txn_id":       txn_id,
        "amount":       round(txn.amount, 2),
        "description":  txn.description,
        "date":         str(txn.date),
        "is_allocated": txn.is_allocated,
        "allocations":  allocations,
        "jars":         get_jar_balances(db),
    }


@router.put("/api/savings/transactions/{txn_id}/allocations")
def save_savings_allocations(
    txn_id: int,
    body: dict,
    db: Session = Depends(get_db),
):
    """
    Replace all allocations for a transaction with the submitted set.

    Marks the transaction as is_allocated=True if the total allocation
    matches the transaction amount within $0.01.

    body expects: { "allocations": [{"category_id": int, "amount": float}, ...] }
    Zero-amount items are silently skipped.
    Returns 400 if any category is not a savings jar or data is malformed.
    Returns 404 if the transaction does not exist.
    """
    txn = get_savings_txn_or_404(db, txn_id)

    raw = body.get("allocations", [])
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="allocations must be a list")

    items = []
    for item in raw:
        try:
            cat_id = int(item["category_id"])
            amount = round(float(item["amount"]), 2)
        except (KeyError, ValueError, TypeError):
            raise HTTPException(
                status_code=400,
                detail="Each allocation needs category_id and amount"
            )
        if amount == 0:
            continue
        cat = db.query(Category).filter(
            Category.id == cat_id,
            Category.is_savings == True,  # noqa: E712
        ).first()
        if not cat:
            raise HTTPException(
                status_code=400,
                detail=f"Category {cat_id} is not a savings jar"
            )
        items.append({"category_id": cat_id, "amount": amount})

    # Replace existing allocations
    db.query(SavingsAllocation)\
      .filter(SavingsAllocation.savings_transaction_id == txn_id)\
      .delete()

    for item in items:
        db.add(SavingsAllocation(
            savings_transaction_id=txn_id,
            category_id=item["category_id"],
            amount=item["amount"],
        ))

    total_allocated  = round(sum(i["amount"] for i in items), 2)
    txn.is_allocated = abs(total_allocated - round(txn.amount, 2)) < 0.01
    db.commit()

    return {
        "txn_id":          txn_id,
        "is_allocated":    txn.is_allocated,
        "total_allocated": total_allocated,
        "allocations":     items,
    }


# ── Jar routes ────────────────────────────────────────────────────────────────

@router.get("/api/savings/jars")
def get_savings_jars(db: Session = Depends(get_db)):
    """Return current balance for all savings jars. Used by the rebalance modal."""
    return {"jars": get_jar_balances(db)}


@router.get("/api/savings/jars/{category_id}/history")
def get_jar_history(category_id: int, db: Session = Depends(get_db)):
    """
    Return full allocation history, stats, and 12-month chart data for a jar.

    Stats include: current balance, average monthly deposit, YTD deposits,
    YTD withdrawals, and net YTD. Chart shows end-of-month balances for the
    last 12 months.

    Returns 404 if the category does not exist.
    """
    cat = db.query(Category).filter(Category.id == category_id).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")

    allocs = (
        db.query(SavingsAllocation)
          .join(SavingsTransaction, SavingsAllocation.savings_transaction_id == SavingsTransaction.id)
          .filter(SavingsAllocation.category_id == category_id)
          .order_by(SavingsTransaction.date.asc())
          .all()
    )

    # Build running balance history
    running = 0.0
    entries = []
    for a in allocs:
        running += a.amount
        entries.append({
            "date":            str(a.savings_transaction.date),
            "description":     a.savings_transaction.description,
            "amount":          round(a.amount, 2),
            "running_balance": round(running, 2),
        })

    current_balance = round(running, 2)
    entries_display = list(reversed(entries))

    # YTD stats
    current_year  = date_type.today().year
    ytd_allocs    = [a for a in allocs if a.savings_transaction.date.year == current_year]
    withdrawn_ytd = abs(sum(a.amount for a in ytd_allocs if a.amount < 0))
    deposited_ytd = sum(a.amount for a in ytd_allocs if a.amount > 0)
    net_ytd       = deposited_ytd - withdrawn_ytd

    # Average monthly deposit
    deposit_months: dict = {}
    for a in allocs:
        if a.amount > 0:
            key = (a.savings_transaction.date.year, a.savings_transaction.date.month)
            deposit_months[key] = deposit_months.get(key, 0) + a.amount
    avg_deposit = (
        round(sum(deposit_months.values()) / len(deposit_months), 2)
        if deposit_months else 0.0
    )

    # 12-month balance chart
    today          = date_type.today()
    chart_labels   = []
    chart_balances = []
    for i in range(11, -1, -1):
        total_months = today.year * 12 + today.month - i - 1
        yr  = total_months // 12
        mo  = total_months % 12 + 1
        last_day = calendar.monthrange(yr, mo)[1]
        cutoff   = date_type(yr, mo, last_day)
        bal = sum(a.amount for a in allocs if a.savings_transaction.date <= cutoff)
        chart_labels.append(datetime(yr, mo, 1).strftime("%b %y"))
        chart_balances.append(round(bal, 2))

    return {
        "category_id":    category_id,
        "name":           cat.name,
        "balance":        current_balance,
        "avg_deposit":    avg_deposit,
        "withdrawn_ytd":  round(withdrawn_ytd, 2),
        "net_ytd":        round(net_ytd, 2),
        "chart_labels":   chart_labels,
        "chart_balances": chart_balances,
        "entries":        entries_display,
    }


@router.post("/api/savings/rebalance")
def rebalance_jars(body: dict, db: Session = Depends(get_db)):
    """
    Create a $0 rebalance transaction and apply jar allocation adjustments.

    Each allocation amount is a delta: positive = add to jar, negative = remove.
    The sum of all amounts must equal $0.00 — rebalancing moves money between
    jars without changing the account total.

    body expects: { "allocations": [{"category_id": int, "amount": float}, ...] }
    Returns 400 if allocations are missing or don't net to zero.
    """
    raw = body.get("allocations", [])
    if not raw:
        raise HTTPException(status_code=400, detail="No allocations provided")

    items = []
    for item in raw:
        try:
            cat_id = int(item["category_id"])
            amount = round(float(item["amount"]), 2)
        except (KeyError, ValueError, TypeError):
            raise HTTPException(
                status_code=400,
                detail="Each allocation needs category_id and amount"
            )
        if amount != 0:
            items.append({"category_id": cat_id, "amount": amount})

    net = round(sum(i["amount"] for i in items), 2)
    if abs(net) > 0.01:
        raise HTTPException(
            status_code=400,
            detail=f"Rebalance allocations must net to $0.00 (got {net:+.2f})"
        )

    txn = SavingsTransaction(
        date=date_type.today(),
        amount=0.0,
        description="Jar Rebalance",
        notes="Automatic rebalance",
        is_allocated=True,
    )
    db.add(txn)
    db.flush()

    for item in items:
        db.add(SavingsAllocation(
            savings_transaction_id=txn.id,
            category_id=item["category_id"],
            amount=item["amount"],
        ))

    db.commit()
    db.refresh(txn)

    return {
        "id":          txn.id,
        "date":        str(txn.date),
        "description": txn.description,
        "amount":      txn.amount,
        "allocations": items,
    }


# ── Template routes ───────────────────────────────────────────────────────────

@router.get("/api/savings/templates/default")
def get_default_template(db: Session = Depends(get_db)):
    """
    Return the default allocation template for pre-filling the deposit modal.

    Returns empty items list if no default template has been saved yet.
    """
    template = db.query(AllocationTemplate)\
                 .filter(AllocationTemplate.is_default == True)  # noqa: E712
    template = template.first()

    if not template:
        return {"template_id": None, "name": None, "items": []}

    return {
        "template_id": template.id,
        "name":        template.name,
        "items": [
            {"category_id": item.category_id, "amount": round(item.amount, 2)}
            for item in template.items
        ],
    }


@router.put("/api/savings/templates/default")
def save_default_template(body: dict, db: Session = Depends(get_db)):
    """
    Save or replace the default allocation template.

    Creates the template if it doesn't exist; replaces all items if it does.
    Zero-amount items are silently skipped.

    body expects: { "name": str, "items": [{"category_id": int, "amount": float}, ...] }
    Returns 400 for malformed items.
    """
    name = str(body.get("name", "Default Template")).strip() or "Default Template"
    raw  = body.get("items", [])

    items = []
    for item in raw:
        try:
            cat_id = int(item["category_id"])
            amount = round(float(item["amount"]), 2)
        except (KeyError, ValueError, TypeError):
            raise HTTPException(
                status_code=400,
                detail="Each item needs category_id and amount"
            )
        if amount == 0:
            continue
        items.append({"category_id": cat_id, "amount": amount})

    template = db.query(AllocationTemplate)\
                 .filter(AllocationTemplate.is_default == True)  # noqa: E712
    template = template.first()

    if template:
        template.name = name
        db.query(AllocationTemplateItem)\
          .filter(AllocationTemplateItem.template_id == template.id)\
          .delete()
    else:
        template = AllocationTemplate(name=name, is_default=True)
        db.add(template)
        db.flush()

    for item in items:
        db.add(AllocationTemplateItem(
            template_id=template.id,
            category_id=item["category_id"],
            amount=item["amount"],
        ))

    db.commit()

    return {
        "template_id": template.id,
        "name":        template.name,
        "items":       items,
    }


# ── Summary route ─────────────────────────────────────────────────────────────

@router.get("/api/savings/summary")
def get_savings_summary(db: Session = Depends(get_db)):
    """
    Return the four stat tile values for the savings page header.

    Used for live tile refresh after allocation changes without a full page reload.
    Returns account_balance, jar_total, deposits_ytd, and withdrawals_ytd.
    """
    all_txns     = db.query(SavingsTransaction).all()
    current_year = date_type.today().year

    account_balance = round(sum(t.amount for t in all_txns), 2)
    deposits_ytd    = round(sum(
        t.amount for t in all_txns
        if t.amount > 0 and t.date.year == current_year
    ), 2)
    withdrawals_ytd = round(abs(sum(
        t.amount for t in all_txns
        if t.amount < 0 and t.date.year == current_year
    )), 2)

    jar_balances = get_jar_balances(db)
    jar_total    = round(sum(j["balance"] for j in jar_balances), 2)

    return {
        "account_balance":  account_balance,
        "jar_total":        jar_total,
        "deposits_ytd":     deposits_ytd,
        "withdrawals_ytd":  withdrawals_ytd,
    }
