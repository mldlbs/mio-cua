"""Cross-process desktop-input serialization (replaces the hard singleton)."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mio_cua.automation.desktop_lock import ACTION_MUTEX, desktop_action_lock  # noqa: E402


def test_action_lock_acquires_and_releases():
    with desktop_action_lock() as acquired:
        assert acquired is True
    # A second action right after must acquire again (no leaked ownership).
    with desktop_action_lock() as acquired_again:
        assert acquired_again is True


def test_action_lock_is_exclusive_across_threads():
    """Threads in one process contend like processes do: the second waits."""
    import threading
    import time

    order = []

    def worker(name, hold_s):
        with desktop_action_lock() as acquired:
            assert acquired is True
            order.append((name, "in"))
            time.sleep(hold_s)
            order.append((name, "out"))

    t1 = threading.Thread(target=worker, args=("a", 0.3))
    t1.start()
    time.sleep(0.05)
    t2 = threading.Thread(target=worker, args=("b", 0.05))
    t2.start()
    t1.join()
    t2.join()

    # b must not enter before a leaves
    assert order.index(("a", "out")) < order.index(("b", "in"))


def test_mutex_name_is_machine_local():
    assert ACTION_MUTEX.startswith("Local\\")
