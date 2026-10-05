import time

from mio_cua.safety.confirm import Confirmation, _ask


def test_disabled_confirmation_passes_through():
    c = Confirmation(enabled=False)
    assert c.confirm("kill_process", {"name": "notepad.exe"}) is True


def test_env_off_disables(monkeypatch):
    monkeypatch.setenv("MIO_CUA_CONFIRM_OFF", "1")
    c = Confirmation()  # enabled resolved from env
    assert c.enabled is False
    assert c.confirm("kill_process", {}) is True


def test_env_unset_enables(monkeypatch):
    monkeypatch.delenv("MIO_CUA_CONFIRM_OFF", raising=False)
    c = Confirmation()
    assert c.enabled is True


def test_ask_yes_returns_true():
    def fake_dialog(text, title):
        return 6  # IDYES

    assert _ask("t", "text", 5.0, dialog=fake_dialog) is True


def test_ask_no_returns_false():
    def fake_dialog(text, title):
        return 7  # IDNO

    assert _ask("t", "text", 5.0, dialog=fake_dialog) is False


def test_ask_dialog_error_fails_closed():
    def boom(text, title):
        raise RuntimeError("no desktop session")

    assert _ask("t", "text", 5.0, dialog=boom) is False


def test_ask_timeout_denies():
    def slow(text, title):
        time.sleep(5)

    start = time.time()
    assert _ask("t", "text", 0.05, dialog=slow) is False
    assert time.time() - start < 2.0, "timeout must not wait for the dialog"
