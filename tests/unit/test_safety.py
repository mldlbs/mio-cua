import time

from mio_cua.agent.safety import Safety


def test_step_limit():
    s = Safety(max_steps=2, timeout_s=60, emergency_key="f9", hotkey_enabled=False)
    assert s.should_stop() is False
    s.record_step()
    s.record_step()
    assert s.should_stop() is True


def test_timeout():
    s = Safety(max_steps=50, timeout_s=0.05, emergency_key="f9", hotkey_enabled=False)
    time.sleep(0.1)
    assert s.should_stop() is True


def test_manual_stop():
    s = Safety(max_steps=50, timeout_s=60, emergency_key="f9", hotkey_enabled=False)
    s.stop()
    assert s.should_stop() is True


def test_status_running():
    s = Safety(max_steps=50, timeout_s=60, emergency_key="f9", hotkey_enabled=False)
    assert s.status() == "RUNNING"


def test_status_aborted():
    s = Safety(max_steps=50, timeout_s=60, emergency_key="f9", hotkey_enabled=False)
    s.stop()
    assert s.status() == "ABORTED"


def test_status_aborted_on_step_limit():
    s = Safety(max_steps=2, timeout_s=60, emergency_key="f9", hotkey_enabled=False)
    s.record_step()
    s.record_step()
    assert s.status() == "ABORTED"
