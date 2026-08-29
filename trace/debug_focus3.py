import sys
sys.path.insert(0, r'E:\work\code\agent-dev\desktop-agent')
from mio_cua.automation.windows import focus_window as fw, _windows_matching_process
from pywinauto import Desktop
import sys
sys.stdout.reconfigure(encoding='utf-8')

# Test the process matching logic directly
print('Testing _windows_matching_process for "weixin":')
for hwnd in _windows_matching_process(('weixin',)):
    import win32gui
    print(f'  hwnd={hwnd} title={win32gui.GetWindowText(hwnd)!r} visible={win32gui.IsWindowVisible(hwnd)}')

# Test UIA enumeration with "weixin" in title
print('\nTesting UIA enumeration with "weixin" in title:')
for w in Desktop(backend="uia").windows():
    try:
        text = w.window_text()
        if text and 'weixin' in text.lower():
            print(f'  Found: handle={w.handle} title={text!r}')
            print(f'  Calling set_focus()...')
            w.set_focus()
            import time
            time.sleep(0.2)
            import win32gui
            fg = win32gui.GetForegroundWindow()
            print(f'  Foreground: {fg} title={win32gui.GetWindowText(fg)!r}')
            break
    except Exception as e:
        print(f'Error: {e}')
        continue

# Test full focus_window function
print('\nTesting full focus_window("WeChat"):')
from mio_cua.automation.windows import focus_window as fw
result = fw('WeChat')
print(f'fw("WeChat") returned: {result}')

time.sleep(1)
import win32gui
fg = win32gui.GetForegroundWindow()
print(f'After focus: hwnd={fg} title={win32gui.GetWindowText(fg)!r}')