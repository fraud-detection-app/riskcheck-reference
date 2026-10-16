"""A small, readable risk score for one money transaction.

Every rule adds a few points. The points are added up, capped at 1.0, and the
rules that fired are returned as plain-English reasons.

    score, reasons = score_transaction(250_000, 300_000, 50_000, "TRANSFER")
"""

# --- The rules live here, as constants, so they are easy to read and change. ---

LARGE_AMOUNT = 200_000        # at or above this the amount is "large"
MEDIUM_AMOUNT = 50_000        # at or above this the amount is "medium"
LARGE_AMOUNT_POINTS = 0.30
MEDIUM_AMOUNT_POINTS = 0.15

RISKY_TYPES = {"TRANSFER", "CASH_OUT"}   # money that leaves the system
KNOWN_TYPES = RISKY_TYPES | {"PAYMENT", "CASH_IN", "DEBIT"}
RISKY_TYPE_POINTS = 0.20

EMPTIED_POINTS = 0.35         # the account balance went to exactly zero
OVERDRAFT_POINTS = 0.25       # the amount is bigger than the balance before

MAX_SCORE = 1.0


def score_transaction(
    amount: float,
    balance_before: float,
    balance_after: float,
    txn_type: str,
) -> tuple[float, list[str]]:
    """Return ``(score, reasons)`` for one transaction.

    Args:
        amount: money moved by the transaction (must not be negative).
        balance_before: sender's balance before the transaction.
        balance_after: sender's balance after the transaction.
        txn_type: PAYMENT, CASH_IN, CASH_OUT, DEBIT or TRANSFER (any letter case).

    Returns:
        score: a number from 0.0 (looks normal) to 1.0 (looks very risky).
        reasons: one short sentence for every rule that fired (empty if none).

    Raises:
        ValueError: if the amount or a balance is negative, or the type is unknown.
    """
    txn_type = txn_type.strip().upper()
    if amount < 0 or balance_before < 0 or balance_after < 0:
        raise ValueError("amount and balances must not be negative")
    if txn_type not in KNOWN_TYPES:
        raise ValueError(f"unknown transaction type: {txn_type!r}")

    score = 0.0
    reasons: list[str] = []

    # Rule 1: how big is the amount? (only one of the two size rules can fire)
    if amount >= LARGE_AMOUNT:
        score += LARGE_AMOUNT_POINTS
        reasons.append(f"large amount (>= {LARGE_AMOUNT:,})")
    elif amount >= MEDIUM_AMOUNT:
        score += MEDIUM_AMOUNT_POINTS
        reasons.append(f"medium amount (>= {MEDIUM_AMOUNT:,})")

    # Rule 2: does the money leave the system?
    if txn_type in RISKY_TYPES:
        score += RISKY_TYPE_POINTS
        reasons.append(f"risky transaction type ({txn_type})")

    # Rule 3: was the account emptied?
    if amount > 0 and balance_before > 0 and balance_after == 0:
        score += EMPTIED_POINTS
        reasons.append("account emptied (balance went to zero)")

    # Rule 4: is more money moving than the account held?
    if amount > balance_before:
        score += OVERDRAFT_POINTS
        reasons.append("amount is larger than the balance before")

    return round(min(score, MAX_SCORE), 2), reasons
