import csv
import decimal
import re

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import beancount
from beancount.core.data import EMPTY_SET, Posting, Transaction, new_metadata, Balance
from beancount.core import flags, amount, number
from beancount.ingest import importer

CURRENCY = "AUD"


@dataclass
class StGeorgeTransaction:
    """Parse a CSV row from StGeorge.

    Presents an object.
    """
    TIME_FORMAT = [
        "Osko Withdrawal",
        "Osko Deposit",
        "Internet Withdrawal",
        "Eftpos Debit",
        "Eftpos Purchase",
        "Eftpos Refund",
        "Atm Withdrawal",
        "Atm Withdrawal -Wbc",
        "Tfr Wdl BPAY Internet",
    ]
    LOCATION_FORMAT = [
        "Visa Purchase",
        "Visa Purchase O/Seas",
        "Visa Cash Advance",
        "Visa Credit",
    ]

    def __init__(self, row: dict):
        self._row = row
        self.date = datetime.strptime(row["Date"], "%d/%m/%Y").date()
        self.raw = row["Description"].strip()
        self.credit = row["Credit"] if len(row["Credit"]) else None
        self.debit = row["Debit"] if len(row["Debit"]) else None
        self.balance = row["Balance"] if len(row["Balance"]) else None
        self.effective_date = None
        self.effective_time = None
        self.location = None
        self.narration = self.raw.strip()
        self.payee = None

        if self.raw[:30].strip() in self.TIME_FORMAT:
            # These descriptions include the time, but not location.
            # eg: "Internet Withdrawal           15Jan05:44 Night Church"
            self.narration = self.raw[:30].strip()
            self.effective_date = self.raw[30:35].strip()
            self.effective_time = self.raw[35:40].strip()
            self.payee = " ".join(self.raw[41:].split())

        elif self.raw[:30].strip() in self.LOCATION_FORMAT:
            # These descriptions include the location, but not the time.
            # eg: "Visa Purchase                 12Jan David Jones Limited  Artarmon"
            self.narration = self.raw[:30].strip()
            self.effective_date = self.raw[30:35].strip()
            self.payee = self.raw[36:56].strip()
            self.location = self.raw[57:].strip() or None

        for txt in [self.effective_date, self.effective_time, self.location]:
            if txt is not None:
                self.narration += " " + txt

    def __str__(self):
        return ",".join(self._row.values())

    @staticmethod
    def csv_reader(file):
        with open(file.name, "r") as fileobj:
            for row in csv.DictReader(fileobj):
                yield StGeorgeTransaction(row)


class StGeorgeImporter(importer.ImporterProtocol):
    """Interface that all source importers need to comply with."""

    # A flag to use on new transaction. Override this flag as you prefer.
    FLAG = flags.FLAG_OKAY

    def __init__(self, account_name, tags=EMPTY_SET):
        """
        Args:
            account_name: beancount account name for the upbank account.
                eg:  "Assets:Bank:StGeorge:Freedom"
        """
        self.account_name = account_name
        self.tags = tags

    def name(self):
        """Return a unique id/name for this importer.

        Returns:
          A string which uniquely identifies this importer.
        """
        return "St George Bank"

    __str__ = name

    def identify(self, file):
        """Return true if this importer matches the given file.

        St George offers a CSV export.

        You have to manually go into the web interface, pick the dates,
        export as, and save to file.

        Args:
          file: A cache.FileMemo instance.
        Returns:
          A boolean, true if this importer can handle this file.
        """
        return re.match("Date,Description,Debit,Credit,Balance", file.head())

    def extract(self, file, existing_entries=None):
        """Extract transactions from a file.

        Args:
          file: A cache.FileMemo instance.
          existing_entries: An optional list of existing directives loaded from
            the ledger which is intended to contain the extracted entries. This
            is only provided if the user provides them via a flag in the
            extractor program.
        Returns:
          A list of new, imported directives (usually mostly Transactions)
          extracted from the file.
        """
        date_of_last = None
        entries = []
        for lineno, row in enumerate(StGeorgeTransaction.csv_reader(file)):
            # TODO: balance is printed as 0.1 AUD, not 0.10 AUD?
            # Declare the balance at the start of a new month.
            if date_of_last and date_of_last.month != row.date.month:
                balance = Balance(
                    new_metadata(file.name, lineno + 2),
                    date(row.date.year, row.date.month, 1),
                    self.account_name,
                    amount.Amount(number.D(row.balance), CURRENCY),
                    None,
                    None,
                )
                entries.append(balance)

            # Post a transaction.
            value = number.D(row.credit if row.credit else row.debit).quantize(
                decimal.Decimal("0.01")
            )
            if row.debit:
                value *= decimal.Decimal(-1)
            posting = Posting(
                self.account_name,
                amount.Amount(value, CURRENCY),
                None,
                None,
                None,
                None,
            )
            txn_args = {
                "meta": new_metadata(file.name, lineno + 2),
                "date": row.date,
                "flag": beancount.core.flags.FLAG_OKAY,
                "tags": self.tags,
                "links": EMPTY_SET,
                "postings": [posting],
                "narration": row.narration,
                "payee": row.payee,
            }
            entries.append(Transaction(**txn_args))

            date_of_last = row.date
        return entries

    def file_account(self, file):
        """Return an account associated with the given file.

        Note: If you don't implement this method you won't be able to move the
        files into its preservation hierarchy; the bean-file command won't
        work.

        Also, normally the returned account is not a function of the input
        file--just of the importer--but it is provided anyhow.

        Args:
          file: A cache.FileMemo instance.
        Returns:
          The name of the account that corresponds to this importer.
        """
        return self.account_name

    def file_name(self, file):
        """A filter that optionally renames a file before filing.

        This is used to make tidy filenames for filed/stored document files. If
        you don't implement this and return None, the same filename is used.
        Note that if you return a filename, a simple, RELATIVE filename must be
        returned, not an absolute filename.

        Args:
          file: A cache.FileMemo instance.
        Returns:
          The tidied up, new filename to store it as.
        """
        # Use the account name.
        account_str = self.account_name.split(":")[-1]
        return f"{account_str}.json"

    def file_date(self, file):
        """Attempt to obtain a date that corresponds to the given file.

        Args:
          file: A cache.FileMemo instance.
        Returns:
          A date object, if successful, or None if a date could not be extracted.
          (If no date is returned, the file creation time is used. This is the
          default.)
        """
        # Date of last transaction in the file.
        return self.extract(file)[-1].date
