import time

import requests


def retrying_post(url: str, json_body: dict, timeout: float = 60, retries: int = 4,
                  headers: dict = None) -> requests.Response:
    # 4 attempts with exponential backoff: this machine's route to the LLM
    # endpoint is flaky (observed TLS handshake timeouts and RST 10054 within
    # a single session), and 3 attempts were not enough to ride it out.
    last_err = None
    for attempt in range(retries):
        try:
            resp = requests.post(url, json=json_body, timeout=timeout, headers=headers or {})
            resp.raise_for_status()
            return resp
        except requests.HTTPError as e:
            if 400 <= e.response.status_code < 500 and e.response.status_code != 429:
                raise
            last_err = e
        except (requests.ConnectionError, requests.Timeout, TimeoutError) as e:
            last_err = e
        if attempt == retries - 1:
            break
        time.sleep(0.5 * (2 ** attempt))
    raise last_err
