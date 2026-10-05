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
    """Enumerate UIA elements from the foreground window's tree only.

    Resolve the foreground window DIRECTLY from its hwnd. The previous
    implementation did ``for w in Desktop(backend="uia").windows(): if
    w.handle == fg_hwnd``, which enumerates every top-level window on the
    desktop just to find one: measured at 120.16s for 14 windows (~8.6s each)
    on this machine, against 0.01s + 0.9s for the direct-handle path. That
    single call was 95% of ``Perception.observe()`` (122s -> ~3s).
    """
    import win32gui
    from pywinauto.controls.uiawrapper import UIAWrapper
    from pywinauto.uia_element_info import UIAElementInfo

    elements = []
    try:
        fg_hwnd = win32gui.GetForegroundWindow()
        if not fg_hwnd:
            return elements
        window = UIAWrapper(UIAElementInfo(fg_hwnd))
        if not window.is_visible():
            return elements
        children = window.descendants()
    except Exception:
        return elements

    # The window ROOT itself is not a descendant, so it was never enumerated --
    # which meant the scene never carried the window's own identity (control
    # type "Window", and its bbox == the whole window). Downstream frame/process
    # logic was left inferring the frame from size because this node was missing
    # (confirmed live 2026-10-05: 975 uia elements, 0 of role "Window"). Emit it
    # first so the root is present and identifiable.
    try:
        elements.append(_element_from_rect(
            window.rectangle(),
            source="uia",
            text=window.window_text(),
            role=window.element_info.control_type,
            enabled=window.is_enabled(),
            visible=True,
        ))
    except Exception:
        pass

    for c in children:
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
    return elements
