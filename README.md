# Beancount tools

* download transactions with the UpBank API
* complete new transactions by fuzzy-matching them against existing transactions
* import transactions from a St George Bank CSV file

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

