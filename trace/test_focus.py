import sys
sys.path.insert(0, r'E:\work\code\agent-dev\desktop-agent')
from mio_cua.automation.windows import focus_window
import ctypes
import win32gui
import sys
sys.stdout.reconfigure(encoding='utf-8')

result = focus_window('WeChat')
print(f'focus_window("WeChat") = {result}')

hwnd = win32gui.GetForegroundWindow()
text = win32gui.GetWindowText(hwnd)
print(f'Foreground window: {text!r}')