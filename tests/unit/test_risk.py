from mio_cua.safety.risk import HIGH_RISK, is_high_risk


def test_high_risk_contains_expected_tools():
    assert "delete" in HIGH_RISK
    assert "overwrite" in HIGH_RISK
    assert "kill_process" in HIGH_RISK
    assert "close_window" in HIGH_RISK


def test_is_high_risk():
    assert is_high_risk("kill_process") is True
    assert is_high_risk("close_window") is True
    assert is_high_risk("click") is False
    assert is_high_risk("type") is False
    assert is_high_risk("") is False
    assert is_high_risk(None) is False
