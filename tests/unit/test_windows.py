from mio_cua.automation.windows import set_dpi_aware, get_active_window, get_cursor


def test_dpi_aware_runs():
    set_dpi_aware()  # should not raise


def test_get_cursor_tuple():
    x, y = get_cursor()
    assert isinstance(x, int)
    assert isinstance(y, int)


def test_get_active_window_str():
    title = get_active_window()
    assert isinstance(title, str)


def test_focus_window_empty_title_returns_false():
    from mio_cua.automation.windows import focus_window
    assert focus_window("") is False
