"""Regression tests for the importers' duplicate-detection rule.

Up and StGeorge post exact decimal amounts, so two imported transactions are
duplicates only when their amounts are **exactly** equal. beangulp's default
heuristic comparator matches amounts within a percentage tolerance (5% by
default). Even a tightened 0.1% still merges, say, $1000.00 and $1000.50, which
would silently drop distinct transactions on import. These tests require exact
amount equality: an identical amount is a duplicate, and any difference — even a
single cent on a large amount — is a distinct transaction that must be kept.

Under beancount v2 the tolerance was enforced by a single global monkeypatch
(``similar.SimilarityComparator.EPSILON``) that happened to cover every
importer. Under beangulp the comparison is per-importer, set via each class's
``cmp`` attribute; a missing or looser ``cmp`` silently drops real transactions.
"""

import datetime

import pytest
from beancount.core import amount, data, flags, number

from aussie_bean_tools import StGeorgeImporter, UpbankImporter

ACCOUNT = "Assets:Bank:Test"

# (existing amount, newly-imported amount, expected to be flagged duplicate)
CASES = [
    # Exactly equal amounts are duplicates.
    ("-6.95", "-6.95", True),
    ("-1000.00", "-1000.00", True),
    ("-0.01", "-0.01", True),
    ("500.00", "500.00", True),
    # Any difference means a distinct transaction, even within the old 0.1%
    # tolerance, and even a single cent apart on a large amount.
    ("-6.95", "-7.08", False),   # clearly different (~1.9%)
    ("-6.95", "-6.96", False),   # one cent apart on a small amount
    ("-1000.00", "-1000.01", False),  # one cent apart on a large amount
    ("-1000.00", "-1000.50", False),  # ~0.05%: merged by the old tolerance
    ("-500.00", "-500.20", False),    # ~0.04%: merged by the old tolerance
]


def _txn(value, day=10):
    """A one-posting transaction for the test account, dated in Jan 2026."""
    return data.Transaction(
        meta=data.new_metadata("test", 0),
        date=datetime.date(2026, 1, day),
        flag=flags.FLAG_OKAY,
        payee="SHOP",
        narration="coffee",
        tags=data.EMPTY_SET,
        links=data.EMPTY_SET,
        postings=[
            data.Posting(
                ACCOUNT,
                amount.Amount(number.D(value), "AUD"),
                None,
                None,
                None,
                None,
            )
        ],
    )


@pytest.mark.parametrize("importer_cls", [UpbankImporter, StGeorgeImporter])
@pytest.mark.parametrize("existing_value, new_value, is_duplicate", CASES)
def test_dedup_requires_exact_amount(
    importer_cls, existing_value, new_value, is_duplicate
):
    importer = importer_cls(ACCOUNT)
    new = [_txn(new_value)]

    importer.deduplicate(new, existing=[_txn(existing_value)])

    marked = bool(new[0].meta.get("__duplicate__"))
    assert marked is is_duplicate, (
        f"{existing_value} vs {new_value}: expected "
        f"{'duplicate' if is_duplicate else 'kept'}, got "
        f"{'duplicate' if marked else 'kept'}"
    )


@pytest.mark.parametrize("importer_cls", [UpbankImporter, StGeorgeImporter])
def test_dedup_requires_same_date(importer_cls):
    # Same exact amount on the same date is a duplicate; the same amount on a
    # different date is a distinct transaction (e.g. two $4.50 coffees on
    # consecutive days), even though it falls within beangulp's default
    # two-day comparison window.
    importer = importer_cls(ACCOUNT)

    same_date = [_txn("-4.50", day=10)]
    importer.deduplicate(same_date, existing=[_txn("-4.50", day=10)])
    assert same_date[0].meta.get("__duplicate__"), "same amount + same date is a duplicate"

    next_day = [_txn("-4.50", day=11)]
    importer.deduplicate(next_day, existing=[_txn("-4.50", day=10)])
    assert not next_day[0].meta.get(
        "__duplicate__"
    ), "same amount on a different date must be kept"
