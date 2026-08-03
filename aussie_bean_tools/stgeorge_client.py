"""St George Bank transaction download.

Drives a browser (no public API) to export a date-ranged CSV per account.
Contains no personal data: credentials and account identifiers are supplied
by the caller via options / environment variables.
"""
import datetime
import os

import click


def _format_date(iso_date):
    """Convert a YYYY-MM-DD string to the d/mm/yyyy the St George form accepts.

    The site's From:/To: boxes take a typed date like ``1/05/2026``.
    """
    d = datetime.datetime.strptime(iso_date, "%Y-%m-%d").date()
    return f"{d.day}/{d.month:02d}/{d.year}"


def _filter_csv_to_range(csv_bytes, date_from, date_to):
    """Keep only the rows whose Date falls within [date_from, date_to] inclusive.

    St George's "Export Transaction History" returns recent transactions when the
    requested range contains none, instead of an empty file. Enforcing the
    requested window here makes ``--from``/``--to`` reliable: an empty range
    yields a header-only CSV (which imports nothing) rather than stale duplicates.

    Each kept line is emitted verbatim (preserving the site's trailing comma);
    only the leading Date field is parsed to decide inclusion.

    Args:
        csv_bytes: the raw exported CSV.
        date_from, date_to: YYYY-MM-DD strings.
    """
    lo = datetime.datetime.strptime(date_from, "%Y-%m-%d").date()
    hi = datetime.datetime.strptime(date_to, "%Y-%m-%d").date()
    lines = csv_bytes.decode("utf-8").splitlines()
    if not lines:
        return csv_bytes
    kept = [lines[0]]  # header
    for line in lines[1:]:
        if not line.strip():
            continue
        date_field = line.split(",", 1)[0].strip()
        try:
            d = datetime.datetime.strptime(date_field, "%d/%m/%Y").date()
        except ValueError:
            continue
        if lo <= d <= hi:
            kept.append(line)
    return ("\n".join(kept) + "\n").encode("utf-8")


def resolve_password(password):
    """Return the internet password, prompting with hidden input if absent.

    Default posture is *not stored*: when --password / STGEORGE_PASSWORD is
    unset, the user is prompted each run.
    """
    if password:
        return password
    return click.prompt("StGeorge internet password", hide_input=True)


def _default_profile_dir():
    return os.path.join(click.get_app_dir("aussie-bean-tools"), "stgeorge-profile")


ACCOUNTS_URL = "https://ibanking.stgeorge.com.au/ibank/viewAccountPortfolio.html"


class StGeorgeClient:
    """Playwright driver for the St George internet-banking site."""

    def __init__(self, access_number, security_number, password,
                 profile_dir, headed=True, remote_debugging_port=None,
                 slow_mo_ms=None):
        self.access_number = access_number
        self.security_number = security_number
        self.password = password
        self.profile_dir = profile_dir
        self.headed = headed
        self.remote_debugging_port = remote_debugging_port
        self.slow_mo_ms = slow_mo_ms
        self._playwright = None
        self._context = None
        self._page = None

    # Seconds to wait for the post-login accounts page. Generous so the user can
    # complete a 2FA challenge by hand on the first run with a fresh profile.
    LOGIN_TIMEOUT_MS = 180_000

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._playwright = sync_playwright().start()
        kwargs = dict(
            user_data_dir=self.profile_dir,
            headless=not self.headed,
            accept_downloads=True,
        )
        if self.remote_debugging_port is not None:
            kwargs["args"] = [
                f"--remote-debugging-port={self.remote_debugging_port}"]
        if self.slow_mo_ms is not None:
            kwargs["slow_mo"] = self.slow_mo_ms
        self._context = self._playwright.chromium.launch_persistent_context(
            **kwargs)
        self._page = (self._context.pages[0]
                      if self._context.pages else self._context.new_page())
        return self

    def __exit__(self, *exc):
        if self._context:
            self._context.close()
        if self._playwright:
            self._playwright.stop()

    @classmethod
    def attached(cls, page):
        """Wrap an already-authenticated page from an external session.

        Used by the manual debug script to drive download() against a
        browser tab a separate `debug-session` process already logged in,
        skipping __init__/login().
        """
        self = cls.__new__(cls)
        self._page = page
        return self

    def login(self):
        """Navigate home -> Internet Banking popup -> submit credentials.

        The login form opens in a popup window, which becomes the working page
        for the rest of the session. The home-page link must be used to reach
        the login form (arriving at the login URL directly is rejected).
        """
        page = self._page
        page.goto("https://www.stgeorge.com.au/")
        page.get_by_role("button", name="Logon. Hit enter to open").click()
        with page.expect_popup() as popup_info:
            page.get_by_role("link", name="Internet Banking").click()
        bank = popup_info.value
        bank.get_by_role("textbox", name="Enter your Card or Access").fill(
            self.access_number)
        bank.get_by_role("textbox", name="Enter your Security number").fill(
            self.security_number)
        bank.get_by_role("textbox", name="Enter your Internet Banking").fill(
            self.password)
        bank.get_by_role("button", name="Logon").click()
        # The banking popup is where account selection and export happen.
        self._page = bank

    def download(self, account, date_from, date_to):
        """Open an account, set the date range, and return the exported CSV bytes.

        Args:
            account: site-visible account name. Matched as a case-insensitive
                substring, so "Incentive Saver" finds "Incentive Saver 486 ...".
            date_from, date_to: YYYY-MM-DD strings.
        """
        page = self._page
        # Wait (long) for the accounts page so a 2FA challenge can be completed
        # by hand, then open the requested account.
        page.get_by_role("link", name=account).click(timeout=self.LOGIN_TIMEOUT_MS)
        page.get_by_role("link", name="Select a date range").click()

        from_box = page.get_by_role("textbox", name="From:")
        from_box.click()
        from_box.fill(_format_date(date_from))
        from_box.press("Tab")

        to_box = page.get_by_role("textbox", name="To:")
        to_box.click()
        to_box.fill(_format_date(date_to))
        to_box.press("Tab")

        page.get_by_role("button", name="Search").click()
        with page.expect_download() as dl_info:
            page.get_by_role("link", name="Export Transaction History").click()
        download = dl_info.value
        with open(download.path(), "rb") as fh:
            raw = fh.read()
        # Return to the account list so a second download() call in the same
        # session (a different account) starts from where get_by_role("link",
        # name=account) above expects to be.
        page.goto(ACCOUNTS_URL)
        # The site falls back to recent rows when the range is empty; enforce
        # the requested window so we never import out-of-range duplicates.
        return _filter_csv_to_range(raw, date_from, date_to)


@click.group()
@click.option("--access-number", envvar="STGEORGE_ACCESS_NUMBER", required=True,
              help="Customer access number (env STGEORGE_ACCESS_NUMBER).")
@click.option("--security-number", envvar="STGEORGE_SECURITY_NUMBER", required=True,
              help="Security number (env STGEORGE_SECURITY_NUMBER).")
@click.option("--password", envvar="STGEORGE_PASSWORD", default=None,
              help="Internet password. Unset by default -> prompted each run.")
@click.option("--profile-dir", envvar="STGEORGE_PROFILE_DIR",
              default=_default_profile_dir,
              help="Persistent browser profile dir (keeps the remembered device).")
@click.option("--headed/--headless", default=True,
              help="Headed browser so 2FA can be completed by hand.")
@click.option("--slow-mo", "slow_mo_ms", type=int, default=None,
              help="Milliseconds to pause after each browser action "
                   "(e.g. 500), so the scripted flow is watchable.")
@click.pass_context
def cli(ctx, access_number, security_number, password, profile_dir, headed,
        slow_mo_ms):
    ctx.obj = {
        "access_number": access_number,
        "security_number": security_number,
        "password": resolve_password(password),
        "profile_dir": profile_dir,
        "headed": headed,
        "slow_mo_ms": slow_mo_ms,
    }


def _write_csv(csv_bytes, output):
    """Write csv_bytes to output and report the row count to stderr."""
    n_rows = max(0, len([l for l in csv_bytes.decode("utf-8").splitlines()
                         if l.strip()]) - 1)
    with open(output, "wb") as fh:
        fh.write(csv_bytes)
    click.echo(f"Wrote {output} ({n_rows} transactions in range)", err=True)


@cli.command()
@click.option("--account", required=True,
              help="Site-visible account identifier to export.")
@click.option("--from", "date_from", required=True,
              help="From date, YYYY-MM-DD.")
@click.option("--to", "date_to", required=True,
              help="To date, YYYY-MM-DD.")
@click.option("--output", type=click.Path(dir_okay=False), default=None,
              help="Write CSV here (default: stdout).")
@click.pass_context
def download(ctx, account, date_from, date_to, output):
    """Download a date-ranged transaction CSV for one account."""
    cfg = ctx.obj
    with StGeorgeClient(cfg["access_number"], cfg["security_number"],
                        cfg["password"], cfg["profile_dir"], cfg["headed"],
                        slow_mo_ms=cfg["slow_mo_ms"]) as client:
        client.login()
        csv_bytes = client.download(account, date_from, date_to)
    if output:
        _write_csv(csv_bytes, output)
    else:
        click.echo(csv_bytes.decode("utf-8"))


@cli.command("download-batch")
@click.option("--account", "accounts", required=True, multiple=True,
              help="Site-visible account identifier. Repeatable; paired "
                   "positionally with --from/--to/--output.")
@click.option("--from", "date_froms", required=True, multiple=True,
              help="From date, YYYY-MM-DD. Repeatable, one per --account.")
@click.option("--to", "date_tos", required=True, multiple=True,
              help="To date, YYYY-MM-DD. Repeatable, one per --account.")
@click.option("--output", "outputs", required=True, multiple=True,
              type=click.Path(dir_okay=False),
              help="Write CSV here. Repeatable, one per --account.")
@click.pass_context
def download_batch(ctx, accounts, date_froms, date_tos, outputs):
    """Download date-ranged CSVs for multiple accounts in a single login.

    --account/--from/--to/--output are each repeatable and paired up by
    position, e.g.:

        stgeorge download-batch \\
            --account "Complete Freedom" --from 2026-07-01 --to 2026-07-31 --output joint.csv \\
            --account "Incentive Saver" --from 2026-06-01 --to 2026-07-31 --output saver.csv
    """
    if len({len(accounts), len(date_froms), len(date_tos), len(outputs)}) != 1:
        raise click.UsageError(
            "--account, --from, --to, and --output must each be given the "
            "same number of times")
    cfg = ctx.obj
    with StGeorgeClient(cfg["access_number"], cfg["security_number"],
                        cfg["password"], cfg["profile_dir"], cfg["headed"],
                        slow_mo_ms=cfg["slow_mo_ms"]) as client:
        client.login()
        for account, date_from, date_to, output in zip(
                accounts, date_froms, date_tos, outputs):
            csv_bytes = client.download(account, date_from, date_to)
            _write_csv(csv_bytes, output)


def _wait_forever():
    """Block until Ctrl+C, keeping the browser process alive."""
    import time
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


@cli.command("debug-session")
@click.option("--port", default=9222, show_default=True,
              help="Chrome remote debugging port, for connect_over_cdp().")
@click.pass_context
def debug_session(ctx, port):
    """Log in once and leave the browser running for manual debugging.

    Connect from a separate script with
    chromium.connect_over_cdp(f"http://localhost:{port}") to drive further
    actions (e.g. download()) against this already-authenticated session
    without repeating login.
    """
    cfg = ctx.obj
    with StGeorgeClient(cfg["access_number"], cfg["security_number"],
                        cfg["password"], cfg["profile_dir"], cfg["headed"],
                        remote_debugging_port=port,
                        slow_mo_ms=cfg["slow_mo_ms"]) as client:
        client.login()
        click.echo(f"Logged in. Connect via http://localhost:{port}", err=True)
        click.echo(
            "Leave this running. Press Ctrl+C to close the session.",
            err=True)
        _wait_forever()


if __name__ == "__main__":
    cli()
