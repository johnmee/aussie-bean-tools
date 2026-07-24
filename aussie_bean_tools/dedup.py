"""Exact-amount duplicate detection for bank imports.

Up and StGeorge post exact decimal amounts, so two imported transactions are
duplicates only when their amounts match *exactly*. beangulp's default heuristic
comparator matches amounts within a percentage tolerance (5% by default; even a
tightened 0.1% still merges e.g. $1000.00 and $1000.50), which would silently
drop distinct transactions on import. This comparator requires exact amount
equality instead.

The importers install this as their ``cmp`` attribute. The date window is
applied by ``beangulp.extract.mark_duplicate_entries`` before ``cmp`` is called,
so it is not checked here.
"""

from beancount.core import data


def _amounts_by_account(entry):
    """Map (account, currency) -> number for each posting carrying an amount."""
    return {
        (posting.account, posting.units.currency): posting.units.number
        for posting in entry.postings
        if posting.units is not None
    }


def exact_amount_comparator(entry1, entry2):
    """Return True if the two transactions are duplicates by exact amount and date.

    Two transactions match when they have the same date, post the exact same
    amount to a shared account, and one transaction's set of accounts is a
    subset of the other's. This mirrors beangulp's heuristic comparator
    (shared/subset account sets) but replaces its percentage amount tolerance
    with exact equality, and requires the dates to match rather than merely be
    close. The transaction date (Up ``createdAt`` / StGeorge posting date) is
    stable across re-fetches, so a genuine re-import has the same date; this
    avoids merging distinct transactions of equal value on different days.
    """
    if not isinstance(entry1, data.Transaction) or not isinstance(
        entry2, data.Transaction
    ):
        return False

    if entry1.date != entry2.date:
        return False

    amounts1 = _amounts_by_account(entry1)
    amounts2 = _amounts_by_account(entry2)

    # Require at least one shared account posting with an identical amount.
    common = set(amounts1) & set(amounts2)
    if not any(amounts1[key] == amounts2[key] for key in common):
        return False

    accounts1 = {posting.account for posting in entry1.postings}
    accounts2 = {posting.account for posting in entry2.postings}
    return accounts1.issubset(accounts2) or accounts2.issubset(accounts1)
