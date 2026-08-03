"""Manual debug driver for StGeorgeClient.download().

Start `stgeorge debug-session` first and leave it running (it logs in once
and exposes a CDP endpoint). Then edit ACCOUNT/DATE_FROM/DATE_TO below as
needed and run this script, with PWDEBUG=1 to step through each action in
the Playwright Inspector:

    PWDEBUG=1 python aussie_bean_tools/stgeorge_manual_download.py

Re-run as many times as needed after editing download() in
stgeorge_client.py -- login is never repeated, since this connects to the
already-authenticated browser debug-session started. If download() left
the tab on the export/download view, navigate back to the accounts page by
hand before re-running.
"""
from playwright.sync_api import sync_playwright

from aussie_bean_tools.stgeorge_client import StGeorgeClient

PORT = 9222
ACCOUNT = "Incentive Saver"
DATE_FROM = "2026-06-15"
DATE_TO = "2026-07-15"


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(
            f"http://localhost:{PORT}")
        context = browser.contexts[0]
        page = context.pages[0] if context.pages else context.new_page()
        client = StGeorgeClient.attached(page)
        csv_bytes = client.download(ACCOUNT, DATE_FROM, DATE_TO)
        print(csv_bytes.decode("utf-8"))


if __name__ == "__main__":
    main()
