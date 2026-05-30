from .comment import comment_transactions

UPBANK_ACCOUNTS = ["Assets:Bank:Simon-Upbank", "Assets:Bank:Sheryl-Upbank"]

TRANSFER_JOHN = """\
2026-05-27 * "Up Simon" "Internet Withdrawal"
  Assets:Bank:Joint-CompleteFreedom  -350.00 AUD
  Assets:Bank:Simon-Upbank"""

TRANSFER_FIONA = """\
2026-05-27 * "Up Sheryl" "Internet Withdrawal"
  Assets:Bank:Joint-CompleteFreedom  -350.00 AUD
  Assets:Bank:Sheryl-Upbank"""

UNRELATED = """\
2026-05-28 * "Netflix.Com" "Visa Purchase"
  Assets:Bank:Joint-CompleteFreedom  -20.99 AUD
  Expenses:John:Technology"""


def test_comments_simon_upbank_transfer():
    result = comment_transactions(UPBANK_ACCOUNTS, TRANSFER_JOHN)
    assert result == """\
;2026-05-27 * "Up Simon" "Internet Withdrawal"
;  Assets:Bank:Joint-CompleteFreedom  -350.00 AUD
;  Assets:Bank:Simon-Upbank"""


def test_comments_sheryl_upbank_transfer():
    result = comment_transactions(UPBANK_ACCOUNTS, TRANSFER_FIONA)
    assert result == """\
;2026-05-27 * "Up Sheryl" "Internet Withdrawal"
;  Assets:Bank:Joint-CompleteFreedom  -350.00 AUD
;  Assets:Bank:Sheryl-Upbank"""


def test_leaves_unrelated_transaction_unchanged():
    result = comment_transactions(UPBANK_ACCOUNTS, UNRELATED)
    assert result == UNRELATED


def test_comments_only_matching_transactions_in_mixed_input():
    text = f"{TRANSFER_JOHN}\n\n{UNRELATED}\n\n{TRANSFER_FIONA}"
    result = comment_transactions(UPBANK_ACCOUNTS, text)
    assert UNRELATED in result
    for line in TRANSFER_JOHN.splitlines():
        assert f";{line}" in result
    for line in TRANSFER_FIONA.splitlines():
        assert f";{line}" in result


def test_no_accounts_matches_nothing():
    text = f"{TRANSFER_JOHN}\n\n{UNRELATED}"
    result = comment_transactions([], text)
    assert result == text
