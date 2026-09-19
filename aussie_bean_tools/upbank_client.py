"""Up Bank API.

Use the Up Bank API to retrieve transactions.
"""
import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import click
import json
import pprint
import requests


URL = "https://api.up.com.au/api/v1"

# Maximum number of transactions upbank return per 'page'.
PAGE_SIZE = 100

# Constants
HELD = "HELD"
SETTLED = "SETTLED"

# Up stamps `createdAt` in Sydney time, and the importer dates ledger entries
# from it, so a ledger day is a Sydney day whatever this machine's clock says.
UP_TZ = ZoneInfo("Australia/Sydney")


class UpbankClient:
    def __init__(self, token: str):
        """
        token: str: upbank "personal access token" from https://api.up.com.au/getting_started
        """
        self.token = token

    def get_month(self, year: int, month: int) -> []:
        """Get settled transactions for the given month.

        year: int: year to download eg: 2021
        month: int: month to download eg: 3

        Returns:
              A list of settled transactions as a dict.
        """
        local_tz = datetime.datetime.utcnow().astimezone().tzinfo
        since = datetime.datetime(year=year, month=month, day=1, tzinfo=local_tz)
        if month == 12:
            month = 0
            year += 1
        until = datetime.datetime(year=year, month=month + 1, day=1, tzinfo=local_tz)
        return self.transactions(since, until)

    def get_recent(self, days: int, account_id: str = None) -> []:
        """Get all recent transactions.

        days: int: commencing this many days ago
        account_id: str: only this account's; or None for every account.

        Returns:
              A list of transactions as a dict.
        """
        local_tz = datetime.datetime.utcnow().astimezone().tzinfo
        now = datetime.datetime.utcnow().replace(tzinfo=local_tz)
        since = now - datetime.timedelta(days=days)
        return self.transactions(since, account_id=account_id)

    def transactions(
        self,
        since: datetime.datetime,
        until: datetime.datetime = None,
        status: str = None,
        account_id: str = None,
    ) -> list:
        """Fetch a list of transactions.

        Args:
            since: tzaware datetime to start from
            until: tzaware datetime to stop at; or None for all.
            status: "HELD" or "SETTLED"; or None for both.
            account_id: only this account's transactions; or None for every
                account the token can see.

        Returns:
            list of transactions in dict format.
        """
        params = dict()

        # Upbank only return PAGE_SIZE transactions per request, so we need to
        params.update({"page[size]": PAGE_SIZE})
        params.update({"filter[since]": since})
        if until is not None:
            params.update({"filter[until]": until})
        if status is not None:
            params.update({"filter[status]": status})
        path = "/transactions" if account_id is None else f"/accounts/{account_id}/transactions"
        response = self.get(path, params=params)
        return response

    def get(self, path, params: dict = None) -> list:
        """Send a GET request to Up.

        Args:
            path: includes the preceding slash.
            params: request parameters.

        Returns:
            list of data; probably dicts.
        """
        result = []
        uri = f"{URL}{path}"
        while uri is not None:
            response = requests.get(uri, headers=self._headers(), params=params)
            data = response.json()
            if "data" not in data:
                # Up returns {"errors": [...]} on failure (e.g. 401 for an
                # invalid/revoked token). Surface a clear message instead of
                # crashing with KeyError: 'data'.
                errors = data.get("errors") or [{}]
                detail = "; ".join(
                    " ".join(
                        part for part in (
                            e.get("status"), e.get("title"), e.get("detail")
                        ) if part
                    )
                    for e in errors
                )
                raise click.ClickException(
                    f"Up API request to {path} failed "
                    f"(HTTP {response.status_code}): {detail or response.text}"
                )
            result.extend(data["data"])
            try:
                uri = data["links"]["next"]
            except KeyError:
                break
        return result

    def ping(self):
        """Verify the access token is working.

        Returns:
            requests.Response
        """
        return requests.get(f"{URL}/util/ping", headers=self._headers())

    def accounts(self):
        """Fetch a list of accounts."""
        return self.get("/accounts")

    def categories(self):
        """Fetch a list of categories."""
        return self.get("/categories")

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}"}


def start_of_day_balance(balance: Decimal, transactions: list, day: datetime.date) -> Decimal:
    """Back `day`'s transactions out of a balance read during `day`.

    Beancount checks a `balance` directive at the *start* of its date, but Up
    reports the balance *now*, which already includes everything created
    earlier today. HELD transactions count as well as SETTLED ones, because
    Up's balance is the available balance with holds already deducted.

    A transaction's day is its `createdAt` date, the same date the importer
    gives it in the ledger.
    """
    moved = sum(
        (
            Decimal(t["attributes"]["amount"]["value"])
            for t in transactions
            if t["attributes"]["createdAt"][:10] == day.isoformat()
        ),
        Decimal(0),
    )
    return balance - moved


def _live_balance(client) -> tuple:
    """The account's id and its balance right now, as the Up app shows it."""
    acct = client.accounts()[0]
    return acct["id"], Decimal(acct["attributes"]["balance"]["value"])


def _fingerprint(transactions: list) -> set:
    return {(t["id"], t["attributes"]["amount"]["value"]) for t in transactions}


# Global Upbank client
client = None


@click.group()
@click.option(
    "--token",
    envvar="UPBANK_TOKEN",
    help="Upbank personal access token. Prefer the UPBANK_TOKEN environment "
         "variable so the secret never appears on the command line or in logs.",
)
def cli(token):
    global client
    if not token:
        raise click.UsageError(
            "No Upbank token supplied. Set the UPBANK_TOKEN environment variable "
            "(preferred, keeps the secret off the command line) or pass --token."
        )
    client = UpbankClient(token)


@cli.command()
def ping():
    """Send a ping to Upbank, to verify your token and their API status."""
    global client
    response = client.ping()
    click.echo("Ping!")
    click.echo(response.text)


@cli.command()
def categories():
    """Get a list of transaction categories."""
    global client
    response = client.categories()
    click.echo(pprint.pformat(response))


@cli.command()
@click.argument("account", type=click.types.STRING)
def balance(account):
    """Show the account's balance right now, as the Up app does."""
    global client
    _, current = _live_balance(client)
    click.echo(f"{account}: {current} AUD")


@cli.command()
@click.argument("account", type=click.types.STRING)
def assertion(account):
    """Print a ledger balance assertion for the start of today.

    Beancount checks a `balance` directive at the start of its date, while
    Up's balance runs through the day. Stamping Up's current balance with
    today's date fails whenever something was spent earlier today; stamping
    it with tomorrow's fails when something is spent later today. So today's
    transactions are backed out instead, giving the balance the ledger must
    show at midnight.
    """
    global client
    today = datetime.datetime.now(UP_TZ).date()
    since = datetime.datetime.combine(today, datetime.time(), tzinfo=UP_TZ)
    # The balance and the transactions are separate requests. Pulling the
    # transactions on both sides of the balance read, and retrying until the
    # two pulls agree, ensures nothing landed in between that the balance
    # includes but the subtraction misses (or vice versa).
    account_id, _ = _live_balance(client)
    for _ in range(3):
        pulled = client.transactions(since, account_id=account_id)
        _, current = _live_balance(client)
        if _fingerprint(client.transactions(since, account_id=account_id)) == _fingerprint(pulled):
            break
    else:
        raise click.ClickException(
            "Up transactions kept changing while the balance was read; try again."
        )
    opening = start_of_day_balance(current, pulled, today)
    click.echo(f"{today} balance Assets:Bank:{account}-Upbank \t\t {opening} AUD\n")


@cli.command()
@click.argument("year", type=click.types.INT)
@click.argument("month", type=click.types.INT)
def month(year, month):
    """Download a sequence of transactions.
    """
    global client
    transactions = client.get_month(year, month)
    click.echo(json.dumps(transactions, indent=3))


@cli.command()
@click.argument("days", type=click.types.INT, default=60)
def recent(days):
    """Download a sequence of transactions.

    Only the account whose balance `balance` and `assertion` report, so a saver
    added later cannot leak into that account's ledger.
    """
    global client
    account_id, _ = _live_balance(client)
    transactions = client.get_recent(days, account_id=account_id)
    click.echo(json.dumps(transactions, indent=3))


@cli.command()
@click.argument("days", type=click.types.INT, default=60)
def held(days):
    """Download held transactions.
    """
    global client
    local_tz = datetime.datetime.utcnow().astimezone().tzinfo
    now = datetime.datetime.utcnow().replace(tzinfo=local_tz)
    since = now - datetime.timedelta(days=days)
    transactions = client.transactions(since, status=HELD)
    click.echo(json.dumps(transactions, indent=3))


if __name__ == "__main__":
    cli()
