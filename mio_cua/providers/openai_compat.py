import json

from mio_cua.llm import client
from mio_cua.models.action import ToolCall
from mio_cua.providers.base import Provider, LLMResponse


class OpenAICompatProvider(Provider):
    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def generate(self, messages: list, tools: list = None) -> LLMResponse:
        body = {"model": self.model, "messages": messages, "temperature": 0.2}
        if tools:
            body["tools"] = tools
        resp = client.retrying_post(
            f"{self.base_url}/chat/completions", body,
            timeout=self.timeout, retries=3,
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        data = resp.json()
        msg = data["choices"][0]["message"]
        tool_calls = []
        for tc in msg.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(id=tc["id"], name=tc["function"]["name"], arguments=args))
        return LLMResponse(
            message=msg.get("content") or "",
            tool_calls=tool_calls,
            usage=data.get("usage", {}),
            finish_reason=data["choices"][0].get("finish_reason"),
        )
