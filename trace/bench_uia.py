import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def t(label, fn):
    s = time.time()
    out = fn()
    print(f"  {label:34} {time.time() - s:7.2f}s")
    return out


def main():
    import win32gui
    from pywinauto import Desktop

    fg = win32gui.GetForegroundWindow()
    print(f"fg hwnd={fg} title={win32gui.GetWindowText(fg)!r}")

    desktop = t("Desktop(backend='uia')", lambda: Desktop(backend="uia"))
    wins = t("desktop.windows()", lambda: desktop.windows())
    print(f"     top-level windows: {len(wins)}")

    match = None
    for w in wins:
        if w.handle == fg:
            match = w
            break
    print(f"     matched fg: {match is not None}")

    if match is not None:
        t("w.is_visible()", match.is_visible)
        t("w.descendants()", lambda: match.descendants())

    # Direct-from-handle path: skips the full desktop enumeration.
    print("\ndirect path:")
    from pywinauto.controls.uiawrapper import UIAWrapper
    from pywinauto.uia_element_info import UIAElementInfo

    el = t("UIAElementInfo.from_handle", lambda: UIAElementInfo.from_handle(fg))
    wrapper = t("UIAWrapper(el)", lambda: UIAWrapper(el))
    desc = t("wrapper.descendants()", lambda: wrapper.descendants())
    print(f"     descendants: {len(desc)}")

    try:
        ei = t("wrapper.element_info.children()", lambda: wrapper.element_info.children())
        print(f"     children (no deep walk): {len(ei)}")
    except Exception as e:
        print(f"     children failed: {e}")


if __name__ == "__main__":
    main()
