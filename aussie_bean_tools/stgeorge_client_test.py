import click
from click.testing import CliRunner

from aussie_bean_tools import stgeorge_client


# A St George export sample. Note the trailing comma (an empty 6th field) on
# every data row, exactly as the site emits it.
SAMPLE_CSV = (
    "Date,Description,Debit,Credit,Balance\n"
    "29/05/2026,Visa Purchase Spotify,22.99,,15407.88,\n"
    "06/05/2026,Red Energy,261.76,,13125.60,\n"
    "04/05/2026,Transport Nsw,,37.86,14619.26,\n"
).encode("utf-8")


def test_filter_keeps_only_in_range_rows():
    out = stgeorge_client._filter_csv_to_range(SAMPLE_CSV, "2026-05-01", "2026-05-10")
    lines = out.decode("utf-8").splitlines()
    assert lines[0] == "Date,Description,Debit,Credit,Balance"
    assert [l.split(",")[0] for l in lines[1:]] == ["06/05/2026", "04/05/2026"]


def test_filter_empty_range_yields_header_only():
    # The site's fallback rows (all out of range) must be dropped, leaving the
    # header alone so the import appends nothing.
    out = stgeorge_client._filter_csv_to_range(SAMPLE_CSV, "2026-05-30", "2026-05-31")
    assert out.decode("utf-8").splitlines() == [
        "Date,Description,Debit,Credit,Balance"]


def test_filter_is_inclusive_of_boundaries():
    out = stgeorge_client._filter_csv_to_range(SAMPLE_CSV, "2026-05-04", "2026-05-29")
    dates = [l.split(",")[0] for l in out.decode("utf-8").splitlines()[1:]]
    assert dates == ["29/05/2026", "06/05/2026", "04/05/2026"]


def test_filter_preserves_row_verbatim_including_trailing_comma():
    out = stgeorge_client._filter_csv_to_range(SAMPLE_CSV, "2026-05-06", "2026-05-06")
    lines = out.decode("utf-8").splitlines()
    assert lines[1] == "06/05/2026,Red Energy,261.76,,13125.60,"


def test_resolve_password_returns_supplied_value_without_prompting(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("should not prompt when password supplied")
    monkeypatch.setattr(click, "prompt", boom)
    assert stgeorge_client.resolve_password("hunter2") == "hunter2"


def test_resolve_password_prompts_when_missing(monkeypatch):
    monkeypatch.setattr(click, "prompt", lambda *a, **k: "typed-secret")
    assert stgeorge_client.resolve_password(None) == "typed-secret"


def test_resolve_password_prompt_hides_input(monkeypatch):
    captured = {}
    def fake_prompt(text, **kwargs):
        captured.update(kwargs)
        return "x"
    monkeypatch.setattr(click, "prompt", fake_prompt)
    stgeorge_client.resolve_password(None)
    assert captured.get("hide_input") is True


def test_cli_download_requires_access_number():
    runner = CliRunner()
    result = runner.invoke(
        stgeorge_client.cli,
        ["download", "--account", "x", "--from", "2026-01-01", "--to", "2026-01-02"],
        env={"STGEORGE_ACCESS_NUMBER": "", "STGEORGE_SECURITY_NUMBER": ""},
    )
    assert result.exit_code != 0
