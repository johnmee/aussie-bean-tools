"""Tests for the Up balance assertion.

Beancount checks a `balance` directive at the *start* of its date; Up reports
the balance *now*. These tests pin the conversion between the two.
"""
import datetime
from decimal import Decimal

from click.testing import CliRunner

from aussie_bean_tools import upbank_client
from aussie_bean_tools.upbank_client import start_of_day_balance

DAY = datetime.date(2026, 9, 7)


def _txn(created, value, status="SETTLED", up_id=None):
    return {
        "id": up_id or f"{created}-{value}",
        "attributes": {
            "createdAt": created,
            "status": status,
            "amount": {"value": value},
        },
    }


def test_no_transactions_today_leaves_balance_unchanged():
    pulled = [_txn("2026-09-06T20:00:28+10:00", "-33.15")]
    assert start_of_day_balance(Decimal("105.81"), pulled, DAY) == Decimal("105.81")


def test_todays_transactions_are_backed_out():
    # The 2026-09-07 case: a midday snapshot of 88.82 already had Spotify
    # deducted, and Coles landed later the same day.
    pulled = [
        _txn("2026-09-07T13:35:05+10:00", "-41.90"),
        _txn("2026-09-07T10:02:31+10:00", "-16.99"),
        _txn("2026-09-06T05:30:43+10:00", "33.15"),
    ]
    assert start_of_day_balance(Decimal("46.92"), pulled, DAY) == Decimal("105.81")


def test_held_transactions_are_backed_out_too():
    # Up's balance is the available balance, with holds already deducted.
    pulled = [_txn("2026-09-07T13:35:05+10:00", "-41.90", status="HELD")]
    assert start_of_day_balance(Decimal("63.91"), pulled, DAY) == Decimal("105.81")


def test_credits_today_are_backed_out():
    pulled = [_txn("2026-09-07T20:56:33+10:00", "250.00")]
    assert start_of_day_balance(Decimal("355.81"), pulled, DAY) == Decimal("105.81")


class FakeClient:
    """Stands in for UpbankClient; each call pops the next scripted response."""

    def __init__(self, balances, pulls):
        self.balances = list(balances)
        self.pulls = list(pulls)

    def accounts(self):
        value = self.balances.pop(0)
        return [{"id": "acct-1", "attributes": {"balance": {"value": value}}}]

    def transactions(self, since, account_id=None):
        assert account_id == "acct-1"
        return self.pulls.pop(0)


def _invoke(monkeypatch, fake, command):
    monkeypatch.setattr(upbank_client, "UpbankClient", lambda token: fake)
    return CliRunner().invoke(
        upbank_client.cli, [command, "John"], env={"UPBANK_TOKEN": "t"}
    )


def test_balance_shows_the_live_figure_unadjusted(monkeypatch):
    # For a human: what the Up app shows, today's spending included.
    fake = FakeClient(["46.92"], [])
    result = _invoke(monkeypatch, fake, "balance")
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "John: 46.92 AUD"


def test_assertion_prints_start_of_today_balance(monkeypatch):
    today = datetime.datetime.now(upbank_client.UP_TZ).date()
    pulled = [_txn(f"{today}T13:35:05+10:00", "-41.90")]
    fake = FakeClient(["46.92", "46.92"], [pulled, pulled])
    result = _invoke(monkeypatch, fake, "assertion")
    assert result.exit_code == 0, result.output
    assert result.output.split() == [
        str(today), "balance", "Assets:Bank:John-Upbank", "88.82", "AUD"
    ]


def test_assertion_retries_when_a_transaction_lands_mid_read(monkeypatch):
    today = datetime.datetime.now(upbank_client.UP_TZ).date()
    first = [_txn(f"{today}T10:02:31+10:00", "-16.99")]
    second = first + [_txn(f"{today}T13:35:05+10:00", "-41.90")]
    # The balance read happens between the two pulls, so it may or may not
    # include the transaction that arrived; the pulls disagree, so retry.
    fake = FakeClient(["46.92", "46.92", "46.92"], [first, second, second, second])
    result = _invoke(monkeypatch, fake, "assertion")
    assert result.exit_code == 0, result.output
    assert result.output.split()[3] == "105.81"
