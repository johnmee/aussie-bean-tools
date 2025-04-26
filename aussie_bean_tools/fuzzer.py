import click

from more_itertools import last

from beancount.core import data
from beancount import loader
from beancount.parser import printer
from beancount.parser import parser

from fuzzywuzzy import process


def build_key(trans: data.Transaction) -> str:
    """Return a string for comparing the given transaction against others.
    """
    components = [trans.payee, trans.narration, str(trans.postings[0].units)]
    return " ".join([c for c in components if c is not None])


def mimic(entry, trans):
    """Complete the entry with postings copied from the transaction.
    """
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

    # Copy the tags, but remove& old #john and #fiona tags from individual entries
    tags = entry.tags.union(trans.tags) - frozenset(["john", "fiona"])
    new_entry = entry._replace(tags=tags)
    return new_entry


def fuzzer(threshold: int, training: str, infile: str) -> str:
    """Autocomplete postings of transactions.

    Build a dictionary of past transactions and a summary key/description.
    For each transaction fuzzymatch it against the keys in the dictionary
    and copy the postings and tags of the matched transaction from history

    Args:
        threshold: only use fuzz scores better than this
        training: name of beancount file to use for training
        infile: name of partial beancount file to complete

    Returns:
        sends string output to stdout
    """
    existing, _, _ = loader.load_file(training)
    importing, errors, _ = parser.parse_file(infile)
    if not len(importing):
        print("Nothing to import.")
        exit()

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
def cli(threshold, training, infile):
    fuzzer(threshold, training, infile)


if __name__ == "__main__":
    cli()
