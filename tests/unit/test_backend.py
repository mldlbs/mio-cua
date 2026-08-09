from mio_cua.automation.backends import _parse_keys


def test_parse_keys_single_plus_is_literal():
    # The plus sign is BOTH the combo separator and the calculator '+' key.
    # A lone '+' must not be split into empty parts -- it is the literal char.
    assert _parse_keys("+") == ["+"]


def test_parse_keys_combo():
    assert _parse_keys("ctrl+s") == ["ctrl", "s"]
    assert _parse_keys("ctrl+shift+n") == ["ctrl", "shift", "n"]
    assert _parse_keys("alt+F4") == ["alt", "F4"]


def test_parse_keys_single_char_and_empty():
    assert _parse_keys("1") == ["1"]
    assert _parse_keys("") == []
    assert _parse_keys("   ") == []


def test_parse_keys_plus_in_combo_but_not_alone():
    # "shift+=" is a combo (plus is a separator, not a literal).
    assert _parse_keys("shift+=") == ["shift", "="]
