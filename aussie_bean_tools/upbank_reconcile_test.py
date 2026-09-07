"""Tests for promoting provisional (HELD) Up entries once they settle.

The behaviour these lock down, in order of how expensive it is to get wrong:

* a promoted entry is edited **in place** -- hand-written annotations survive.
  Deleting and re-importing the settled copy would re-run the fuzzer and lose
  them, and roughly one in seven held-at-import entries carries one.
* a hold that settles at a different amount has its posting corrected, and every
  balance directive snapshotted while it was live moves by the same delta.
* the newest balance directive is never adjusted -- it is the evidence that the
  money really moved, so a wrong conclusion rolls back instead of corrupting the
  ledger.
"""

import datetime
import json

import pytest
from click.testing import CliRunner

from aussie_bean_tools.upbank_reconcile import cli

ACCOUNT = "Assets:Bank:John-Upbank"

LEDGER = """\
2000-01-01 open Assets:Bank:John-Upbank
2000-01-01 open Expenses:Food:Alcohol
2000-01-01 open Equity:Opening

2026-08-01 * "seed"
  Assets:Bank:John-Upbank   1000.00 AUD
  Equity:Opening

2026-09-01 * "4 Pines Brewing Co." "4P - Manly, Brookvale"  ;drinks with Tim
  up_hold: "held-4-pines"
  Assets:Bank:John-Upbank    -41.80 AUD
  Expenses:Food:Alcohol

2026-09-02 balance Assets:Bank:John-Upbank    958.20 AUD

2026-09-06 balance Assets:Bank:John-Upbank    {anchor} AUD
"""


def _pull(status, value, settled="2026-09-03T04:29:10+10:00", up_id="held-4-pines"):
    return [{
        "type": "transactions",
        "id": up_id,
        "attributes": {
            "status": status,
            "rawText": "4P - Manly, Brookvale",
            "description": "4 Pines Brewing Co.",
            "message": None,
            "holdInfo": None,
            "amount": {"currencyCode": "AUD", "value": value},
            "createdAt": "2026-09-01T18:31:26+10:00",
            "settledAt": settled if status == "SETTLED" else None,
        },
        "relationships": {},
        "links": {},
    }]


def _run(tmp_path, ledger_text, pull, *extra):
    ledger = tmp_path / "ledger.beancount"
    ledger.write_text(ledger_text)
    pull_path = tmp_path / "pull.json"
    pull_path.write_text(json.dumps(pull))
    # These fixtures are self-contained, so the file under edit is also its own
    # root. The real ledgers are `include`d by master.beancount and must pass it.
    result = CliRunner().invoke(
        cli,
        [str(ledger), str(pull_path), "--root", str(ledger),
         "--account", ACCOUNT, *extra],
    )
    return result, ledger


def test_drifted_hold_is_promoted_in_place(tmp_path):
    # Settled 67c above the hold. The posting is corrected, the tag removed, and
    # the annotation and narration are untouched.
    result, ledger = _run(
        tmp_path, LEDGER.format(anchor="957.53"), _pull("SETTLED", "-42.47"), "--fix"
    )
    assert result.exit_code == 0, result.output
    text = ledger.read_text()

    assert "-42.47 AUD" in text, "posting corrected to the settled amount"
    assert "up_hold" not in text, "provisional tag removed once settled"
    assert ";drinks with Tim" in text, "hand-written annotation survives"
    assert '"4P - Manly, Brookvale"' in text, "narration survives"
    # The assertion taken while the hold was live moves by the drift; the newest
    # one is the evidence and is left alone.
    assert "957.53 AUD" in text, "anchor assertion untouched"
    assert "958.20 AUD" not in text, "intermediate assertion adjusted"


def test_released_hold_is_commented_out(tmp_path):
    # Absent from a pull whose window covers it: the hold was released. The
    # entry is commented rather than deleted, so the history stays readable.
    result, ledger = _run(
        tmp_path,
        LEDGER.format(anchor="1000.00"),
        _pull("SETTLED", "-9.99", up_id="some-other-transaction"),
        "--fix",
    )
    assert result.exit_code == 0, result.output
    text = ledger.read_text()
    assert ';2026-09-01 * "4 Pines Brewing Co."' in text
    assert "released, never settled" in result.output


def test_wrong_conclusion_rolls_back(tmp_path):
    # The anchor says the money never came back, so treating the hold as
    # released must fail loudly and leave the ledger untouched.
    original = LEDGER.format(anchor="958.20")
    result, ledger = _run(
        tmp_path, original, _pull("SETTLED", "-9.99", up_id="other"), "--fix"
    )
    assert result.exit_code != 0
    assert "Rolled back" in result.output
    assert ledger.read_text() == original, "ledger restored exactly"


def test_still_held_is_reported_and_left_alone(tmp_path):
    result, ledger = _run(
        tmp_path, LEDGER.format(anchor="958.20"), _pull("HELD", "-41.80"), "--fix"
    )
    assert result.exit_code == 0, result.output
    assert "still unsettled" in result.output
    assert "up_hold" in ledger.read_text(), "an unsettled hold keeps its tag"


def test_stale_hold_is_flagged(tmp_path):
    # Holds normally settle within days; this one is old enough to want a look.
    stale = LEDGER.format(anchor="958.20").replace("2026-09-01", "2026-08-01")
    pull = _pull("HELD", "-41.80")
    pull[0]["attributes"]["createdAt"] = "2026-08-01T18:31:26+10:00"
    result, _ = _run(tmp_path, stale, pull, "--fix")
    assert result.exit_code == 0, result.output
    assert "!!" in result.output
    assert "pending for more than 7 days" in result.output


def test_dry_run_changes_nothing(tmp_path):
    original = LEDGER.format(anchor="957.53")
    result, ledger = _run(tmp_path, original, _pull("SETTLED", "-42.47"))
    assert result.exit_code == 0, result.output
    assert "pending; re-run with --fix" in result.output
    assert ledger.read_text() == original


AGED = """\
2000-01-01 open Assets:Bank:John-Upbank
2000-01-01 open Expenses:Food:Alcohol
2000-01-01 open Equity:Opening

2026-08-01 * "seed"
  Assets:Bank:John-Upbank   1000.00 AUD
  Equity:Opening

2026-07-01 * "Ancient Hold" "ANCIENT HOLD PTY LTD   SYDNEY"
  up_hold: "aged-out-of-window"
  Assets:Bank:John-Upbank    -12.00 AUD
  Expenses:Food:Alcohol

2026-09-06 balance Assets:Bank:John-Upbank    {anchor} AUD
"""


def test_released_hold_outside_the_window_is_identified_by_the_gap(tmp_path):
    # A hold that aged out of the pull window cannot be checked against the API:
    # Up keeps no record of a release. But releasing it puts the money back, so
    # Up's balance rises by the held amount while the ledger still spends it.
    # That gap identifies the culprit when nothing else can.
    result, ledger = _run(
        tmp_path,
        AGED.format(anchor="1000.00"),  # the 12.00 came back
        _pull("SETTLED", "-42.47"),
        "--fix",
    )
    assert result.exit_code == 0, result.output
    assert "a gap of 12.00 AUD" in result.output
    assert "released them and put the money back" in result.output
    assert "Ancient Hold" in result.output
    # Identified, not acted on: the API cannot confirm it, so this stays a
    # judgement call for a human.
    assert "up_hold" in ledger.read_text()


def test_gap_that_matches_no_hold_is_not_blamed_on_one(tmp_path):
    result, _ = _run(
        tmp_path, AGED.format(anchor="1007.00"), _pull("SETTLED", "-42.47"), "--fix"
    )
    assert result.exit_code == 0, result.output
    assert "a gap of 19.00 AUD" in result.output
    assert "No combination of pending holds accounts for it" in result.output


def test_no_gap_reports_nothing(tmp_path):
    result, _ = _run(
        tmp_path, AGED.format(anchor="988.00"), _pull("SETTLED", "-42.47"), "--fix"
    )
    assert result.exit_code == 0, result.output
    assert "gap of" not in result.output


def test_still_held_is_never_blamed_for_a_gap(tmp_path):
    # A hold the pull confirms is still HELD is deducted from Up's balance and
    # from the ledger alike, so it cannot be the cause of a gap. Blaming it
    # would advise deleting a live transaction that is going to settle.
    ledger = AGED.format(anchor="1000.00").replace(
        "aged-out-of-window", "still-held"
    ).replace("2026-07-01", "2026-09-01")
    pull = _pull("HELD", "-12.00", up_id="still-held")
    pull[0]["attributes"]["createdAt"] = "2026-09-01T10:00:00+10:00"
    result, _ = _run(tmp_path, ledger, pull, "--fix")
    assert result.exit_code == 0, result.output
    assert "released them and put the money back" not in result.output


def test_broken_intermediate_assertion_rolls_back(tmp_path):
    # When a hold was released *before* an intermediate snapshot, that snapshot
    # already reflects the money back and must not be adjusted again. Verifying
    # only the anchor would miss the break and report success.
    ledger = """\
2000-01-01 open Assets:Bank:John-Upbank
2000-01-01 open Expenses:Food:Alcohol
2000-01-01 open Equity:Opening

2026-08-01 * "seed"
  Assets:Bank:John-Upbank   1000.00 AUD
  Equity:Opening

2026-09-01 * "Gone" "GONE PTY LTD           SYDNEY"
  up_hold: "released"
  Assets:Bank:John-Upbank    -41.80 AUD
  Expenses:Food:Alcohol

2026-09-04 balance Assets:Bank:John-Upbank   1000.00 AUD

2026-09-06 balance Assets:Bank:John-Upbank   1000.00 AUD
"""
    original = ledger
    result, path = _run(tmp_path, ledger, _pull("SETTLED", "-9.99", up_id="other"), "--fix")
    assert result.exit_code != 0, result.output
    assert "Rolled back" in result.output
    assert path.read_text() == original


def test_transfer_leg_is_reported_not_edited(tmp_path):
    # Both legs move together, but only this account's assertions are in scope,
    # so editing would silently shift another account with no rollback signal.
    ledger = """\
2000-01-01 open Assets:Bank:John-Upbank
2000-01-01 open Assets:Bank:Joint-CompleteFreedom
2000-01-01 open Equity:Opening

2026-08-01 * "seed"
  Assets:Bank:John-Upbank   1000.00 AUD
  Equity:Opening

2026-09-01 * "JOHN MEE" "Up John"
  up_hold: "held-4-pines"
  Assets:Bank:John-Upbank    -41.80 AUD
  Assets:Bank:Joint-CompleteFreedom

2026-09-06 balance Assets:Bank:John-Upbank    958.20 AUD
"""
    original = ledger
    result, path = _run(tmp_path, ledger, _pull("SETTLED", "-42.47"), "--fix")
    assert result.exit_code == 0, result.output
    assert "transfer between own accounts" in result.output
    assert path.read_text() == original, "transfer legs are left alone"


def test_settled_without_a_timestamp_is_treated_as_pending(tmp_path):
    pull = _pull("SETTLED", "-42.47")
    pull[0]["attributes"]["settledAt"] = None
    result, path = _run(tmp_path, LEDGER.format(anchor="958.20"), pull, "--fix")
    assert result.exit_code == 0, result.output
    assert "up_hold" in path.read_text(), "undated settlement stays provisional"
