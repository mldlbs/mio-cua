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
