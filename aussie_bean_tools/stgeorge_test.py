import datetime
import os
import tempfile
from decimal import Decimal

from beancount.core.data import Balance

from .stgeorge import StGeorgeImporter, StGeorgeTransaction

HEADER = "Date,Description,Debit,Credit,Balance"
FIELDNAMES = HEADER.split(",")


def to_dict(raw):
    """Convert the raw line to a csv reader style dict."""
    return dict(zip(FIELDNAMES, raw.split(",")))


def test_simple_row():
    row = to_dict("09/02/2022,Su Australia 1479342325,,2089.84,32108.39")
    trans = StGeorgeTransaction(row)
    assert trans.narration == "Su Australia 1479342325"
    assert trans.date == datetime.date(2022, 2, 9)
    print(trans)


def test_datetime_row():
    row = to_dict(
        "15/01/2022,Osko Deposit                  15Jan09:08 Ustacest Lile Malliak,,1000,26954.6"
    )
    trans = StGeorgeTransaction(row)
    assert trans.narration == "Osko Deposit"
    assert trans.date == datetime.date(2022, 1, 15)
    assert trans.credit == Decimal("1000")
    assert trans.payee == "Ustacest Lile Malliak"
    print(trans)


def test_location_row():
    row = to_dict(
        "28/01/2022,Visa Purchase                 25Jan Netflix.Com          Melbourne,22.99,,37374.03"
    )
    trans = StGeorgeTransaction(row)
    assert trans.narration == "Visa Purchase"
    assert trans.date == datetime.date(2022, 1, 28)
    assert trans.debit == Decimal("22.99")
    assert trans.payee == "Netflix.Com"
    assert trans.location == "Melbourne"

    # row = to_dict("07/02/2022,Visa Purchase O/Seas          05Feb Usd22.64 Porkbun.Com,32.12,,30087.9")
    # trans = stgeorge.StGeorgeTransaction(row)


def _extract_from_csv(csv_content):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(csv_content)
        tmpname = f.name

    try:
        return StGeorgeImporter("Assets:Bank:Test").extract(tmpname)
    finally:
        os.unlink(tmpname)


def test_balance_at_month_start():
    # CSV is newest-first; balance 350 is after the last April transaction,
    # which equals the account balance at the opening of May 1.
    entries = _extract_from_csv(
        "Date,Description,Debit,Credit,Balance\n"
        "15/05/2026,May Purchase,100,,250\n"
        "28/04/2026,April Credit,,100,350\n"
        "15/04/2026,April Purchase,50,,250\n"
    )
    balance_entries = [e for e in entries if isinstance(e, Balance)]
    month_bal = next(b for b in balance_entries if b.date == datetime.date(2026, 5, 1))
    assert month_bal.amount.number == Decimal("350")
    assert month_bal.amount.currency == "AUD"


def test_final_balance_dated_day_after_most_recent_transaction():
    entries = _extract_from_csv(
        "Date,Description,Debit,Credit,Balance\n"
        "15/05/2026,May Purchase,100,,250\n"
        "05/05/2026,May Credit,,50,350\n"
    )
    balance_entries = [e for e in entries if isinstance(e, Balance)]
    assert len(balance_entries) == 1
    bal = balance_entries[0]
    assert bal.date == datetime.date(2026, 5, 16)
    assert bal.amount.number == Decimal("250")
    assert bal.amount.currency == "AUD"
