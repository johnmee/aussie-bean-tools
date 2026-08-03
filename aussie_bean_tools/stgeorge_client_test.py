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


def test_attached_wraps_existing_page_without_init():
    sentinel_page = object()
    client = stgeorge_client.StGeorgeClient.attached(sentinel_page)
    assert client._page is sentinel_page


class _FakeContext:
    def __init__(self):
        self.pages = []

    def new_page(self):
        return object()

    def close(self):
        pass


class _FakeChromium:
    def __init__(self):
        self.launch_calls = []

    def launch_persistent_context(self, **kwargs):
        self.launch_calls.append(kwargs)
        return _FakeContext()


class _FakePlaywright:
    def __init__(self):
        self.chromium = _FakeChromium()

    def stop(self):
        pass


def _patch_sync_playwright(monkeypatch):
    fake_pw = _FakePlaywright()
    fake_sync_playwright = type(
        "FakeSyncPlaywright", (), {"start": lambda self: fake_pw})()
    monkeypatch.setattr(
        "playwright.sync_api.sync_playwright", lambda: fake_sync_playwright)
    return fake_pw


def test_enter_passes_remote_debugging_port_when_set(monkeypatch, tmp_path):
    fake_pw = _patch_sync_playwright(monkeypatch)
    client = stgeorge_client.StGeorgeClient(
        "a", "s", "p", str(tmp_path), headed=True, remote_debugging_port=9222)
    with client:
        pass
    assert fake_pw.chromium.launch_calls[0]["args"] == [
        "--remote-debugging-port=9222"]


def test_enter_omits_args_when_port_not_set(monkeypatch, tmp_path):
    fake_pw = _patch_sync_playwright(monkeypatch)
    client = stgeorge_client.StGeorgeClient("a", "s", "p", str(tmp_path))
    with client:
        pass
    assert "args" not in fake_pw.chromium.launch_calls[0]


def test_enter_passes_slow_mo_when_set(monkeypatch, tmp_path):
    fake_pw = _patch_sync_playwright(monkeypatch)
    client = stgeorge_client.StGeorgeClient(
        "a", "s", "p", str(tmp_path), slow_mo_ms=500)
    with client:
        pass
    assert fake_pw.chromium.launch_calls[0]["slow_mo"] == 500


def test_enter_omits_slow_mo_when_not_set(monkeypatch, tmp_path):
    fake_pw = _patch_sync_playwright(monkeypatch)
    client = stgeorge_client.StGeorgeClient("a", "s", "p", str(tmp_path))
    with client:
        pass
    assert "slow_mo" not in fake_pw.chromium.launch_calls[0]


class _FakeClient:
    instances = []

    def __init__(self, access_number, security_number, password,
                 profile_dir, headed, remote_debugging_port=None,
                 slow_mo_ms=None):
        self.kwargs = dict(
            access_number=access_number, security_number=security_number,
            password=password, profile_dir=profile_dir, headed=headed,
            remote_debugging_port=remote_debugging_port,
            slow_mo_ms=slow_mo_ms)
        self.login_count = 0
        self.download_calls = []
        _FakeClient.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def login(self):
        self.login_count += 1

    def download(self, account, date_from, date_to):
        self.download_calls.append((account, date_from, date_to))
        return b"Date,Description,Debit,Credit,Balance\n"


def test_debug_session_logs_in_and_passes_port(monkeypatch):
    _FakeClient.instances.clear()
    monkeypatch.setattr(stgeorge_client, "StGeorgeClient", _FakeClient)
    monkeypatch.setattr(stgeorge_client, "_wait_forever", lambda: None)

    runner = CliRunner()
    result = runner.invoke(
        stgeorge_client.cli,
        ["debug-session", "--port", "9333"],
        env={"STGEORGE_ACCESS_NUMBER": "a", "STGEORGE_SECURITY_NUMBER": "s",
             "STGEORGE_PASSWORD": "p"},
    )
    assert result.exit_code == 0, result.output
    assert _FakeClient.instances[0].kwargs["remote_debugging_port"] == 9333
    assert _FakeClient.instances[0].login_count == 1


def test_slow_mo_option_passed_through_to_client(monkeypatch):
    _FakeClient.instances.clear()
    monkeypatch.setattr(stgeorge_client, "StGeorgeClient", _FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        stgeorge_client.cli,
        ["--slow-mo", "750", "download", "--account", "x",
         "--from", "2026-01-01", "--to", "2026-01-02"],
        env={"STGEORGE_ACCESS_NUMBER": "a", "STGEORGE_SECURITY_NUMBER": "s",
             "STGEORGE_PASSWORD": "p"},
    )
    assert result.exit_code == 0, result.output
    assert _FakeClient.instances[0].kwargs["slow_mo_ms"] == 750


def test_slow_mo_option_defaults_to_none(monkeypatch):
    _FakeClient.instances.clear()
    monkeypatch.setattr(stgeorge_client, "StGeorgeClient", _FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        stgeorge_client.cli,
        ["download", "--account", "x",
         "--from", "2026-01-01", "--to", "2026-01-02"],
        env={"STGEORGE_ACCESS_NUMBER": "a", "STGEORGE_SECURITY_NUMBER": "s",
             "STGEORGE_PASSWORD": "p"},
    )
    assert result.exit_code == 0, result.output
    assert _FakeClient.instances[0].kwargs["slow_mo_ms"] is None


def test_download_batch_requires_matching_option_counts(monkeypatch):
    _FakeClient.instances.clear()
    monkeypatch.setattr(stgeorge_client, "StGeorgeClient", _FakeClient)

    runner = CliRunner()
    result = runner.invoke(
        stgeorge_client.cli,
        ["download-batch",
         "--account", "Complete Freedom", "--from", "2026-01-01",
         "--to", "2026-01-31", "--output", "a.csv",
         "--account", "Incentive Saver", "--from", "2026-01-01",
         "--output", "b.csv"],
        env={"STGEORGE_ACCESS_NUMBER": "a", "STGEORGE_SECURITY_NUMBER": "s",
             "STGEORGE_PASSWORD": "p"},
    )
    assert result.exit_code != 0
    assert "same number of times" in result.output
    assert _FakeClient.instances == []


def test_download_batch_logs_in_once_for_multiple_accounts(monkeypatch, tmp_path):
    _FakeClient.instances.clear()
    monkeypatch.setattr(stgeorge_client, "StGeorgeClient", _FakeClient)

    joint_out = tmp_path / "joint.csv"
    saver_out = tmp_path / "saver.csv"
    runner = CliRunner()
    result = runner.invoke(
        stgeorge_client.cli,
        ["download-batch",
         "--account", "Complete Freedom", "--from", "2026-01-01",
         "--to", "2026-01-31", "--output", str(joint_out),
         "--account", "Incentive Saver", "--from", "2026-02-01",
         "--to", "2026-02-28", "--output", str(saver_out)],
        env={"STGEORGE_ACCESS_NUMBER": "a", "STGEORGE_SECURITY_NUMBER": "s",
             "STGEORGE_PASSWORD": "p"},
    )
    assert result.exit_code == 0, result.output
    client = _FakeClient.instances[0]
    assert client.login_count == 1
    assert client.download_calls == [
        ("Complete Freedom", "2026-01-01", "2026-01-31"),
        ("Incentive Saver", "2026-02-01", "2026-02-28"),
    ]
    assert joint_out.exists()
    assert saver_out.exists()


def test_cli_download_requires_access_number():
    runner = CliRunner()
    result = runner.invoke(
        stgeorge_client.cli,
        ["download", "--account", "x", "--from", "2026-01-01", "--to", "2026-01-02"],
        env={"STGEORGE_ACCESS_NUMBER": "", "STGEORGE_SECURITY_NUMBER": ""},
    )
    assert result.exit_code != 0
