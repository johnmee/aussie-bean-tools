import json

from datetime import date

import beancount
from beancount.core import data
from beancount.core import flags
from beancount.core import (account, amount, number)
from beancount.ingest import importer

# Upbank (up.com.au–Bendigo Bank) only operates in AUD, afaik.
CURRENCY = "AUD"


class UpbankImporter(importer.ImporterProtocol):
    """Interface that all source importers need to comply with.
    """

    # A flag to use on new transaction. Override this flag as you prefer.
    FLAG = beancount.core.flags.FLAG_OKAY

    def __init__(self, account_name="Assets:Bank:Upbank", tags=data.EMPTY_SET):
        """
        Args:
            account_name: beancount account name for the upbank account.
            tags: set of tags to apply to every transaction.
        """
        self.account_name = account_name
        self.tags = tags

    def name(self):
        """
        Returns:
          A string which uniquely identifies this importer.
        """
        return "Upbank"

    __str__ = name

    def identify(self, file):
        """Return true if this importer matches the given file.

        Args:
          file: A cache.FileMemo instance.
        Returns:
          A boolean, true if this importer can handle this file.
        """
        try:
            # Is a json file with specific structure and attributes.
            transactions = json.loads(file.contents())
            assert isinstance(transactions, list), "JSON file is not a list of transactions."
            assert len(transactions) > 0, "JSON list of transactions is empty"
            for trans in transactions:
                assert isinstance(trans, dict), "JSON list contains a non-dictionary item."
                assert "type" in trans
                assert "id" in trans
                assert "attributes" in trans
                assert "relationships" in trans
                assert "links" in trans
            return True
        except json.JSONDecodeError:
            pass
        except AssertionError:
            pass
        return False

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
        # Open the file as json
        transactions = json.loads(file.contents())
        entries = []

        for trans in reversed(transactions):
            trans_id = trans['id']   # Could be used to flag "__duplicate__"s.
            date_ = date.fromisoformat(trans['attributes']['createdAt'][:10])
            raw_text = trans['attributes']['rawText']
            description = trans['attributes']['description']
            message = trans['attributes']['message']
            if message is not None and len(message):
                if raw_text is None or raw_text == description:
                    raw_text = message
                else:
                    raw_text += " " + message
            value = amount.Amount(
                beancount.core.number.D(trans['attributes']['amount']['value']),
                CURRENCY
            )
            posting = data.Posting(self.account_name, value, None, None, None, None)
            txn = data.Transaction(
                meta=data.new_metadata(file.name, trans_id),
                date=date_,
                flag=beancount.core.flags.FLAG_OKAY,
                payee=description,
                tags=self.tags,
                links=data.EMPTY_SET,
                narration=raw_text,
                postings=[posting],
            )
            entries.append(txn)

        # I'd like to insert a balance line somehow but 'balance' is a vague concept
        # to upbank... does it include settled, pending, and cleared amounts?
        # The api-fetch can only snapshot a 'balance' at the moment of asking.

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
