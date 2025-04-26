import os
import pytest
import logging
logging.basicConfig(level=logging.DEBUG)

from beancount.ingest.cache import get_file
from aussie_bean_tools import UpbankImporter

# Define the importer instance
@pytest.fixture
def importer():
    return UpbankImporter()


# Test the identify method
def test_identify(importer):
    test_file = os.path.join(os.path.dirname(__file__), 'testdata/upbank.json')
    result = importer.identify(get_file(test_file))
    assert result == True

# import unittest
# from os import path
#
# from beancount.ingest import regression
# from beancount.ingest.importer import ImporterProtocol
# from beancount.core import data
#
# from beancount.ingest import regression_pytest as regtest
# from .upbank_importer import UpbankImporter
#
# IMPORTER = UpbankImporter("Assets:Bank:John-Upbank", tags={"john"})
#
#
# @regtest.with_importer(IMPORTER)
# @regtest.with_testdir(path.dirname(__file__))
# class TestUpbankImporter(regtest.ImporterTestBase):
#     pass
#
#
# if __name__ == "__main__":
#     unittest.main()
