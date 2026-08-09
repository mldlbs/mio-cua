from mio_cua.models.element import Element


def _element_from_rect(rect, source: str, text: str, role: str, enabled: bool = True, visible: bool = True) -> Element:
    return Element(
        id=0,
        source=source,
        text=text or "",
        role=role or "unknown",
        bbox=(int(rect.left), int(rect.top), int(rect.width()), int(rect.height())),
        enabled=enabled,
        visible=visible,
    )


def get_elements() -> list:
    """Enumerate UIA elements from the foreground window's tree only."""
    import win32gui
    from pywinauto import Desktop

    elements = []
    try:
        desktop = Desktop(backend="uia")
        fg_hwnd = win32gui.GetForegroundWindow()
    except Exception:
        return elements
    for w in desktop.windows():
        try:
            if w.handle != fg_hwnd:
                continue
            if not w.is_visible():
                continue
            for c in w.descendants():
                try:
                    info = c.element_info
                    elements.append(_element_from_rect(
                        c.rectangle(),
                        source="uia",
                        text=c.window_text(),
                        role=info.control_type,
                        enabled=c.is_enabled(),
                        visible=c.is_visible(),
                    ))
                except Exception:
                    continue
        except Exception:
            continue
    return elements
