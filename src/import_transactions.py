import csv
import sys
import json
from pathlib import Path
from datetime import datetime
from database import SessionLocal
from models import Transaction, Account

# --- Configuration ---
IMPORT_FOLDER = Path("../csv_imports")
FORMATS_FILE = Path("../formats.json")

# --- Diagnostics ---
DB_PATH = Path("./budget.db").resolve()
print(f"Database location: {DB_PATH}")
if DB_PATH.exists():
    print(f"Database file found ✓ (size: {DB_PATH.stat().st_size} bytes)")
else:
    print("Database file not found yet — will be created on first import")

def load_formats():
    """
    Load CSV format definitions from formats.json.

    Returns a dictionary keyed by bank name (e.g. 'chase', 'becu'), where each
    value is a dict describing the column mappings and date format for that bank's
    CSV export. Exits the program with an error message if formats.json is not found.
    """
    
    if not FORMATS_FILE.exists():
        print(f"Error: formats.json not found at {FORMATS_FILE.resolve()}")
        sys.exit(1)
    with open(FORMATS_FILE, "r") as f:
        return json.load(f)


def parse_amount(row, fmt):
    """
    Extract and normalize a transaction amount from a CSV row. Normalize amount to a 
    negative float for debits, positive for credits.

    Handles two CSV layouts:
    - Single amount column (e.g. Chase, Discover): returns the value as-is,
      where negative values represent debits and positive values represent credits.
    - Split debit/credit columns (e.g. Capital One, BECU): returns debits as
      negative floats and credits as positive floats.

    Args:
        row (dict): A single CSV row as a dictionary of column name to value.
        fmt (dict): The format definition for the bank being imported.

    Returns:
        float: The normalized transaction amount.
    """

    if fmt["amount_col"]:
        return float(row[fmt["amount_col"]])
    else:
        debit = row[fmt["debit_col"]].strip()
        credit = row[fmt["credit_col"]].strip()
        if debit:
            return -abs(float(debit))
        elif credit:
            return abs(float(credit))
        return 0.0


def parse_date(row, fmt):
    """
    Extract and parse the transaction date from a CSV row.

    Converts the date string from the CSV into a Python date object using
    the date format specified in the bank's format definition.

    Args:
        row (dict): A single CSV row as a dictionary of column name to value.
        fmt (dict): The format definition for the bank being imported.

    Returns:
        datetime.date: The parsed transaction date.
    """

    return datetime.strptime(row[fmt["date_col"]].strip(), fmt["date_format"]).date()


def is_duplicate(db, date, amount, description):
    """
    Check whether a matching transaction already exists in the database.

    A transaction is considered a duplicate if another record exists with
    the same date, amount, and description. This is not guaranteed to catch
    all duplicates (e.g. two legitimate identical transactions on the same day)
    but covers the most common case of re-importing the same CSV file.

    Args:
        db: An active SQLAlchemy database session.
        date (datetime.date): The transaction date to check.
        amount (float): The transaction amount to check.
        description (str): The transaction description to check.

    Returns:
        bool: True if a matching transaction exists, False otherwise.
    """

    return bool(
        db.query(Transaction).filter(
            Transaction.date == date,
            Transaction.amount == amount,
            Transaction.description == description,
        ).first()
    )

def get_or_create_account(db, name):
    """
    Retrieve an existing account by name or create a new one if it doesn't exist.

    Used to ensure each bank has a corresponding account record in the database
    before transactions are imported. Newly created accounts are given a type
    of 'imported' by default.

    Args:
        db: An active SQLAlchemy database session.
        name (str): The account name to look up or create (typically the bank name).

    Returns:
        Account: The existing or newly created Account object.
    """

    account = db.query(Account).filter(Account.name == name).first()
    if not account:
        account = Account(name=name, type="imported")
        db.add(account)
        db.commit()
        db.refresh(account)
        print(f"Created new account: '{name}'")
    return account


def import_csv(filepath, bank_name, formats):
    """
    Import transactions from a CSV file into the database.

    Reads the CSV file at the given path, parses each row according to the
    format definition for the specified bank, checks for duplicates, and
    writes new transactions to the database. When a duplicate is found the
    user is prompted to import, skip, import all remaining duplicates, or
    skip all remaining duplicates.

    The original bank category (e.g. 'Shopping', 'Dining') is stored in the
    transaction's notes field until a full categorization system is implemented.

    Args:
        filepath (Path): Full path to the CSV file to import.
        bank_name (str): The bank key to look up in the formats dictionary
                         (e.g. 'chase', 'becu', 'capitalone', 'discover').
        formats (dict): The full format definitions loaded from formats.json.

    Returns:
        None. Prints a summary of imported, skipped, and duplicate rows on completion.
    """

    if bank_name not in formats:
        print(f"Unknown bank format '{bank_name}'. Available formats: {', '.join(formats.keys())}")
        sys.exit(1)

    fmt = formats[bank_name]
    db = SessionLocal()
    account = get_or_create_account(db, bank_name)

    imported = 0
    skipped = 0
    duplicates_skipped = 0
    duplicate_action = None  # None = ask each time, "skip_all", or "import_all"

    with open(filepath, newline="", encoding="utf-8-sig") as csvfile:
        reader = csv.DictReader(csvfile)
        reader.fieldnames = [f.strip().strip('"') for f in reader.fieldnames]

        for row in reader:
            row = {k: v.strip().strip('"') for k, v in row.items()}

            if not row.get(fmt["date_col"], "").strip():
                skipped += 1
                continue

            try:
                date = parse_date(row, fmt)
                amount = parse_amount(row, fmt)
                description = row[fmt["description_col"]].strip()
                category_name = row.get(fmt["category_col"] or "", "").strip()
            except (ValueError, KeyError) as e:
                print(f"Skipping row due to error: {e} | Row: {row}")
                skipped += 1
                continue

            if is_duplicate(db, date, amount, description):
                if duplicate_action == "skip_all":
                    duplicates_skipped += 1
                    continue
                elif duplicate_action == "import_all":
                    pass  # fall through to import
                else:
                    print(f"\nDuplicate found:")
                    print(f"  Date:        {date}")
                    print(f"  Description: {description}")
                    print(f"  Amount:      {amount}")
                    response = input("  Action? (y=import, n=skip, ia=import all, sa=skip all): ").strip().lower()
                    if response == "sa":
                        duplicate_action = "skip_all"
                        duplicates_skipped += 1
                        continue
                    elif response == "ia":
                        duplicate_action = "import_all"
                        pass  # fall through to import
                    elif response != "y":
                        duplicates_skipped += 1
                        continue

            transaction = Transaction(
                date=date,
                amount=amount,
                description=description,
                notes=category_name,
                account_id=account.id,
            )
            db.add(transaction)
            imported += 1

    db.commit()
    db.close()

    print(f"\n--- Import Complete: {filepath.name} ---")
    print(f"  Imported:           {imported}")
    print(f"  Duplicates skipped: {duplicates_skipped}")
    print(f"  Rows skipped:       {skipped}")


def list_available_files():
    """
    List all CSV files available in the import folder.

    Scans the IMPORT_FOLDER directory for files with a .csv extension and
    prints a numbered list to the terminal. Used in interactive mode to help
    the user select a file to import. Exits the program if no CSV files are found.

    Returns:
        list[Path]: A list of Path objects for each CSV file found.
    """
    
    files = list(IMPORT_FOLDER.glob("*.csv"))
    if not files:
        print(f"No CSV files found in {IMPORT_FOLDER.resolve()}")
        sys.exit(1)
    print(f"\nAvailable CSV files in {IMPORT_FOLDER.resolve()}:")
    for i, f in enumerate(files, 1):
        print(f"  {i}. {f.name}")
    return files


if __name__ == "__main__":
    formats = load_formats()

    if not IMPORT_FOLDER.exists():
        print(f"Error: Import folder '{IMPORT_FOLDER.resolve()}' does not exist.")
        sys.exit(1)

    if len(sys.argv) == 1:
        files = list_available_files()
        print(f"\nAvailable banks: {', '.join(formats.keys())}")
        filename = input("\nEnter filename to import: ").strip()
        bank_name = input("Enter bank name: ").strip().lower()
        filepath = IMPORT_FOLDER / filename

    elif len(sys.argv) == 3:
        filepath = IMPORT_FOLDER / sys.argv[1]
        bank_name = sys.argv[2].lower()

    else:
        print("Usage:")
        print("  python import_transactions.py                        # interactive mode")
        print("  python import_transactions.py <filename> <bank>      # direct mode")
        print(f"  Banks: {', '.join(formats.keys())}")
        sys.exit(1)

    if not filepath.exists():
        print(f"Error: File '{filepath}' not found.")
        sys.exit(1)

    import_csv(filepath, bank_name, formats)