import os
import tempfile

from .fuzzer import fuzzer

TESTDATA = os.path.join(os.path.dirname(__file__), "testdata")


def test_fuzzer_autocompletes_from_training(capsys):
    # fuzzing.beancount holds transactions missing their expense posting;
    # training.beancount holds the same transactions complete. The fuzzer
    # should copy the missing posting from the matching training entry.
    threshold = 86
    training = os.path.join(TESTDATA, "training.beancount")
    infile = os.path.join(TESTDATA, "fuzzing.beancount")

    fuzzer(threshold, training, infile)

    out = capsys.readouterr().out
    # "XS Espresso" matches a training entry posting to Expenses:Food:Eatout,
    # which is absent from the import file -> proves the posting was mimicked.
    assert "Expenses:Food:Eatout" in out


def test_fuzzer_empty_import_emits_marker_not_crash(capsys):
    # An import file with a balance directive but no transactions (e.g. every
    # row was a duplicate the extractor commented out, or the source had no
    # in-range rows). The fuzzer must not crash on the absent target account,
    # and must emit a valid-beancount comment marker plus the balance line.
    training = os.path.join(TESTDATA, "training.beancount")
    with tempfile.NamedTemporaryFile(
        "w", suffix=".beancount", delete=False
    ) as f:
        f.write("2026-05-31 balance Assets:Bank:IncentiveSaver  100.00 AUD\n")
        infile = f.name

    try:
        fuzzer(86, training, infile)
    finally:
        os.unlink(infile)

    out = capsys.readouterr().out
    assert "; Nothing to import." in out
    assert "balance Assets:Bank:IncentiveSaver" in out
