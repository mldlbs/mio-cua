"""Cross-process serialization for real desktop input.

MCP clients each spawn their own server process, so several servers must be able
to run at once -- but two processes driving the mouse and keyboard at the same
moment is worse than either failing. The old guard refused the second server
outright, which made every additional client fail to start (a client that
launches one server per session always loses).

Now: any number of servers may exist, and every individual ACTION takes a short
named mutex. Both servers keep serving their clients; only one acts at a time.

Scope note: this serializes single ACTIONS, not whole tasks. Two agents running
long tasks on one desktop will still interleave turns -- each action pair is
atomic, the workflows are not. Task-level coordination is a separate concern.
"""

import contextlib
import os

# One desktop, one input stream. The name is machine-local (Local\ = per
# session); the mutex is held only for the duration of a single action.
ACTION_MUTEX = "Local\\mio-cua-desktop-input"
DEFAULT_TIMEOUT_MS = 30_000


@contextlib.contextmanager
def desktop_action_lock(timeout_ms: int = DEFAULT_TIMEOUT_MS):
    """Hold the cross-process desktop-input mutex for one action.

    Yields True when the lock was acquired and False on timeout; callers must
    treat False as "desktop busy, do not act". On non-Windows platforms there is
    no mutex and it yields True.
    """
    if os.name != "nt":
        yield True
        return

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.ReleaseMutex.restype = wintypes.BOOL
    kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    handle = kernel32.CreateMutexW(None, False, ACTION_MUTEX)
    if not handle:  # no mutex available: behave as "no guard"
        yield True
        return

    WAIT_OBJECT_0 = 0x00000000
    acquired = kernel32.WaitForSingleObject(handle, int(timeout_ms)) == WAIT_OBJECT_0
    try:
        yield acquired
    finally:
        if acquired:
            kernel32.ReleaseMutex(handle)
        kernel32.CloseHandle(handle)
