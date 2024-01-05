import datetime
from decimal import Decimal

from . import stgeorge

HEADER = "Date,Description,Debit,Credit,Balance"
FIELDNAMES = HEADER.split(",")


def to_dict(raw):
    """Convert the raw line to a csv reader style dict."""
    return dict(zip(FIELDNAMES, raw.split(",")))


def test_simple_row():
    row = to_dict("09/02/2022,Su Australia 1479342325,,2089.84,32108.39")
    trans = stgeorge.StGeorgeTransaction(row)
    assert trans.narration == "Su Australia 1479342325"
    assert trans.date == datetime.date(2022, 2, 9)
    print(trans)


def test_datetime_row():
    row = to_dict(
        "15/01/2022,Osko Deposit                  15Jan09:08 Eustacest Lile Walliak,,1000,26954.6"
    )
    trans = stgeorge.StGeorgeTransaction(row)
    assert trans.narration == "Osko Deposit"
    assert trans.date == datetime.date(2022, 1, 15)
    assert trans.credit == Decimal("1000")
    assert trans.payee == "Eustacest Lile Walliak"
    print(trans)


def test_location_row():
    row = to_dict(
        "28/01/2022,Visa Purchase                 25Jan Netflix.Com          Melbourne,22.99,,37374.03"
    )
    trans = stgeorge.StGeorgeTransaction(row)
    assert trans.narration == "Visa Purchase"
    assert trans.date == datetime.date(2022, 1, 28)
    assert trans.debit == Decimal("22.99")
    assert trans.payee == "Netflix.Com"
    assert trans.location == "Melbourne"

    # row = to_dict("07/02/2022,Visa Purchase O/Seas          05Feb Usd22.64 Porkbun.Com,32.12,,30087.9")
    # trans = stgeorge.StGeorgeTransaction(row)
