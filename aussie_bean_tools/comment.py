import re
import sys

import click


def comment_transactions(accounts, text):
    """Return text with any transaction posting to one of accounts commented out."""
    blocks = re.split(r'\n\n', text)
    result = []
    for block in blocks:
        if block.strip() and any(account in block for account in accounts):
            block = '\n'.join(
                (';' + line) if line.strip() else line
                for line in block.split('\n')
            )
        result.append(block)
    return '\n\n'.join(result)


@click.command
@click.argument('accounts', nargs=-1, required=True)
def cli(accounts):
    """Read beancount from stdin; comment out transactions posting to ACCOUNTS.

    Any transaction that contains a posting to one of the given ACCOUNTS has
    every line prefixed with ';', turning it into a beancount comment block.
    All other transactions pass through unchanged.

    Typical use: pipe fuzzer output through bean-comment before appending to
    your ledger, to silence transfers that are already recorded in another
    account's file.

    \b
    Example:
        fuzzer /tmp/joint.beancount \\
            | bean-comment Assets:Bank:Simon-Upbank Assets:Bank:Sheryl-Upbank \\
            >> joint-freedom-2026.beancount
    """
    print(comment_transactions(accounts, sys.stdin.read()), end='')
