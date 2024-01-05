import unittest
from os import path

from beancount.ingest import regression_pytest as regtest
from upbank import UpbankImporter

IMPORTER = UpbankImporter("Assets:Bank:John-Upbank", tags={"john"})


@regtest.with_importer(IMPORTER)
@regtest.with_testdir(path.dirname(__file__))
class TestUpbankImporter(regtest.ImporterTestBase):
    pass


if __name__ == "__main__":
    unittest.main()
