import click

from more_itertools import last

from beancount.core import data
from beancount import loader
from beancount.parser import printer
from beancount.parser import parser

from fuzzywuzzy import process


def build_key(trans: data.Transaction) -> str:
    """Return a string for comparing this trans against others."""
    components = [trans.payee, trans.narration, str(trans.postings[0].units)]
    return " ".join([c for c in components if c is not None])


def mimic(entry, trans):
    """Fill out the entry with parts copied from trans."""

    # Copy postings to accounts not already there.
    entry_accounts = [p.account for p in entry.postings]
    added_postings = list()
    for posting in trans.postings:
        if posting.account not in entry_accounts:
            added_postings.append(posting)

    # Drop the value of one added posting so the known value applies to both
    # accounts.
    if len(added_postings) == 1:
        added_postings = [added_postings[0]._replace(units=None)]
    entry.postings.extend(added_postings)

    # Copy the tags.
    new_entry = entry._replace(tags=(entry.tags | trans.tags))
    return new_entry


@click.command
@click.option(
    "--threshold",
    default=86,
    show_default=True,
    type=int,
    help="Only use fuzz scores better than this.",
)
@click.option(
    "--training",
    show_default=True,
    type=click.Path(exists=True),
    default="master.beancount",
    help="Beancount file to use as a template for predictions."
)
@click.argument("infile", type=click.Path(exists=True))
def fuzzer(threshold, training, infile):
    """Autocomplete postings of transactions.

    * Build a dictionary of past transactions and a summary key/description.
    * For each transaction fuzzymatch it against the keys in the dictionary
    * and copy the postings and tags of the matched transaction from history
    """
    existing, _, _ = loader.load_file(training)
    importing, errors, _ = parser.parse_file(infile)
    if not len(importing):
        print("Nothing to import.")
        return

    # Assume the target account is the first posting found in the import file.
    # This means the training ignores postings targeted to other accounts.
    for directive in importing:
        if isinstance(directive, data.Transaction):
            target_account = directive.postings[0].account
            break

    # Build a dictionary of historical entries.
    transactions = {}
    for directive in existing:
        if isinstance(directive, data.Transaction):

            # Only consider transactions which post to the target account.
            accounts = [p.account for p in directive.postings]
            if target_account not in accounts or len(accounts) == 1:
                continue

            # Key the transaction for matching.
            key = build_key(directive)
            if key not in transactions:
                transactions[key] = [directive]
            else:
                transactions[key].append(directive)

    # Present completion options for each new transaction.
    for entry in importing:
        if not isinstance(entry, data.Transaction):
            printer.print_entry(entry)
            continue
        match_key, score = process.extractOne(build_key(entry), transactions.keys())
        if score <= threshold:
            printer.print_entry(entry)
        else:
            proposal = mimic(entry, last(transactions[match_key]))
            printer.print_entry(proposal)


if __name__ == "__main__":
    fuzzer()
