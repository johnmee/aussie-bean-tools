# Aussie Bean Tools

Tools for using [beancount](https://beancount.github.io/) with [Up Bank](https://up.com.au/), [St George Bank](https://www.stgeorge.com/), [Fastmail](https://fastmail.com/), 
and autocompleting the routine transactions.

* downloads transactions with the UpBank API
* completes new transactions, by fuzzy-matching them against existing transactions
* imports transactions from a St George Bank CSV file
* sends an email via fastmail.com

# Example

Retrieve recent upbank transactions...
```  
$ upbank --token $UPBANK_TOKEN recent > /tmp/upbank.json
```
Convert transactions from json to beancount format... 
```
$ bean-extract -e master.beancount bean.config /tmp/upbank.json > /tmp/up.beancount
```
Autocomplete transactions by fuzzy matching against past transactions...
```
$ fuzzer /tmp/up.beancount
```
Convert transactions from stgeorge csv to beancount format, and autocomplete...
```commandline
$ bean-extract -e master.beancount bean.config stgeorge.csv | fuzzer
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

Beancount needs a config file something like this for `bean-extract` to work.

```bean.config
from aussie_bean_tools import upbank
from aussie_bean_tools import stgeorge

CONFIG = [
  upbank.UpbankImporter("Assets:Bank:Upbank"),
  stgeorge.StGeorgeImporter("Assets:Bank:StGeorge:Freedom"),
]
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
