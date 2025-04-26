from .fuzzer import fuzzer


def test_fuzzer():
    # call the fuzzer
    threshold = 86
    # training = "testdata/training.beancount"
    # training = "../../money/john-upbank-2025.beancount"
    training = "../../money/master.beancount"
    testfile = "testdata/fuzzing.beancount"

    fuzzer(threshold, training, testfile)
