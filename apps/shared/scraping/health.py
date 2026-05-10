import time
from collections import deque


class HealthWindow:
    def __init__(self, window_seconds: int = 3600, min_samples: int = 10) -> None:
        self._window = window_seconds
        self._min_samples = min_samples
        self._events: deque[tuple[float, bool]] = deque()

    def _evict_old(self) -> None:
        cutoff = time.time() - self._window
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    def record(self, success: bool) -> None:
        self._events.append((time.time(), success))
        self._evict_old()

    def failure_rate(self) -> float:
        self._evict_old()
        if not self._events:
            return 0.0
        f = sum(1 for _, ok in self._events if not ok)
        return f / len(self._events)

    def should_fallback(self, threshold: float = 0.20) -> bool:
        self._evict_old()
        return len(self._events) >= self._min_samples and self.failure_rate() > threshold
