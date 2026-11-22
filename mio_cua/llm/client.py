import time

import requests


def _retry_after_seconds(resp) -> float:
    """Honour ``Retry-After`` when the endpoint tells us how long to wait.

    Shared/rate-limited proxies (429) and overloaded upstreams (503) usually
    include it; ignoring it is what turns one hiccup into a dead run.
    """
    try:
        raw = (resp.headers or {}).get("Retry-After")
    except Exception:
        return 0.0
    if not raw:
        return 0.0
    try:
        return max(0.0, float(str(raw).strip()))
    except ValueError:
        return 0.0


def retrying_post(url: str, json_body: dict, timeout: float = 60, retries: int = 4,
                  headers: dict = None, backoff_s: float = 0.5,
                  backoff_max_s: float = 30.0) -> requests.Response:
    # Exponential backoff, not a fixed 3.5s budget: this machine's route to the
    # LLM endpoint is flaky (TLS handshakes, RST 10054) and shared proxies answer
    # 429/503 for seconds at a time. Callers expose the knobs through config
    # (``llm_attempts`` / ``llm_backoff_s`` / ``llm_backoff_max_s``).
    last_err = None
    for attempt in range(retries):
        try:
            resp = requests.post(url, json=json_body, timeout=timeout, headers=headers or {})
            resp.raise_for_status()
            return resp
        except requests.HTTPError as e:
            status = getattr(getattr(e, "response", None), "status_code", 0) or 0
            if 400 <= status < 500 and status != 429:
                raise
            last_err = e
            wait = _retry_after_seconds(getattr(e, "response", None))
        except (requests.ConnectionError, requests.Timeout, TimeoutError) as e:
            last_err = e
            wait = 0.0
        if attempt == retries - 1:
            break
        if wait <= 0:
            wait = min(backoff_max_s, backoff_s * (2 ** attempt))
        time.sleep(wait)
    raise last_err
