import logging
import os

import pytest
from aussie_bean_tools import UpbankImporter

logging.basicConfig(level=logging.DEBUG)


# Define the importer instance
@pytest.fixture
def importer():
    return UpbankImporter()


# Test the identify method
def test_identify(importer):
    test_file = os.path.join(os.path.dirname(__file__), 'testdata/upbank.json')
    result = importer.identify(test_file)
    assert result is True
