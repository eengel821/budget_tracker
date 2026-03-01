# Adding Keywords & Categories

This guide covers how to add new keyword mappings to improve auto-categorization, and how to add new categories to the system.

---

## Adding keywords

Keywords are stored in `keywords.json` in the project root. Each entry maps a keyword to a category so the auto-categorizer can match transaction descriptions automatically.

### keywords.json structure

```json
{
    "keywords": [
        {
            "keyword": "STARBUCKS",
            "category": "Coffee Shops",
            "match_type": "contains"
        }
    ]
}
```

| Field | Description |
|---|---|
| `keyword` | The text to search for in the transaction description |
| `category` | The category name to assign — must exactly match a category in the database |
| `match_type` | Currently only `"contains"` is supported — matches if keyword appears anywhere in the description |

### Adding a new keyword

Open `keywords.json` and add a new entry to the `keywords` array:

```json
{
    "keyword": "COSTCO GAS",
    "category": "Gas",
    "match_type": "contains"
}
```

!!! tip
    You do not need to restart the app after editing `keywords.json`. The file is read each time auto-categorization runs.

### Tips for good keywords

- **Use the most specific keyword possible** — `STARBUCKS` is better than `STAR` which might accidentally match unrelated merchants
- **Check your transaction descriptions** — open the Transactions page, filter by uncategorized, and look at the actual description text to find good keywords
- **Keywords are case-insensitive** — `starbucks` and `STARBUCKS` both work the same way
- **First match wins** — if multiple keywords could match a description, the first one in the list is used. Put more specific keywords before more general ones.

### Finding good keywords from your transaction history

Run this from the project root to see uncategorized transaction descriptions:

```bash
python -c "
import sys
sys.path.insert(0, 'src')
from database import SessionLocal
from models import Transaction
db = SessionLocal()
transactions = db.query(Transaction).filter(
    Transaction.category_id.is_(None)
).all()
for t in transactions:
    print(t.description)
db.close()
"
```

---

## Adding categories

### From the browser

The easiest way to add a new category is from the **Manage Budgets** page at `/budget/manage`:

1. Enter the category name in the **Add New Category** form at the top
2. Optionally enter a monthly budget amount
3. Click **Add Category**

The new category appears immediately in the table and is available in all category dropdowns throughout the app.

### From categories.json

For adding multiple categories at once, edit `categories.json` in the project root:

```json
{
    "categories": [
        "Existing Category",
        "Another Category",
        "Your New Category"
    ]
}
```

Then run the seeder to insert the new categories:

```bash
python seed_categories.py
```

The seeder skips categories that already exist so it is safe to re-run at any time.

### Setting a budget for a new category

After adding a category, set its monthly budget amount from the **Manage Budgets** page at `/budget/manage`. Find the category in the table, enter the amount, and click **Save**.

---

## Category naming tips

- Use consistent capitalization — the category name is displayed exactly as entered throughout the app
- Keep names short enough to fit in table cells and chart labels
- Avoid special characters that might cause display issues
