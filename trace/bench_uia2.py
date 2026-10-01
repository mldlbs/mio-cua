import inspect
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def t(label, fn):
    s = time.time()
    try:
        out = fn()
    except Exception as e:
        print(f"  {label:40} FAILED {time.time() - s:7.2f}s: {type(e).__name__}: {e}")
        return None
    print(f"  {label:40} {time.time() - s:7.2f}s")
    return out


def main():
    import win32gui
    from pywinauto.uia_element_info import UIAElementInfo

    print("UIAElementInfo.__init__:", inspect.signature(UIAElementInfo.__init__))

    fg = win32gui.GetForegroundWindow()
    print(f"fg hwnd={fg} title={win32gui.GetWindowText(fg)!r}\n")

    el = t("UIAElementInfo(fg) [direct handle]", lambda: UIAElementInfo(fg))
    if el is None:
        return

    from pywinauto.controls.uiawrapper import UIAWrapper

    wrapper = t("UIAWrapper(el)", lambda: UIAWrapper(el))
    if wrapper is None:
        return
    desc = t("wrapper.descendants()", lambda: wrapper.descendants())
    print(f"     -> {len(desc) if desc is not None else 'n/a'} descendants")

    # Compare: pywinauto Desktop scoped to the handle (may still enumerate).
    from pywinauto import Desktop

    d = Desktop(backend="uia")
    spec = t("desktop.window(handle=fg)", lambda: d.window(handle=fg))
    if spec is not None:
        w = t("  spec.descendants()", lambda: spec.descendants())
        print(f"     -> {len(w) if w is not None else 'n/a'} descendants")

    # Sanity: element_info round-trip for text/control_type cost
    if desc:
        first = desc[0]
        t("first.rectangle()+window_text()", lambda: (
            first.rectangle(), first.window_text()))
        t("first.element_info.control_type", lambda: first.element_info.control_type)


if __name__ == "__main__":
    main()
