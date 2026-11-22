"""Build the LLM provider from an ``AgentConfig``.

Kept in one place so every entry point (CLI, agent factory, evaluation trace
runner) picks up the same retry/timeout policy: a shared proxy that answers
429/503 for a few seconds must not kill a whole task.
"""

from mio_cua.config import AgentConfig


def provider_from_config(config: AgentConfig):
    # Import the module (not the name) so tests that monkeypatch
    # ``mio_cua.providers.openai_compat.OpenAICompatProvider`` keep working.
    from mio_cua.providers import openai_compat

    return openai_compat.OpenAICompatProvider(
        base_url=config.base_url,
        api_key=config.api_key(),
        model=config.model,
        timeout=getattr(config, "llm_timeout_s", 180),
        attempts=getattr(config, "llm_attempts", 4),
        backoff_s=getattr(config, "llm_backoff_s", 0.5),
        backoff_max_s=getattr(config, "llm_backoff_max_s", 30.0),
    )
