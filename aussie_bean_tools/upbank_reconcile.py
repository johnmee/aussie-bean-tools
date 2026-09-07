"""Reconcile provisional (HELD) Up entries against a fresh pull.

An entry written with an ``up_hold`` tag was still HELD when it was imported, so
it is provisional. Up may settle it at a different amount -- a restaurant tip, a
foreign conversion -- or release it entirely, in which case it simply vanishes
from the API. ``TransactionStatusEnum`` is ``HELD|SETTLED`` only: there is no
terminal "released" state a poller can observe, and no tombstone. The importer
only ever appends, so neither outcome can be seen from the import side.

Each provisional entry resolves one of five ways::

    settled, same amount   strip the tag
    settled, drifted       correct the amount, strip the tag
    released               comment the entry out
    still held             leave alone, report (loudly, once it is stale)
    out of window          leave alone, report -- cannot be checked

Entries are promoted **in place**: the amount is corrected and the tag removed,
but the entry keeps its position, its narration and any hand-written annotation.
Deleting the provisional entry and letting the settled copy re-import would
re-run the fuzzer from scratch and discard those edits -- roughly one in seven
held-at-import entries in this ledger carries one.

Correcting an entry also shifts every ``balance`` directive that was snapshotted
while the hold was live, because Up's ``AccountResource.balance`` is *available*
balance and already had the hold deducted from it.

Edits are surgical, anchored on line numbers. Do NOT be tempted to parse the
ledger and reprint it: that would discard the hand-written ``;`` annotations, the
tab alignment and the pushtag/poptag structure the ledger is full of.

USAGE
-----

::

    upbank-reconcile LEDGER PULL --root ROOT --account ACCOUNT [--fix]

``LEDGER``
    The file to edit -- the one the importer appended to, e.g.
    ``john-upbank-2026.beancount``. Only this file is modified.
``PULL``
    The Up JSON this run downloaded, e.g. ``/tmp/john_upbank.json``. Reuse the
    same file the import used; a second ``upbank recent`` would race settlement.
``--root``
    The top-level ledger, normally ``master.beancount``. Required, and it is
    *not* the same as ``LEDGER``: the per-account files are ``include``d and
    carry no opening balance, so loading one standalone makes every assertion in
    it look short by the prior year's carry-over. Balances are computed over the
    root; edits stay confined to ``LEDGER``.
``--account``
    The beancount account the Up transactions post to, e.g.
    ``Assets:Bank:John-Upbank``.
``--fix``
    Apply the edits. The default (``--dry-run``) only reports them.

Run it **last**, after ``upbank balance`` has appended this run's assertion::

    upbank recent 30 > /tmp/john_upbank.json
    python bean.config extract -e master.beancount /tmp/john_upbank.json \\
        | fuzzer >> john-upbank-2026.beancount
    upbank balance John >> john-upbank-2026.beancount
    upbank-reconcile john-upbank-2026.beancount /tmp/john_upbank.json \\
        --root master.beancount --account Assets:Bank:John-Upbank --fix

The ordering is not cosmetic. That freshly-written assertion is the only one
known to postdate a release, so it is the evidence the run verifies against;
earlier assertions were snapshotted while the hold was live and get adjusted.

A ``--fix`` run writes ``LEDGER.bak`` first. If any assertion dated after the
earliest entry it touched fails afterwards, it restores that backup and exits
non-zero rather than leaving a half-corrected ledger.

Sample output::

    2026-09-01  4 Pines Brewing Co.   -41.80 -> -42.47 AUD   settled 2026-09-03

    1 still unsettled:
    !! 2026-07-01  Ancient Hold       -12.00 AUD  66d  -- older than the pull
                                                          window, cannot be checked

      balance directive line 325 -> 181.76 AUD (that snapshot included the hold)

    Applied. Verified against the untouched 2026-09-06 assertion (138.96 AUD).

Two cases are reported but never edited, because neither can be settled safely
from this account alone: a hold that is a leg of a transfer between two of your
own accounts (the other leg would move with it, and its assertions live in a
file this run does not hold), and one that has aged out of the pull window (its
absence proves nothing, since it was never fetched). For the latter the run
still checks whether the gap against Up's balance matches it exactly, which is
the only evidence available once the API has forgotten the hold.
"""

import datetime
import itertools
import json
import os
import re
import shutil

import click
from beancount import loader
from beancount.core import data

# Up's TransactionStatusEnum.
HELD = "HELD"

# A hold this old is worth looking at: in practice Up settles within a few days,
# so anything lingering past a week is anomalous rather than merely pending.
STALE_DAYS = 7

SETTLED_SAME = "settled"
DRIFTED = "drifted"
RELEASED = "released"
OUTSTANDING = "outstanding"
UNVERIFIABLE = "unverifiable"


class Finding:
    """One provisional ledger entry and what the pull says became of it."""

    def __init__(self, kind, entry, posting, was, now=None, settled_on=None,
                 transfer=False):
        self.kind = kind
        self.entry = entry
        self.posting = posting
        self.was = was
        self.now = now
        self.settled_on = settled_on
        # A leg of a transfer between two of our own accounts. Editing this side
        # silently moves the other one, whose balance directives live in another
        # file we are not editing, so these are reported rather than fixed.
        self.transfer = transfer

    def age(self, today):
        return (today - self.entry.date).days

    @property
    def editable(self):
        return self.kind in (SETTLED_SAME, DRIFTED, RELEASED) and not self.transfer

    @property
    def delta(self):
        if self.kind == DRIFTED:
            return self.now - self.was
        if self.kind == RELEASED:
            return -self.was
        return 0


def _is_transfer(entry, account):
    """True if the entry also posts to another asset or liability account."""
    return any(
        posting.account != account
        and posting.account.split(":")[0] in ("Assets", "Liabilities")
        for posting in entry.postings
    )


def resolve(entries, pull, account, filename=None):
    """Classify every ``up_hold`` entry in the ledger against the pull.

    ``filter[since]``/``filter[until]`` select on ``createdAt``, which never
    changes, so an entry whose date falls inside the pull's range was certainly
    fetched and its absence is real. Outside that range absence means "not
    fetched" and nothing can be concluded.

    ``entries`` comes from loading the *root* ledger so that balances mean what
    beancount says they mean; ``filename`` restricts the findings to the one
    file this run may edit.
    """
    live = {t["id"]: t for t in pull}
    dates = sorted(
        datetime.date.fromisoformat(t["attributes"]["createdAt"][:10])
        for t in pull
    )
    window = (dates[0], dates[-1]) if dates else None

    findings = []
    for entry in entries:
        if not isinstance(entry, data.Transaction):
            continue
        up_id = entry.meta.get("up_hold")
        if up_id is None:
            continue
        if filename is not None and entry.meta.get("filename") != filename:
            continue

        posting = next(
            (p for p in entry.postings if p.account == account), None
        )
        if posting is None or posting.units is None:
            continue
        was = posting.units.number
        transfer = _is_transfer(entry, account)

        if window is None or not (window[0] <= entry.date <= window[1]):
            findings.append(
                Finding(UNVERIFIABLE, entry, posting, was, transfer=transfer)
            )
            continue

        trans = live.get(up_id)
        if trans is None:
            findings.append(
                Finding(RELEASED, entry, posting, was, transfer=transfer)
            )
            continue

        attributes = trans["attributes"]
        settled_at = attributes.get("settledAt")
        if attributes["status"] == HELD or settled_at is None:
            # A SETTLED status with no settledAt is a skew we cannot date, so
            # treat it as still pending rather than guessing.
            findings.append(
                Finding(OUTSTANDING, entry, posting, was, transfer=transfer)
            )
            continue

        now = data.D(attributes["amount"]["value"])
        settled_on = datetime.date.fromisoformat(settled_at[:10])
        kind = SETTLED_SAME if now == was else DRIFTED
        findings.append(
            Finding(kind, entry, posting, was, now, settled_on, transfer)
        )

    return findings


def newest_assertion(entries, account):
    """The most recent balance directive for the account.

    Written by the current run, so it postdates anything the current pull shows
    as gone. It is never adjusted: leaving it untouched is what makes it an
    independent check rather than a restatement of our own guess.
    """
    assertions = [
        e for e in entries
        if isinstance(e, data.Balance) and e.account == account
    ]
    if not assertions:
        return None
    # `upbank balance` dates its directive today, so running the target twice in
    # one day leaves two on the same date. The later one in the file is the
    # newer snapshot; tie-break on position so the other is treated as an
    # ordinary intermediate assertion.
    return max(assertions, key=lambda e: (e.date, e.meta.get("lineno", 0)))


def plan(entries, findings, lines, account, anchor, filename):
    """Return ``({lineno: (op, value)}, {lineno: new_balance}, [unreachable])``.

    beancount records a line number per directive and per posting but not per
    metadata key, so the ``up_hold:`` line is found by scanning the entry's span.

    Only directives in ``filename`` can be edited -- every line number here
    indexes into that one file's ``lines``. Assertions that need adjusting but
    live elsewhere are returned so the caller can say so rather than silently
    skipping them.
    """
    edits, balances, unreachable = {}, {}, []

    for finding in findings:
        if not finding.editable:
            continue

        entry = finding.entry
        span = range(
            entry.meta["lineno"],
            max(p.meta["lineno"] for p in entry.postings) + 1,
        )

        if finding.kind == RELEASED:
            for lineno in span:
                edits[lineno] = ("comment", None)
            # The release time is unknowable -- Up keeps no record of it -- so
            # every assertion between the entry and the anchor is assumed to
            # have been taken while the hold was still live.
            until = anchor.date if anchor else datetime.date.max
        else:
            tag = next(
                (ln for ln in span if "up_hold:" in lines[ln - 1]), None
            )
            if tag is None:
                raise click.ClickException(
                    f"{entry.meta['filename']}:{entry.meta['lineno']}: "
                    f"cannot locate the up_hold line to remove"
                )
            edits[tag] = ("delete", None)
            if finding.kind == DRIFTED:
                edits[finding.posting.meta["lineno"]] = ("amount", finding.now)
            until = finding.settled_on

        if finding.delta:
            for other in entries:
                if not (
                    isinstance(other, data.Balance)
                    and other.account == account
                    and other is not anchor
                    and entry.date < other.date <= until
                ):
                    continue
                if other.meta.get("filename") != filename:
                    unreachable.append(other)
                    continue
                lineno = other.meta["lineno"]
                current = balances.get(lineno, other.amount.number)
                balances[lineno] = current + finding.delta

    return edits, balances, unreachable


def shortfall_at(entries, account, assertion):
    """How much the assertion expects beyond what the ledger actually accumulates.

    Positive means Up holds more money than the ledger accounts for -- which is
    exactly what a released hold looks like, since Up added the money back and
    the ledger still has the entry spending it.
    """
    accumulated = data.D("0")
    for entry in entries:
        # Balance directives assert as at the *start* of their date.
        if isinstance(entry, data.Transaction) and entry.date < assertion.date:
            for posting in entry.postings:
                if posting.account == account and posting.units is not None:
                    accumulated += posting.units.number
    return assertion.amount.number - accumulated


def explain(shortfall, pending):
    """Which pending holds, if released, would account for the shortfall.

    A hold that aged out of the pull window cannot be checked against the API --
    Up keeps no record of a release. But the money coming back is visible in the
    balance, so an exact match against one or more pending holds identifies the
    culprit when the API no longer can.
    """
    if not shortfall or not pending:
        return None
    # In practice there are only ever a couple of these; the cap keeps a
    # pathological ledger from turning this into a subset-sum blow-up.
    for size in range(1, min(len(pending), 6) + 1):
        for combo in itertools.combinations(pending, size):
            if sum((f.was for f in combo), data.D("0")) == -shortfall:
                return combo
    return None


def _rewrite_number(line, after, new_number):
    """Replace the first number following ``after``, preserving column width."""
    head, marker, tail = line.partition(after)
    if not marker:
        raise ValueError(f"{after!r} not found in {line!r}")
    match = re.search(r"-?[\d,]+(?:\.\d+)?", tail)
    if match is None:
        raise ValueError(f"no number after {after!r} in {line!r}")
    old = match.group(0)
    new = str(new_number)
    # Absorb the width change into the whitespace in front of the number so the
    # ledger's alignment survives.
    pad = len(old) - len(new)
    prefix = tail[: match.start()]
    if pad > 0:
        prefix += " " * pad
    elif pad < 0:
        prefix = prefix[:pad] if len(prefix) + pad >= 1 else prefix
    return head + marker + prefix + new + tail[match.end():]


def apply_edits(path, lines, edits, balances, account):
    """Write the planned edits, keeping a ``.bak`` alongside."""
    shutil.copy(path, path + ".bak")
    out = list(lines)
    for lineno, (op, value) in edits.items():
        i = lineno - 1
        if op == "comment":
            out[i] = ";" + out[i]
        elif op == "delete":
            out[i] = None
        elif op == "amount":
            out[i] = _rewrite_number(out[i], account, value)
    for lineno, number in balances.items():
        i = lineno - 1
        out[i] = _rewrite_number(out[i], account, number)
    with open(path, "w") as handle:
        handle.writelines(line for line in out if line is not None)


def failing_assertions(root, account, since):
    """Balance assertions for the account, dated after ``since``, that fail.

    Absence from a pull is a *hypothesis* that a hold was released; the ledger
    reconciling afterwards is the proof. Every assertion in range must hold, not
    just the anchor -- that is what catches a wrongly-adjusted intermediate
    snapshot, one taken after the hold was already released and which therefore
    must not move.

    Assertions dated on or before the earliest entry we touched cannot be
    affected by these edits (a balance asserts as at the *start* of its date),
    so a pre-existing failure further back does not block the run.
    """
    _, errors, _ = loader.load_file(root)
    return [
        error for error in errors
        if isinstance(getattr(error, "entry", None), data.Balance)
        and error.entry.account == account
        and error.entry.date > since
    ]


def report(findings, today):
    """Print what became of every provisional entry, loudest last."""
    transfers = [f for f in findings if f.transfer and f.kind != OUTSTANDING]
    for finding in transfers:
        click.echo(
            f"!! {finding.entry.date}  "
            f"{(finding.entry.payee or '')[:34]:34} {finding.was} AUD  "
            f"transfer between own accounts -- not touched, fix by hand\n"
            f"   {finding.entry.meta['filename']}:{finding.entry.meta['lineno']}"
        )
    resolved = [f for f in findings if f.editable]
    for finding in resolved:
        entry = finding.entry
        label = f"  {entry.date}  {(entry.payee or '')[:34]:34}"
        if finding.kind == DRIFTED:
            click.echo(
                f"{label} {finding.was} -> {finding.now} AUD"
                f"   settled {finding.settled_on}"
            )
        elif finding.kind == SETTLED_SAME:
            click.echo(f"{label} {finding.was} AUD   settled as held")
        else:
            click.echo(f"{label} {finding.was} AUD   released, never settled")

    pending = [f for f in findings if f.kind in (OUTSTANDING, UNVERIFIABLE)]
    if not pending:
        if resolved:
            click.echo("\nNothing left unsettled.")
        return pending

    click.echo(f"\n{len(pending)} still unsettled:")
    for finding in sorted(pending, key=lambda f: f.entry.date):
        entry = finding.entry
        age = finding.age(today)
        mark = "  " if age <= STALE_DAYS and finding.kind == OUTSTANDING else "!!"
        note = ""
        if finding.kind == UNVERIFIABLE:
            note = "  -- older than the pull window, cannot be checked"
        elif age > STALE_DAYS:
            note = "  -- unusually old, Up may have dropped it"
        click.echo(
            f"{mark} {entry.date}  {(entry.payee or '')[:34]:34} "
            f"{finding.was} AUD  {age}d{note}"
        )

    stale = [
        f for f in pending
        if f.kind == UNVERIFIABLE or f.age(today) > STALE_DAYS
    ]
    if stale:
        click.echo(
            f"\n!! {len(stale)} hold(s) marked !! above have been pending for "
            f"more than {STALE_DAYS} days.\n"
            f"   Holds normally settle within a few days."
        )
    return pending


def report_shortfall(entries, account, anchor, pending):
    """Explain any gap between Up's reported balance and the ledger's.

    When Up releases a hold it puts the money back, so the account balance it
    reports rises by the held amount while the ledger still has the entry
    spending it. For a hold inside the pull window that release is visible
    directly, as the transaction's absence. For one that has aged out, this
    arithmetic is the only evidence left that it was released.
    """
    if anchor is None:
        return
    gap = shortfall_at(entries, account, anchor)
    if not gap:
        return

    # Only holds the pull could not see are candidates. One the pull confirmed
    # is still HELD is deducted from Up's balance and from the ledger alike, so
    # it contributes nothing to the gap -- blaming it would tell the user to
    # delete a live transaction that is going to settle.
    pending = [f for f in pending if f.kind == UNVERIFIABLE]

    click.echo(
        f"\nUp reports {anchor.amount.number} AUD at {anchor.date}, "
        f"but the ledger accumulates {anchor.amount.number - gap} AUD "
        f"-- a gap of {gap} AUD."
    )
    culprits = explain(gap, pending)
    if culprits:
        click.echo(
            "   That is exactly the amount of the pending hold(s) below, so Up "
            "has\n   released them and put the money back:"
        )
        for finding in culprits:
            click.echo(
                f"     {finding.entry.date}  "
                f"{(finding.entry.payee or '')[:34]:34} {finding.was} AUD  "
                f"{finding.entry.meta['filename']}:{finding.entry.meta['lineno']}"
            )
        click.echo(
            "   Comment the entr(ies) out and add the same amount to every "
            "balance\n   directive between them and this one."
        )
    else:
        click.echo(
            "   No combination of pending holds accounts for it, so this gap is "
            "something else."
        )


@click.command()
@click.argument("ledger", type=click.Path(exists=True, dir_okay=False))
@click.argument("pull", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--account",
    required=True,
    help="Beancount account the Up transactions post to.",
)
@click.option(
    "--root",
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Top-level ledger to load for balance semantics -- usually "
         "master.beancount. LEDGER is normally included by it, and a sub-ledger "
         "loaded on its own has no opening balance, so every assertion in it "
         "would appear to fail.",
)
@click.option(
    "--fix/--dry-run",
    default=False,
    help="Apply the edits. The default only reports them.",
)
def cli(ledger, pull, account, root, fix):
    """Promote settled holds in LEDGER using a fresh Up PULL (json)."""
    transactions = json.load(open(pull))
    entries, _, _ = loader.load_file(root)
    # Balances are computed over the whole ledger; edits are confined to the one
    # file whose lines we hold.
    target = os.path.abspath(ledger)
    findings = resolve(entries, transactions, account, target)

    if not findings:
        click.echo("No provisional (up_hold) entries in the ledger.")
        return

    today = datetime.date.today()
    pending = report(findings, today)

    with open(ledger) as handle:
        lines = handle.readlines()
    anchor = newest_assertion(entries, account)
    edits, balances, unreachable = plan(
        entries, findings, lines, account, anchor, target
    )

    for other in unreachable:
        click.echo(
            f"\n!! {other.meta['filename']}:{other.meta['lineno']}: this "
            f"assertion needs adjusting too but is outside {ledger}; "
            f"fix it by hand."
        )

    if not edits:
        # Nothing to promote, but a gap against Up's balance still needs
        # explaining -- a hold released after ageing out of the pull window
        # leaves no other trace.
        report_shortfall(entries, account, anchor, pending)
        return

    for lineno, number in sorted(balances.items()):
        click.echo(
            f"\n  balance directive line {lineno} -> {number} AUD "
            f"(that snapshot included the hold)"
        )

    if not fix:
        click.echo(f"\n{len(edits)} line edit(s) pending; re-run with --fix.")
        return

    # Our edits can only move assertions dated after the earliest entry we
    # touch, so that is the horizon we hold ourselves to.
    since = min(f.entry.date for f in findings if f.editable)
    apply_edits(ledger, lines, edits, balances, account)
    failures = failing_assertions(root, account, since)
    if not failures:
        click.echo(
            f"\nApplied. Verified against the untouched {anchor.date} "
            f"assertion ({anchor.amount.number} AUD)."
            if anchor else "\nApplied (no balance directive to verify against)."
        )
        return

    shutil.copy(ledger + ".bak", ledger)
    # The edits were sound as far as the API could tell, so a residual gap is
    # most likely a hold that aged out of the window and was released unseen.
    report_shortfall(entries, account, anchor, pending)
    raise click.ClickException(
        "Rolled back -- these balance assertions do not hold after the edits:\n"
        + "\n".join(f"  {f.message}" for f in failures)
    )


if __name__ == "__main__":
    cli()
