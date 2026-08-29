import sys
sys.path.insert(0, r'E:\work\code\agent-dev\desktop-agent')
from mio_cua.automation.windows import _ALIASES, _windows_matching_process
from pywinauto import Desktop
import sys
sys.stdout.reconfigure(encoding='utf-8')

title = 'WeChat'
alias = _ALIASES.get(title.lower())
print(f'alias: {alias}')

# Test process match
print('Testing _windows_matching_process:')
for hwnd in _windows_matching_process((alias.lower().replace(".exe", ""),)):
    import win32gui
    print(f'  hwnd={hwnd} title={win32gui.GetWindowText(hwnd)!r}')

# Test UIA enumeration
print('\nTesting UIA enumeration:')
for w in Desktop(backend="uia").windows():
    try:
        text = w.window_text()
        if text and alias.lower() in text.lower():
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