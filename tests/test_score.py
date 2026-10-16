"""Fast tests: one per rule, plus edge cases. Run with: python -m pytest -q"""

import pytest

from riskcheck import score_transaction


def test_small_payment_is_not_risky():
    score, reasons = score_transaction(100, 1_000, 900, "PAYMENT")
    assert score == 0.0
    assert reasons == []


def test_large_amount_rule():
    score, reasons = score_transaction(250_000, 1_000_000, 750_000, "PAYMENT")
    assert score == pytest.approx(0.30)
    assert reasons == ["large amount (>= 200,000)"]


def test_medium_amount_rule_and_boundary():
    # exactly 50,000 counts as medium; exactly 200,000 counts as large
    assert score_transaction(50_000, 900_000, 850_000, "PAYMENT")[0] == pytest.approx(0.15)
    assert score_transaction(200_000, 900_000, 700_000, "PAYMENT")[0] == pytest.approx(0.30)


def test_risky_type_rule_ignores_letter_case():
    score, reasons = score_transaction(100, 1_000, 900, "cash_out")
    assert score == pytest.approx(0.20)
    assert reasons == ["risky transaction type (CASH_OUT)"]


def test_account_emptied_rule():
    score, reasons = score_transaction(100, 100, 0, "PAYMENT")
    assert score == pytest.approx(0.35)
    assert reasons == ["account emptied (balance went to zero)"]


def test_amount_larger_than_balance_rule():
    score, reasons = score_transaction(500, 100, 100, "PAYMENT")
    assert score == pytest.approx(0.25)
    assert reasons == ["amount is larger than the balance before"]


def test_score_is_capped_at_one():
    score, reasons = score_transaction(300_000, 100_000, 0, "TRANSFER")
    assert score == 1.0
    assert len(reasons) == 4  # every rule fired: 0.30 + 0.20 + 0.35 + 0.25 = 1.10


def test_bad_input_is_rejected():
    with pytest.raises(ValueError):
        score_transaction(-1, 100, 100, "PAYMENT")
    with pytest.raises(ValueError):
        score_transaction(10, 100, 90, "WIRE")
