"""Deterministic clock for tool timestamps.

Gold-action DB-hash matching requires created/updated timestamps to be reproducible: the gold
replay and the agent run must stamp identical times. Tools therefore read the current time via
``get_now()`` (never ``datetime.now()`` directly). The environment sets a fixed per-task time;
by default it is a stable constant so behaviour is deterministic even outside a task run.
"""

from __future__ import annotations

import threading

#: Default frozen time used when no task time has been set (ISO 8601, microseconds).
DEFAULT_NOW = "2024-06-01T00:00:00"

_state = threading.local()


def set_now(iso_timestamp: str) -> None:
    """Freeze ``get_now()`` to ``iso_timestamp`` for the current thread."""
    _state.now = iso_timestamp


def reset_now() -> None:
    """Restore the default frozen time."""
    _state.now = DEFAULT_NOW


def get_now() -> str:
    """Return the current (frozen) timestamp as an ISO 8601 string."""
    return getattr(_state, "now", DEFAULT_NOW)
