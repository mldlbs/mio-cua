import json
from mio_cua.providers.base import Provider, LLMResponse
from mio_cua.providers.openai_compat import OpenAICompatProvider
from mio_cua.models.action import ToolCall


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _payload(content, tool_calls, finish="stop"):
    return {
        "choices": [{
            "message": {"role": "assistant", "content": content, "tool_calls": tool_calls},
            "finish_reason": finish,
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def test_llm_response_fields():
    r = LLMResponse(message="hi", tool_calls=[], usage={"total_tokens": 5}, finish_reason="stop")
    assert r.finish_reason == "stop"
    assert r.usage["total_tokens"] == 5


def test_provider_base_raises():
    try:
        Provider().generate([], None)
        assert False, "should raise"
    except NotImplementedError:
        pass


def test_openai_compat_parses_tool_calls(monkeypatch):
    tc = {"id": "t1", "type": "function", "function": {"name": "click", "arguments": json.dumps({"element_id": 3})}}
    resp = FakeResponse(_payload("", [tc]))
    monkeypatch.setattr("mio_cua.llm.client.retrying_post", lambda url, json_body, timeout, retries, headers=None: resp)

    p = OpenAICompatProvider("http://x/v1", "key", "gpt-4o")
    out = p.generate([{"role": "user", "content": "go"}], tools=[{"type": "function", "function": {}}])
    assert len(out.tool_calls) == 1
    assert isinstance(out.tool_calls[0], ToolCall)
    assert out.tool_calls[0].name == "click"
    assert out.tool_calls[0].arguments == {"element_id": 3}


def test_openai_compat_sends_auth_header(monkeypatch):
    captured = {}

    def fake_post(url, json_body, timeout, retries, headers):
        captured["url"] = url
        captured["headers"] = headers
        return FakeResponse(_payload("", []))

    monkeypatch.setattr("mio_cua.llm.client.retrying_post", fake_post)
    p = OpenAICompatProvider("http://x/v1", "secret-key", "gpt-4o")
    p.generate([{"role": "user", "content": "go"}])
    assert captured["url"] == "http://x/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer secret-key"
