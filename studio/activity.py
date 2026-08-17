"""Process-wide activity/token feed + background action registry for the dashboard."""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

ACTIVITY: dict[str, dict[str, Any]] = {}

# Long-running pipeline actions: key -> {"state", "detail", "done", "total"}
ACTIONS: dict[str, dict[str, Any]] = {}
_ACTIONS_LOCK = threading.Lock()

# Push listeners: called whenever ACTIVITY/ACTIONS change so the dashboard can
# SSE-notify connected clients instead of the client polling.
_listeners: set = set()
_LISTENERS_LOCK = threading.Lock()


def subscribe(fn) -> None:
    with _LISTENERS_LOCK:
        _listeners.add(fn)


def unsubscribe(fn) -> None:
    with _LISTENERS_LOCK:
        _listeners.discard(fn)


def _notify() -> None:
    with _LISTENERS_LOCK:
        fns = list(_listeners)
    for fn in fns:
        try:
            fn()
        except Exception:
            pass


def report(key: str, detail: str, output: str = "") -> None:
    entry = {"detail": detail, "ts": time.time()}
    if output:
        entry["output"] = output[-600:]
    ACTIVITY[key] = entry
    _notify()


def report_progress(key: str, detail: str, n: int, text: str) -> None:
    entry = {"detail": f"{detail} ({n} tokens…)", "output": text[-600:], "ts": time.time()}
    ACTIVITY[key] = entry
    _notify()


def action_status(key: str) -> dict[str, Any]:
    with _ACTIONS_LOCK:
        return dict(ACTIONS.get(key, {"state": "idle", "detail": "", "done": 0, "total": 0}))


def start_action(key: str, fn: Callable[[], Any]) -> None:
    """Run ``fn`` in a background thread, tracking state under ``key``."""
    with _ACTIONS_LOCK:
        ACTIONS[key] = {"state": "running", "detail": "Starting…", "done": 0, "total": 0}

    def _run():
        try:
            ACTIONS[key]["detail"] = "Running…"
            result = fn()
            with _ACTIONS_LOCK:
                ACTIONS[key].update({"state": "done", "detail": str(result or "Done")})
        except Exception as exc:
            with _ACTIONS_LOCK:
                ACTIONS[key].update({"state": "failed", "detail": str(exc)})
        finally:
            report(key, ACTIONS[key]["detail"])

    _notify()
    threading.Thread(target=_run, daemon=True).start()
