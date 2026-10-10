"""A small thread-safe time-based cache."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Callable, TypeVar

T = TypeVar("T")


class TTLCache:
    """Remembers loader results for `ttl` seconds, keeping at most `max_entries`.

    Errors propagate and are not cached, and neither are empty results (None,
    {} or []), so a temporary upstream failure isn't remembered for hours.
    """

    def __init__(self, ttl: float, max_entries: int = 1000):
        self.ttl = ttl
        self.max_entries = max_entries
        self._data: OrderedDict[str, tuple[float, object]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str, loader: Callable[[], T]) -> T:
        with self._lock:
            hit = self._data.get(key)
            if hit and time.monotonic() < hit[0]:
                self._data.move_to_end(key)
                return hit[1]  # type: ignore[return-value]
        value = loader()
        if value is not None and value != {} and value != []:
            with self._lock:
                self._data[key] = (time.monotonic() + self.ttl, value)
                self._data.move_to_end(key)
                while len(self._data) > self.max_entries:
                    self._data.popitem(last=False)
        return value
