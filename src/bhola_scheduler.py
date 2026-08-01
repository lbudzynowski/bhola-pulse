"""Small monotonic scheduler used by the unified dashboard provider."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


Collector = Callable[[], dict[str, object]]


@dataclass
class ScheduledSource:
    name: str
    interval: float
    collect: Collector
    fallback: dict[str, object]
    next_run: float = field(default=0.0)


class SourceScheduler:
    def __init__(self, sources: list[ScheduledSource], start: float) -> None:
        self.sources = sources
        for source in self.sources:
            source.next_run = start

    def run_due(self, now: float, payload: dict[str, object]) -> list[str]:
        completed: list[str] = []
        for source in self.sources:
            if now + 1e-9 < source.next_run:
                continue
            try:
                payload.update(source.collect())
                payload[f"source_{source.name}"] = "ok"
            except Exception:
                payload.update(source.fallback)
                payload[f"source_{source.name}"] = "unknown"
            completed.append(source.name)
            source.next_run += source.interval
            if source.next_run <= now:
                source.next_run = now + source.interval
        return completed

    def wait_seconds(self, now: float, maximum: float = 0.5) -> float:
        if not self.sources:
            return maximum
        return max(0.0, min(maximum, min(source.next_run for source in self.sources) - now))
