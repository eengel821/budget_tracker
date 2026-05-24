# Keywords & Categories

Keywords are rules that tell the categorization engine how to classify transactions based on their description. They are the fastest and most reliable categorization method — when a keyword matches, the category is suggested with full confidence.

---

## keywords.json structure

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

| Field | Required | Description |
|---|---|---|
| `keyword` | Yes | Text to search for in the transaction description |
| `category` | Yes | Category name to suggest — must exactly match a category in the database |
| `match_type` | Yes | Currently only `"contains"` is supported |
| `priority` | No | Integer — lower number = checked first. Default 50. |
| `exclude_if_contains` | No | List of strings — skip this rule if any appear in the description |

---

## Specificity ordering

Keywords are automatically sorted longest-first before matching, so more specific rules always win over general ones regardless of their order in the file.

For example if you have both `"COSTCO GAS"` and `"COSTCO"`, a description of `"COSTCO GAS #0731"` will match `"COSTCO GAS"` → Gas, not `"COSTCO"` → Groceries.

You never need to manually order your keywords file — longer keywords are always checked first.

---

## Negative keywords

Use `exclude_if_contains` to express exceptions without creating an exhaustive list:

```json
{
    "keyword": "COSTCO",
    "category": "Groceries",
    "match_type": "contains",
    "exclude_if_contains": ["GAS", "TIRE", "OPTICAL", "PHARMACY"]
}
```

This matches any Costco transaction *except* those containing GAS, TIRE, OPTICAL, or PHARMACY — which have their own more specific rules.

---

## Priority field

Use `priority` to manually control ordering when length alone isn't enough:

```json
{
    "keyword": "COSTCO GAS",
    "category": "Gas",
    "match_type": "contains",
    "priority": 10
}
```

Lower priority number = checked first. Default is 50. Use priority 10 for rules that must always win, priority 90 for rules that should only fire as a last resort.

---

## Short keyword protection

Keywords shorter than 4 characters are automatically matched as whole words only — not as substrings. This prevents short tokens like `"PSE"` from matching inside unrelated words like `"EXPENSE"`.

---

## Description normalization

Before matching, descriptions are normalized:

- Uppercased
- Store numbers stripped (`#0731`, `#042`)
- Standalone numeric codes removed
- Excess whitespace collapsed

So `"COSTCO WHSE #0731 SEATTLE WA"` and `"COSTCO WHSE #0042"` both match the same keyword.

---

## Adding keywords

Open `keywords.json` and add entries to the `keywords` array. The app reads the file on every categorization run — no restart needed.

To find good keywords, go to the Transactions page, filter by uncategorized, and look at the description text for recurring merchants.

---

## exclude_keywords.json

Transactions whose descriptions match anything in `exclude_keywords.json` are automatically excluded from reports on import:

```json
{
    "exclude_keywords": ["DISCOVER PAYMENT", "CHASE CREDIT CARD", "TRANSFER TO SAVINGS"]
}
```

This prevents credit card payments and internal transfers from double-counting in your budget. Matching is case-insensitive substring matching.

---

## Adding categories

### From the browser

Go to **Manage Budgets** (`/budget/manage`):

1. Enter the category name in the **Add New Category** form
2. Optionally enter a monthly budget
3. Click **Add Category**

The new category is immediately available everywhere in the app.

### From categories.json

For bulk additions, edit `categories.json` and run the seeder:

```bash
python scripts\seed_categories.py
```

The seeder skips categories that already exist — safe to re-run at any time.
