from mio_cua.automation.backends import Backend
from mio_cua.automation.backends import _key_combo, _VK
from mio_cua.models.action import Action
from mio_cua.models.action_result import RawResult


class FakeWin32Api:
    def __init__(self):
        self.events = []

    def keybd_event(self, vk, scan, flags, extra):
        self.events.append((vk, flags))

    def VkKeyScan(self, ch):
        if ch == "A":
            return 0x41 | 0x0100  # requires shift
        return ord(ch)


class FakeWin32Con:
    KEYEVENTF_KEYUP = 2


def test_key_combo_lowercase_no_shift():
    api, con = FakeWin32Api(), FakeWin32Con()
    _key_combo(api, con, ["a"])
    # no shift in events
    assert 0x10 not in [vk for vk, _ in api.events]


def test_key_combo_uppercase_adds_shift():
    api, con = FakeWin32Api(), FakeWin32Con()
    _key_combo(api, con, ["A"])
    vks = [vk for vk, _ in api.events]
    assert 0x10 in vks  # shift present
    assert 0x41 in vks  # A present


def test_key_combo_named_key():
    api, con = FakeWin32Api(), FakeWin32Con()
    _key_combo(api, con, ["backspace"])
    vks = [vk for vk, _ in api.events]
    assert _VK["backspace"] in vks


def test_key_combo_unknown_raises():
    api, con = FakeWin32Api(), FakeWin32Con()
    try:
        _key_combo(api, con, ["definitely-not-a-key"])
        assert False, "should raise"
    except RuntimeError:
        pass


class RecordingBackend(Backend):
    def __init__(self):
        self.calls = []

    def execute(self, action: Action) -> RawResult:
        self.calls.append(action)
        return RawResult(sent=True)


def test_backend_contract():
    b = RecordingBackend()
    r = b.execute(Action(id="a-1", type="click", params={"x": 10, "y": 20}))
    assert r.sent is True
    assert b.calls[0].type == "click"


def test_backend_error_result():
    class FailingBackend(Backend):
        def execute(self, action):
            return RawResult(sent=False, error="boom")

    r = FailingBackend().execute(Action(id="a", type="click"))
    assert r.sent is False
    assert r.error == "boom"
