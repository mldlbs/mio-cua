import pytest
from mio_cua.llm.client import retrying_post


class FakeResp:
    def __init__(self, ok, text=""):
        self.ok = ok
        self.text = text

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(self.text)


def test_retrying_post_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def fake_post(url, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise TimeoutError("boom")
        return FakeResp(ok=True)

    monkeypatch.setattr("mio_cua.llm.client.requests.post", fake_post)
    resp = retrying_post("http://x", {}, timeout=1, retries=3)
    assert calls["n"] == 3
    assert resp.ok


def test_retrying_post_gives_up(monkeypatch):
    def fake_post(url, **kwargs):
        raise TimeoutError("boom")

    monkeypatch.setattr("mio_cua.llm.client.requests.post", fake_post)
    with pytest.raises(TimeoutError):
        retrying_post("http://x", {}, timeout=1, retries=2)


def test_retrying_post_does_not_retry_4xx(monkeypatch):
    import requests

    class FakeError(requests.HTTPError):
        def __init__(self):
            super().__init__("bad request")
            self.response = type("R", (), {"status_code": 400})()

    calls = {"n": 0}

    def fake_post(url, **kwargs):
        calls["n"] += 1
        raise FakeError()

    monkeypatch.setattr("mio_cua.llm.client.requests.post", fake_post)
    with pytest.raises(requests.HTTPError):
        retrying_post("http://x", {}, timeout=1, retries=3)
    assert calls["n"] == 1


def _http_error(status, headers=None):
    import requests

    resp = type("R", (), {"status_code": status, "headers": headers or {}})()

    class FakeError(requests.HTTPError):
        def __init__(self):
            super().__init__(f"http {status}")
            self.response = resp

    return FakeError()


def test_retrying_post_retries_503(monkeypatch):
    """A shared proxy answering 503 for a moment must not kill the task."""
    import requests

    calls = {"n": 0}

    def fake_post(url, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise _http_error(503)
        return FakeResp(ok=True)

    slept = []
    monkeypatch.setattr("mio_cua.llm.client.requests.post", fake_post)
    monkeypatch.setattr("mio_cua.llm.client.time.sleep", lambda s: slept.append(s))

    resp = retrying_post("http://x", {}, timeout=1, retries=4, backoff_s=0.1)

    assert resp.ok
    assert calls["n"] == 3
    assert slept == [0.1, 0.2]


def test_retrying_post_honours_retry_after(monkeypatch):
    calls = {"n": 0}

    def fake_post(url, **kwargs):
        calls["n"] += 1
        if calls["n"] < 2:
            raise _http_error(429, {"Retry-After": "7"})
        return FakeResp(ok=True)

    slept = []
    monkeypatch.setattr("mio_cua.llm.client.requests.post", fake_post)
    monkeypatch.setattr("mio_cua.llm.client.time.sleep", lambda s: slept.append(s))

    retrying_post("http://x", {}, timeout=1, retries=3, backoff_s=0.1)

    assert slept == [7.0], "Retry-After must win over exponential backoff"


def test_retrying_post_backoff_is_capped(monkeypatch):
    def fake_post(url, **kwargs):
        raise _http_error(503)

    slept = []
    monkeypatch.setattr("mio_cua.llm.client.requests.post", fake_post)
    monkeypatch.setattr("mio_cua.llm.client.time.sleep", lambda s: slept.append(s))

    with pytest.raises(Exception):
        retrying_post("http://x", {}, timeout=1, retries=6, backoff_s=1.0, backoff_max_s=4.0)

    assert slept == [1.0, 2.0, 4.0, 4.0, 4.0]
