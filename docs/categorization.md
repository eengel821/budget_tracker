# Transaction Categorization — Technical Reference

This document describes the design and mathematics of the budget tracker's automatic
categorization system. It covers the two-stage architecture (keyword rules + machine
learning), the algorithms involved, how confidence scores are produced, and how the
model improves over time as you correct its predictions.

---

## Architecture Overview

Categorization runs in two sequential stages. A transaction only reaches Stage 2 if
Stage 1 fails to match it.

```
Imported transaction
        │
        ▼
┌───────────────────────┐
│  Stage 1: Keyword     │  ──── match found ────▶  assign category
│  Rule Engine          │
└───────────────────────┘
        │ no match
        ▼
┌───────────────────────┐
│  Stage 2: ML Model    │  ──── prediction ─────▶  assign category
│  TF-IDF + Logistic    │                           + confidence score
│  Regression           │
└───────────────────────┘
        │ low confidence
        ▼
   Review queue
   (manual verification)
```

Stage 1 handles the easy, known cases with certainty. Stage 2 handles the ambiguous
remainder and produces a probability estimate alongside its prediction. Both stages
feed into the review queue, where you verify or correct the result. Every correction
you make is fed back into the model so it improves over time.

---

## Stage 1 — Keyword Rule Engine

### How it works

The keyword engine checks a transaction description against a prioritized list of
keyword rules. Each rule specifies a keyword string, a target category, and a match
type (currently `contains`, meaning the keyword can appear anywhere in the description).

The critical design change from the original implementation is **specificity ordering**:
rules are sorted by keyword length (longest first) before matching begins. This ensures
that "COSTCO GAS" is checked before "COSTCO", so a description like
"COSTCO GAS #0731" correctly resolves to Gas rather than Groceries.

**Matching order:**

1. Rules are sorted by keyword length, descending
2. Description is normalized (uppercased, store numbers stripped)
3. Each rule is checked in order; the first match wins
4. Negative keywords are checked — if the description contains an exclusion term for that rule, the match is skipped

**Normalization** strips common noise patterns before matching:

- Store/branch numbers: `#0731`, `#042`
- Location codes appended after merchant names
- Trailing transaction IDs

This means `COSTCO WHSE #0731` and `COSTCO WHSE #0042` both normalize to `COSTCO WHSE`
and match identically.

**Negative keywords** let you express exceptions without an exhaustive list. For example:

```json
{
  "keyword": "COSTCO",
  "category": "Groceries",
  "match_type": "contains",
  "exclude_if_contains": ["GAS", "TIRE", "OPTICAL"]
}
```

This matches any Costco transaction *except* those involving gas, tires, or optical — which
can have their own more specific rules.

### Why rules before ML?

For well-known, consistent merchants, rules are more reliable than a learned model.
"PUGET SOUND ENERGY" will always be your electric bill. A rule captures this with
100% certainty and zero training data required. The ML model only needs to cover the
long tail of merchants the rules don't know about.

---

## Stage 2 — Machine Learning Model

### Problem framing

Transaction categorization is a **multiclass text classification** problem. Given a
transaction description (and optionally amount, date, and account), predict which of
your *N* categories it belongs to — including "Exclude" as a valid category for
auto-excluded transactions like credit card payments.

We use two techniques in sequence: **TF-IDF** to convert raw text into numbers, and
**Logistic Regression** to classify those numbers into categories.

---

### Step 1 — TF-IDF: Converting Text to Numbers

A machine learning model cannot operate on raw strings. We need to convert each
transaction description into a fixed-length vector of numbers that captures what the
description is *about*.

**Term Frequency (TF)**

For a given description $d$ and a word (term) $t$, term frequency counts how often
$t$ appears in $d$ relative to the total number of words:

$$\text{TF}(t, d) = \frac{\text{number of times } t \text{ appears in } d}{\text{total number of terms in } d}$$

For a transaction description like "WHOLEFDS #0421 SEATTLE WA", each token gets a TF
score. "WHOLEFDS" appears once out of four tokens, so TF = 0.25.

**Inverse Document Frequency (IDF)**

TF alone is not enough. The word "PAYMENT" appears in many transaction descriptions
across many categories and tells you almost nothing. The word "WHOLEFDS" appears
almost exclusively in Groceries transactions and is highly informative.

IDF penalizes words that appear across many documents and rewards words that are
specific to few documents. Given a corpus of $D$ total training transactions:

$$\text{IDF}(t) = \log\left(\frac{D}{|\{d \in D : t \in d\}|}\right)$$

where the denominator is the number of training transactions containing term $t$.

If "PAYMENT" appears in 150 of 200 transactions: $\text{IDF} = \log(200/150) = 0.29$

If "WHOLEFDS" appears in 18 of 200 transactions: $\text{IDF} = \log(200/18) = 2.41$

**TF-IDF**

The combined score for term $t$ in document $d$ is simply the product:

$$\text{TF-IDF}(t, d) = \text{TF}(t, d) \times \text{IDF}(t)$$

After computing TF-IDF for all terms in all training documents, each transaction
becomes a **sparse vector** in a high-dimensional space — one dimension per unique
term in the training corpus. Most entries are zero (the term doesn't appear in that
transaction). The non-zero entries capture which terms are present and how informative
they are.

**The feature matrix**

For $M$ training transactions and $V$ unique vocabulary terms, we construct a matrix
$\mathbf{X} \in \mathbb{R}^{M \times V}$ where each row is the TF-IDF vector for one
transaction. In practice $V$ may be several thousand, but the matrix is sparse so
storage and computation remain efficient.

**Additional features**

Transaction amount and account can be appended to each row as additional numeric
features alongside the TF-IDF scores. Amount is log-transformed first
($\log(|\text{amount}|)$) to compress the range — a $3,000 purchase should not
dominate the $30 purchases by a factor of 100. Month of year (1–12) can be encoded
as a cyclic feature to capture seasonal patterns.

---

### Step 2 — Logistic Regression: Learning the Decision Boundaries

With transactions now represented as numeric vectors, logistic regression learns a
set of weights that map those vectors to category probabilities.

**Binary case (two categories)**

To build intuition, consider the binary case first. Logistic regression models the
probability that a transaction belongs to category 1 (vs category 0) as:

$$P(y=1 \mid \mathbf{x}) = \sigma(\mathbf{w}^T \mathbf{x} + b)$$

where $\mathbf{x}$ is the TF-IDF feature vector, $\mathbf{w}$ is a learned weight
vector of the same dimension, $b$ is a bias term, and $\sigma$ is the sigmoid function:

$$\sigma(z) = \frac{1}{1 + e^{-z}}$$

The sigmoid maps any real number to $(0, 1)$, which we interpret as a probability.
The dot product $\mathbf{w}^T \mathbf{x}$ computes a weighted sum of feature values —
features with large positive weights push the probability toward 1 (category 1),
features with large negative weights push it toward 0 (category 0).

**Multiclass extension — Softmax**

With $N$ categories, we have $N$ weight vectors $\mathbf{w}_1, \ldots, \mathbf{w}_N$
(one per category), organized as a weight matrix $\mathbf{W} \in \mathbb{R}^{N \times V}$.

For a transaction with feature vector $\mathbf{x}$, we compute a raw score (called
a **logit**) for each category:

$$z_k = \mathbf{w}_k^T \mathbf{x} + b_k \quad \text{for } k = 1, \ldots, N$$

These logits are converted to probabilities using the **softmax** function:

$$P(y = k \mid \mathbf{x}) = \frac{e^{z_k}}{\sum_{j=1}^{N} e^{z_j}}$$

Softmax exponentiates each logit and normalizes by the sum, ensuring all probabilities
are positive and sum to exactly 1. The category with the highest probability is the
predicted category. The probability itself is the **confidence score** shown in the
review queue.

**A concrete example**

Suppose you have 4 categories and the model computes logits:

| Category    | Logit $z_k$ | $e^{z_k}$ | Probability |
|-------------|-------------|-----------|-------------|
| Groceries   | 3.2         | 24.5      | 0.71        |
| Gas         | 1.8         | 6.0       | 0.17        |
| Restaurants | 1.1         | 3.0       | 0.09        |
| Home Supplies | 0.2       | 1.2       | 0.03        |
| **Sum**     |             | **34.7**  | **1.00**    |

The model predicts Groceries with 71% confidence. This is what gets displayed in the
review queue alongside the prediction.

---

### Step 3 — Training: Learning the Weights

**What training does**

Training adjusts the weight matrix $\mathbf{W}$ so that the model's predicted
probabilities align with your labeled transaction data. It does this by minimizing a
**loss function** — a measure of how wrong the model's predictions are.

**Cross-entropy loss**

The standard loss function for multiclass classification is cross-entropy. For a
single training transaction with true category $c$ and predicted probability vector
$\mathbf{p}$:

$$\mathcal{L} = -\log P(y = c \mid \mathbf{x}) = -\log p_c$$

If the true category is Groceries and the model assigns it probability 0.71, the loss
is $-\log(0.71) = 0.34$. If the model had assigned it 0.10, the loss would be
$-\log(0.10) = 2.30$ — much higher. The log function heavily penalizes confident
wrong predictions.

Over the full training set of $M$ transactions:

$$\mathcal{L}_{\text{total}} = -\frac{1}{M} \sum_{i=1}^{M} \log P(y = c_i \mid \mathbf{x}_i)$$

**Optimization**

Minimizing $\mathcal{L}_{\text{total}}$ over $\mathbf{W}$ is a convex optimization
problem with a unique global minimum — there are no local minima to get stuck in.
Scikit-learn solves it using L-BFGS or coordinate descent, which are variants of
gradient descent. The gradient of the loss with respect to each weight tells the
optimizer which direction to adjust it to reduce loss.

**Regularization**

With small training data (under 200 transactions), a model can **overfit** — memorizing
training examples instead of learning general patterns. Regularization adds a penalty
term to the loss that discourages large weight values:

$$\mathcal{L}_{\text{regularized}} = \mathcal{L}_{\text{total}} + \frac{\lambda}{2} \|\mathbf{W}\|^2$$

The parameter $\lambda$ (called `C = 1/λ` in scikit-learn) controls the strength of
regularization. Higher $\lambda$ (lower `C`) produces a simpler model that generalizes
better to new transactions. This is the most important hyperparameter to tune as your
dataset grows.

---

### Retraining from Corrections

Every time you correct a categorization in the review queue, the corrected label is
saved to the database. The model then retrains from scratch on all labeled transactions.

At your current data scale (under 200 transactions), a full retrain takes
milliseconds — scikit-learn can solve the optimization problem almost instantly for
datasets this size. There is no need for incremental or online learning algorithms;
retrain-from-scratch is simpler, more robust, and produces identical results.

**Why retraining from scratch is correct here**

Incremental learning algorithms (like stochastic gradient descent with partial_fit)
update weights based only on the new example. This can cause **catastrophic
forgetting** — the model drifts toward recent corrections and loses accuracy on earlier
patterns. Retraining from scratch always produces the globally optimal weights given
all labeled data, and at this scale the computational cost is negligible.

As your labeled dataset grows beyond ~5,000 transactions, the cost of a full retrain
starts to matter and incremental approaches become worth considering.

---

### Exclusion Handling

Transactions that should be auto-excluded (credit card payments, internal transfers,
etc.) are handled by treating "Exclude" as a regular category in both the keyword
engine and the ML model.

In the keyword engine, exclusion rules live in `exclude_keywords.json` and are checked
first, before any category rules. A match immediately marks the transaction as excluded.

In the ML model, any transaction you have manually excluded becomes a training example
with label "Exclude". The model learns to predict this label just like any other
category. In the review queue, predicted-Exclude transactions are flagged with a
distinct visual indicator so you can confirm before they are hidden from reports.

---

## Confidence Scores and the Review Queue

The ML model always produces a full probability distribution over all categories. The
review queue uses this in two ways:

**Display:** The predicted category and its probability are shown for each transaction,
e.g. "Groceries — 84%". This lets you instantly judge how much to trust the prediction
before verifying.

**Threshold gating:** Transactions below a confidence threshold (e.g. 70%) are
flagged for mandatory review even if they would otherwise be auto-assigned. This
threshold is configurable. Transactions above the threshold can optionally be
auto-assigned without appearing in the review queue at all, though keeping them in the
queue for spot-checking is recommended while the model is young.

The confidence threshold trades off two types of errors:

- **False positives** (auto-assigned wrong): Lower threshold → more auto-assignments → more errors slip through
- **False negatives** (correct prediction sent to review): Higher threshold → fewer auto-assignments → more manual work

A threshold of 80–85% is a reasonable starting point for a dataset of this size.

---

## Model Persistence

The trained model is serialized to disk using Python's `pickle` module (via
`joblib.dump` for efficiency with large numpy arrays). The serialized file stores the
full pipeline: the TF-IDF vectorizer (including its learned vocabulary and IDF weights)
and the logistic regression weight matrix.

On server startup, the model is loaded from disk. If no saved model exists (first run,
or after clearing training data), the system falls back to keyword-only categorization
until enough labeled transactions exist to train a reliable model. A minimum of
approximately 3–5 examples per category is needed before training is attempted.

---

## Summary

| Stage | Method | Handles | Confidence |
|-------|--------|---------|------------|
| 1 — Keywords | Rule matching with specificity ordering | Known merchants, recurring bills | Deterministic (100% or no match) |
| 2 — ML | TF-IDF + Logistic Regression | Unknown merchants, ambiguous descriptions | Probabilistic (softmax score) |
| Fallback | Manual review queue | Low-confidence predictions | N/A |

The system is designed to improve continuously. Every transaction you verify or correct
in the review queue adds a labeled example, which improves the model's accuracy on
similar future transactions. Over time, the fraction of transactions requiring manual
review should decrease as the model learns your specific spending patterns.
