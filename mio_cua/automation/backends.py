from abc import ABC, abstractmethod

from mio_cua.models.action import Action
from mio_cua.models.action_result import RawResult


class Backend(ABC):
    @abstractmethod
    def execute(self, action: Action) -> RawResult:
        raise NotImplementedError


class SendInputBackend(Backend):
    """Real Windows input via win32 SendInput-equivalent calls (default)."""

    def execute(self, action: Action) -> RawResult:
        try:
            _dispatch(action)
            return RawResult(sent=True)
        except Exception as e:
            return RawResult(sent=False, error=str(e))


class PyAutoGUIBackend(Backend):
    """Debug/mock backend using pyautogui."""

    def execute(self, action: Action) -> RawResult:
        try:
            _dispatch_pyautogui(action)
            return RawResult(sent=True)
        except Exception as e:
            return RawResult(sent=False, error=str(e))


def _center(bbox):
    left, top, width, height = bbox
    return left + width // 2, top + height // 2


def _dispatch(action: Action):
    import win32api
    import win32con
    import win32clipboard

    params = action.params
    typ = action.type

    if typ in ("click", "move_mouse"):
        if "element_id" in params:
            raise RuntimeError("element_id must be resolved to bbox before backend call")
        x, y = params["x"], params["y"]
        win32api.SetCursorPos((int(x), int(y)))
        if typ == "move_mouse":
            return
        button = params.get("button", "left")
        down, up = win32con.MOUSEEVENTF_LEFTDOWN, win32con.MOUSEEVENTF_LEFTUP
        if button == "right":
            down, up = win32con.MOUSEEVENTF_RIGHTDOWN, win32con.MOUSEEVENTF_RIGHTUP
        rounds = 2 if params.get("double") else 1
        for _ in range(rounds):
            win32api.mouse_event(down, 0, 0, 0, 0)
            win32api.mouse_event(up, 0, 0, 0, 0)

    elif typ == "type":
        if "element_id" in params:
            raise RuntimeError("element_id must be resolved to bbox before backend call")
        try:
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(str(params["text"]), win32clipboard.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
        _key_combo(win32api, win32con, ["ctrl", "v"])

    elif typ == "key":
        _key_combo(win32api, win32con, _parse_keys(params["keys"]))

    elif typ == "scroll":
        amount = params.get("amount", 1)
        direction = params.get("direction", "down")
        delta = -120 * amount if direction == "down" else 120 * amount
        win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, delta, 0)

    elif typ == "drag":
        x1, y1 = params["x1"], params["y1"]
        x2, y2 = params["x2"], params["y2"]
        win32api.SetCursorPos((int(x1), int(y1)))
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        # smooth drag so the OS registers an actual move-drag gesture
        steps = 20
        for i in range(1, steps + 1):
            mx = int(x1 + (x2 - x1) * i / steps)
            my = int(y1 + (y2 - y1) * i / steps)
            win32api.SetCursorPos((mx, my))
            win32api.Sleep(8)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    else:
        raise RuntimeError(f"unsupported action type: {typ}")


_VK = {
    "ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12, "menu": 0x12,
    "win": 0x5B, "lwin": 0x5B, "enter": 0x0D, "return": 0x0D, "tab": 0x09,
    "esc": 0x1B, "escape": 0x1B, "space": 0x20, "backspace": 0x08, "delete": 0x2E,
    "del": 0x2E, "home": 0x24, "end": 0x23, "insert": 0x2D, "up": 0x26,
    "down": 0x28, "left": 0x25, "right": 0x27, "pageup": 0x21, "pgup": 0x21,
    "pagedown": 0x22, "pgdn": 0x22, "capslock": 0x14, "f1": 0x70, "f2": 0x71,
    "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75, "f7": 0x76, "f8": 0x77,
    "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
}


def _parse_keys(keys: str) -> list:
    """Split a key combo spec into parts, keeping a lone `+` as the literal plus.

    ``"ctrl+s"`` -> ``["ctrl", "s"]``; ``"+"`` (the plus character, as typed in
    a calculator) must NOT be split into empty parts.
    """
    s = (keys or "").strip()
    if not s:
        return []
    if s == "+":
        return ["+"]
    return [k.strip() for k in s.split("+") if k.strip()]


def _key_combo(win32api, win32con, keys: list):
    mods = [_VK[k.strip().lower()] for k in keys[:-1] if k.strip().lower() in _VK]
    main = keys[-1].strip()
    main_lower = main.lower()
    shift_needed = False

    if main_lower in _VK:
        main_vk = _VK[main_lower]
    elif len(main) == 1:
        try:
            scan = win32api.VkKeyScan(main)
            main_vk = scan & 0xFF
            shift_needed = (scan & 0x0100) != 0
        except Exception:
            raise RuntimeError(f"unsupported key: {main}")
    else:
        raise RuntimeError(f"unsupported key: {main}")

    if shift_needed and "shift" not in [m.strip().lower() for m in keys[:-1]]:
        mods.append(_VK["shift"])

    for m in mods:
        win32api.keybd_event(m, 0, 0, 0)
    win32api.keybd_event(main_vk, 0, 0, 0)
    win32api.keybd_event(main_vk, 0, win32con.KEYEVENTF_KEYUP, 0)
    for m in mods:
        win32api.keybd_event(m, 0, win32con.KEYEVENTF_KEYUP, 0)


def _dispatch_pyautogui(action: Action):
    import pyautogui

    params = action.params
    typ = action.type
    if typ == "click":
        pyautogui.click(params["x"], params["y"], button=params.get("button", "left"), clicks=2 if params.get("double") else 1)
    elif typ == "move_mouse":
        pyautogui.moveTo(params["x"], params["y"])
    elif typ == "type":
        pyautogui.typewrite(str(params["text"]))
    elif typ == "key":
        pyautogui.hotkey(*[k.strip() for k in params["keys"].split("+")])
    elif typ == "scroll":
        amount = params.get("amount", 1)
        direction = params.get("direction", "down")
        delta = -amount if direction == "down" else amount
        pyautogui.scroll(delta)
    elif typ == "drag":
        pyautogui.moveTo(params["x1"], params["y1"])
        pyautogui.mouseDown()
        pyautogui.moveTo(params["x2"], params["y2"], duration=0.2)
        pyautogui.mouseUp()
    else:
        raise RuntimeError(f"unsupported action type: {typ}")
