"""Verify single-instance guard: two processes, only one may acquire."""
import subprocess
import sys
import time

PY = r"C:\d\venvs\mio-gpu\Scripts\python.exe"
HOLDER = r"""
import sys, time
sys.path.insert(0, r"E:\work\code\agent-dev\desktop-agent")
from mio_cua import mcp_server
ok = mcp_server._acquire_single_instance()
print(f"HOLDER acquired={ok}", flush=True)
time.sleep(8)
"""
SECOND = r"""
import sys
sys.path.insert(0, r"E:\work\code\agent-dev\desktop-agent")
from mio_cua import mcp_server
ok = mcp_server._acquire_single_instance()
print(f"SECOND acquired={ok}", flush=True)
"""

p1 = subprocess.Popen([PY, "-c", HOLDER], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
time.sleep(3)  # let holder acquire

p2 = subprocess.run([PY, "-c", SECOND], capture_output=True, text=True, timeout=30)
print("second stdout:", p2.stdout.strip())

p1.wait(timeout=30)
screen1 = p1.stdout.read()
print("holder stdout:", screen1.strip(), "exit=", p1.returncode)

assert "acquired=True" in screen1, "holder should acquire"
assert "acquired=False" in p2.stdout, "second process must be rejected"
print("PASS: single-instance guard works")