import re
import subprocess
import time

from mio_cua.automation.windows import bring_to_front, bring_file_to_front, _process_base
from mio_cua.models.action_result import ActionResult

# Apps that allow (and often need) multiple independent windows: a bare
# `launch notepad` should open a fresh window, not reuse one showing an old
# file, otherwise a "new blank document" task silently targets stale content.
_MULTI_INSTANCE_APPS = {"notepad"}

# Browsers are often not on PATH (Edge/Chrome install under Program Files);
# `launch msedge <url>` then fails with "not recognized". Resolve the command
# to a known install path before Popen.
_BROWSER_PATHS = {
    "msedge": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "edge": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
}

# A bare domain like `chat.deepseek.com` (no scheme, no browser prefix) must be
# treated as a URL to open in the browser, not a program to run.
_BARE_HOST_RE = re.compile(
    r"^(?:www\.)?[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?:/[^\s]*)?$"
)


def _resolve_command(command: str) -> str:
    """Replace a browser command token with its full install path if needed."""
    tokens = command.split()
    if not tokens:
        return command
    base = tokens[0].strip('"')
    resolved = _BROWSER_PATHS.get(base.lower())
    if resolved and base.lower() in _BROWSER_PATHS:
        return ' '.join([f'"{resolved}"'] + tokens[1:])
    return command


def _resolve_url(command: str) -> str:
    """Turn a bare domain (``chat.deepseek.com``) into a browser launch.

    The model often emits a URL without a scheme and without a browser prefix.
    ``Popen("chat.deepseek.com")`` would then fail with "not recognized" on
    Windows. Detect a single bare-domain token and route it through Edge.
    """
    if not command or not command.strip():
        return command
    token = command.strip()
    if (
        " " not in token
        and "://" not in token
        and "\\" not in token
        and _BARE_HOST_RE.match(token)
    ):
        return f"msedge https://{token}"
    return command


def _normalize_path(token: str) -> str:
    """Collapse run-away backslashes from LLM JSON escaping (``D:\\\\U`` -> ``D:\\U``).

    The model emits commands as JSON strings, so a Windows path like
    ``D:\\Users\\...`` can arrive double- (or quadruple-) escaped. ``cmd /c``
    would then look for a non-existent file. Collapse any run of 2+ backslashes
    (that is not a leading UNC ``\\\\``) into a single one.
    """
    if re.match(r"^\\\\", token):  # UNC path, keep
        return token
    return re.sub(r"\\{2,}", r"\\", token)


def _normalize_command(command: str) -> str:
    tokens = command.split()
    if len(tokens) <= 1:
        return command
    tokens[-1] = _normalize_path(tokens[-1])
    return " ".join(tokens)


def _wait_for_front(command, tries=6, delay=1.0):
    """Bring `command`'s window to front, retrying until it appears.

    A freshly launched app may take >1.5s to show its first window; a single
    best-effort focus attempt then fails and the window never reaches the
    foreground of the current virtual desktop. Poll instead.
    """
    for _ in range(tries):
        if bring_to_front(command):
            return True
        time.sleep(delay)
    return bring_to_front(command)


def launch(ctx, command):
    try:
        command = _resolve_command(_normalize_command(_resolve_url(command)))
        tokens = command.split()
        plain_app = len(tokens) == 1
        if plain_app and _process_base(tokens[0]) in _MULTI_INSTANCE_APPS:
            # e.g. `launch notepad`: open a fresh window (multi-instance app);
            # reuse would silently target a window already showing old data.
            proc = subprocess.Popen(command, shell=True)
            time.sleep(1.5)
            brought = _wait_for_front(command)
            message = f"launched {command}"
            if not brought:
                message += " (could not focus window)"
            return ActionResult(ctx.current_action_id, True, message)
        if plain_app:
            brought = bring_to_front(command)
            if brought:
                return ActionResult(
                    ctx.current_action_id,
                    True,
                    f"reused already-running {command} window",
                )
        else:
            # command like `notepad D:\...\file.txt`: reuse an existing window
            # that already has this file open, else open fresh.
            hint = tokens[-1]
            if bring_file_to_front(hint):
                return ActionResult(
                    ctx.current_action_id,
                    True,
                    f"reused existing window already showing {hint}",
                )
        proc = subprocess.Popen(command, shell=True)
        time.sleep(1.5)
        brought = _wait_for_front(command)
        message = f"launched {command}"
        if not brought:
            message += " (could not focus window)"
        return ActionResult(ctx.current_action_id, True, message)
    except Exception as e:
        return ActionResult(ctx.current_action_id, False, str(e), retryable=True)
