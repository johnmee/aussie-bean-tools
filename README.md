# Aussie Bean Tools

Tools for using [beancount](https://beancount.github.io/) with [Up Bank](https://up.com.au/), [St George Bank](https://www.stgeorge.com/), [Fastmail](https://fastmail.com/), 
and autocompleting the routine transactions.

* downloads transactions with the UpBank API
* completes new transactions, by fuzzy-matching them against existing transactions
* imports transactions from a St George Bank CSV file
* comments out transactions that are already recorded in another account's file
* sends an email via fastmail.com

# Example

Retrieve recent upbank transactions...
```  
$ upbank --token $UPBANK_TOKEN recent > /tmp/upbank.json
```
Convert transactions from json to beancount format... 
```
$ python bean.config extract -e master.beancount /tmp/upbank.json > /tmp/up.beancount
```
Autocomplete transactions by fuzzy matching against past transactions...
```
$ fuzzer /tmp/up.beancount
```
Convert transactions from stgeorge csv to beancount format, and autocomplete...
```commandline
$ python bean.config extract -e master.beancount stgeorge.csv | fuzzer
```

# Upbank

```commandline
Usage: upbank [OPTIONS] COMMAND [ARGS]...

Options:
  --token TEXT  Upbank token
  --help        Show this message and exit.

Commands:
  balance     Fetch the current balance of the account.
  categories  Get a list of transaction categories.
  month       Download a sequence of transactions.
  ping        Send a ping to Upbank, to verify your token and their API...
  recent      Download a sequence of transactions.
```



### Upbank API token
See https://api.up.com.au/

You need a personal token to use the upbank API.
I put it into an environment variable for easy usage.

### bean.config

Beancount v3 (beangulp) importer configs are executable scripts. Run the config
directly, e.g. `python bean.config extract -e master.beancount /tmp/upbank.json`.

```bean.config
from aussie_bean_tools import UpbankImporter
from aussie_bean_tools import StGeorgeImporter
from beangulp import Ingest

Ingest([
  UpbankImporter("Assets:Bank:Upbank"),
  StGeorgeImporter("Assets:Bank:StGeorge:Freedom"),
])()
```

# St George

Download a date-ranged transaction CSV by driving a browser, since St George has
no public API. A persistent browser profile keeps the device "remembered", so 2FA
is only needed on the first run.

One-time browser install:
```commandline
$ playwright install chromium
```

Credentials come from the environment. The internet password is *not stored* by
default — it is prompted (hidden) each run unless you opt in by setting
`STGEORGE_PASSWORD`:
```commandline
$ export STGEORGE_ACCESS_NUMBER=...
$ export STGEORGE_SECURITY_NUMBER=...
$ # optional opt-in, otherwise you are prompted:
$ # export STGEORGE_PASSWORD=...
```

Download an account's transactions for a date range:
```commandline
$ stgeorge download --account "Complete Freedom" \
    --from 2026-05-01 --to 2026-05-30 --output joint.csv
```

```commandline
Usage: stgeorge [OPTIONS] COMMAND [ARGS]...

Options:
  --access-number TEXT    Customer access number (env STGEORGE_ACCESS_NUMBER).
  --security-number TEXT  Security number (env STGEORGE_SECURITY_NUMBER).
  --password TEXT         Internet password. Unset by default -> prompted each run.
  --profile-dir TEXT      Persistent browser profile dir (keeps the remembered device).
  --headed / --headless   Headed browser so 2FA can be completed by hand.
  --help                  Show this message and exit.

Commands:
  download  Download a date-ranged transaction CSV for one account.
```

## Fuzzer

Add the cross account posting to routine beancount transactions.

A tool which consumes a beancount file fragment, with only
one posting per transaction, and outputs the same beancount file with 
speculatively completed postings guessed from historical entries.

```commandline
Usage: fuzzer [OPTIONS] INFILE

  Autocomplete postings of transactions.

  * Build a dictionary of past transactions and a summary key/description. *
  For each transaction fuzzymatch it against the keys in the dictionary * and
  copy the postings and tags of the matched transaction from history

Options:
  --threshold INTEGER  Only use fuzz scores better than this.  [default: 86]
  --training PATH      Beancount file to use as a template for predictions.
                       [default: master.beancount]
  --help               Show this message and exit.
```

May issue a warning.  Works fine, but slower without. Install `python-Levenshtein` if desired.

## Bean-comment

Silence transfers already recorded in another account file by commenting them out.

When importing into a joint account, some transactions (e.g. transfers to a personal
account) are already fully recorded elsewhere. Running `bean-comment` after `fuzzer`
prefixes those transactions with `;` so they appear in the file for reference but are
ignored by beancount.

```commandline
Usage: bean-comment [OPTIONS] ACCOUNTS...

  Read beancount from stdin; comment out transactions posting to ACCOUNTS.

  Any transaction that contains a posting to one of the given ACCOUNTS has
  every line prefixed with ';', turning it into a beancount comment block.
  All other transactions pass through unchanged.

  Typical use: pipe fuzzer output through bean-comment before appending to
  your ledger, to silence transfers that are already recorded in another
  account's file.

  Example:
      fuzzer /tmp/joint.beancount \
          | bean-comment Assets:Bank:John-Upbank Assets:Bank:Fiona-Upbank \
          >> joint-freedom-2026.beancount
```
