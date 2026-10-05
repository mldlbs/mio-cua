import sys
sys.path.insert(0, r'E:\work\code\agent-dev\desktop-agent')
from mio_cua.automation.windows import focus_window as fw, get_active_window
from pywinauto import Desktop
import win32gui
import time
import sys
sys.stdout.reconfigure(encoding='utf-8')

# Find and focus OpenCode
for w in Desktop(backend='uia').windows():
    if 'OpenCode' in w.window_text():
        w.set_focus()
        break

time.sleep(0.5)
print(f'After OpenCode focus: {get_active_window()!r}')

# Now test WeChat focus
result = fw('WeChat')
print(f'fw returned: {result}')

time.sleep(1)
print(f'After WeChat focus: {get_active_window()!r}')