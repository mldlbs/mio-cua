"""Windows 11 virtual desktop helpers via shell shortcuts (Win+Ctrl+...).

Create/switch to a dedicated virtual desktop so mio-cua automation runs
isolated from the user's main desktop. After the run, close the desktop and
return to the previous one.

Functions:
    python vdesk.py new        create a new desktop and switch to it
    python vdesk.py num <n>    switch to desktop number n (1-based)
    python vdesk.py left       switch to previous desktop
    python vdesk.py right      switch to next desktop
    python vdesk.py close      close the current desktop
"""
import sys
import time

import win32api
import win32con

_WIN = 0x5B
_CTRL = 0x11


def _tap(key):
    win32api.keybd_event(key, 0, 0, 0)
    win32api.keybd_event(key, 0, win32con.KEYEVENTF_KEYUP, 0)


def _combo(letter_vk):
    win32api.keybd_event(_WIN, 0, 0, 0)
    win32api.keybd_event(_CTRL, 0, 0, 0)
    win32api.keybd_event(letter_vk, 0, 0, 0)
    win32api.keybd_event(letter_vk, 0, win32con.KEYEVENTF_KEYUP, 0)
    win32api.keybd_event(_CTRL, 0, win32con.KEYEVENTF_KEYUP, 0)
    win32api.keybd_event(_WIN, 0, win32con.KEYEVENTF_KEYUP, 0)


def _vk(ch):
    return win32api.VkKeyScan(ch) & 0xFF


_VK_F4 = 0x73
_VK_LEFT = 0x25
_VK_RIGHT = 0x27
_VK_ESC = 0x1B
_VK_RETURN = 0x0D


def new_desktop():
    """Win+Ctrl+D creates a new desktop, but lands on the Task View chooser.
    Press Esc to dismiss it and actually drop onto the fresh desktop."""
    _combo(_vk("D"))
    time.sleep(1.5)
    _tap(_VK_ESC)
    time.sleep(1.5)


def ensure_test_desktop():
    """Reuse a dedicated test desktop instead of opening a new one each run.

    We reserve desktop #2 as the test desktop. If it exists, Win+Ctrl+2 moves
    us onto it (foreground changes). If it does not exist, the switch is a
    no-op -- then we create it once. Either way only ONE test desktop ever
    exists, so they do not pile up.
    """
    fg_before = _fg_title()
    switch_to(2)
    time.sleep(0.8)
    fg_after = _fg_title()
    if fg_after == fg_before and fg_before:
        # desktop #2 did not exist (switch was a no-op): create it once.
        new_desktop()
        switch_to(2)
        time.sleep(0.8)


def _fg_title():
    import win32gui
    return win32gui.GetWindowText(win32gui.GetForegroundWindow())


def close_desktop():
    _combo(_VK_F4)
    time.sleep(1.5)


def switch_left():
    win32api.keybd_event(_WIN, 0, 0, 0)
    win32api.keybd_event(_CTRL, 0, 0, 0)
    win32api.keybd_event(_VK_LEFT, 0, 0, 0)
    win32api.keybd_event(_VK_LEFT, 0, win32con.KEYEVENTF_KEYUP, 0)
    win32api.keybd_event(_CTRL, 0, win32con.KEYEVENTF_KEYUP, 0)
    win32api.keybd_event(_WIN, 0, win32con.KEYEVENTF_KEYUP, 0)
    time.sleep(1.0)


def switch_right():
    win32api.keybd_event(_WIN, 0, 0, 0)
    win32api.keybd_event(_CTRL, 0, 0, 0)
    win32api.keybd_event(_VK_RIGHT, 0, 0, 0)
    win32api.keybd_event(_VK_RIGHT, 0, win32con.KEYEVENTF_KEYUP, 0)
    win32api.keybd_event(_CTRL, 0, win32con.KEYEVENTF_KEYUP, 0)
    win32api.keybd_event(_WIN, 0, win32con.KEYEVENTF_KEYUP, 0)
    time.sleep(1.0)


def switch_to(n):
    _combo(ord(str(n)))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "new"
    if cmd == "new":
        new_desktop()
    elif cmd == "ensure":
        ensure_test_desktop()
    elif cmd == "close":
        close_desktop()
    elif cmd == "left":
        switch_left()
    elif cmd == "right":
        switch_right()
    elif cmd == "num":
        switch_to(int(sys.argv[2]))
    else:
        print(f"unknown command: {cmd}")
        return 1
    print(f"vdesk: {cmd} done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
