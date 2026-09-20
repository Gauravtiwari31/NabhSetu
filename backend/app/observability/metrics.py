from __future__ import annotations

from collections import Counter


class MetricsRegistry:
    def __init__(self) -> None:
        self.counters: Counter[str] = Counter()

    def increment(self, name: str, **labels: str) -> None:
        key = name if not labels else name + "|" + ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        self.counters[key] += 1

    def snapshot(self) -> dict[str, int]:
        return dict(self.counters)


metrics = MetricsRegistry()
