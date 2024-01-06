# Beancount tools

* download transactions with the UpBank API
* complete new transactions by fuzzy-matching them against existing transactions
* import transactions from a St George Bank CSV file

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
### Example

Retrieve the most recent upbank transactions, and save to file.  
```  
$ upbank --token $UPBANK_TOKEN recent > /tmp/upbank.json
```
Convert the transactions json into beancount format, and save to file. 
```
$ bean-extract -e master.beancount bean.config /tmp/upbank.json > /tmp/up.beancount
```
Autocomplete transactions by fuzzy matching against past transactions.
```
$ fuzzer /tmp/up.beancount
```


### API token

https://api.up.com.au/

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

