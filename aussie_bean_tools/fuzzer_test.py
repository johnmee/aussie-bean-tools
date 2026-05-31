import os

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
