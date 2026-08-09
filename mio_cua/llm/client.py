import time

import requests


def retrying_post(url: str, json_body: dict, timeout: float = 60, retries: int = 3,
                  headers: dict = None) -> requests.Response:
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
