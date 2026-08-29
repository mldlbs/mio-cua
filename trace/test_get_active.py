"""Test get_active_window encoding."""
import ctypes
import ctypes.wintypes as wt

user32 = ctypes.windll.user32
user32.GetForegroundWindow.restype = wt.HWND
user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextLengthW.argtypes = [wt.HWND]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]

hwnd = user32.GetForegroundWindow()
print(f"hwnd: {hwnd}")

length = user32.GetWindowTextLengthW(hwnd)
print(f"length: {length}")

buf = ctypes.create_unicode_buffer(length + 1)
result = user32.GetWindowTextW(hwnd, buf, length + 1)
print(f"result: {result}")
print(f"buf.value: {buf.value!r}")
print(f"buf.value length: {len(buf.value)}")