import logging
import threading
import time

logger = logging.getLogger(__name__)


class Safety:
    def __init__(self, max_steps: int, timeout_s: float, emergency_key: str = "f9",
                 hotkey_enabled: bool = True):
        self.max_steps = max_steps
        self.timeout_s = timeout_s
        self.emergency_key = emergency_key
        self.hotkey_enabled = hotkey_enabled
        self.step_count = 0
        self._stopped = False
        self._started_at = time.time()
        self._listener = None
        self.listener_active = False
        if hotkey_enabled:
            self.start_listener()

    def start(self):
        if self.hotkey_enabled and not self.listener_active:
            self.start_listener()

    def start_listener(self):
        try:
            from pynput import keyboard

            def on_press(key):
                name = getattr(key, "name", None)
                char = getattr(key, "char", None)
                if name == self.emergency_key or char == self.emergency_key:
                    self._stopped = True

            self._listener = keyboard.Listener(on_press=on_press)
            self._listener.daemon = True
            self._listener.start()
            self.listener_active = True
        except Exception as e:
            logger.warning("Emergency stop hotkey (%s) unavailable: %s", self.emergency_key, e)

    def stop(self):
        self._stopped = True
        if self._listener is not None:
            self._listener.stop()

    def record_step(self):
        self.step_count += 1

    def should_stop(self) -> bool:
        if self._stopped:
            return True
        if self.step_count >= self.max_steps:
            return True
        if time.time() - self._started_at > self.timeout_s:
            return True
        return False

    def status(self) -> str:
        if self._stopped:
            return "ABORTED"
        if self.step_count >= self.max_steps:
            return "ABORTED"
        if time.time() - self._started_at > self.timeout_s:
            return "TIMEOUT"
        return "RUNNING"
