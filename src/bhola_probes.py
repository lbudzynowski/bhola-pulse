"""Bounded, non-overlapping background execution for network probes."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from collections.abc import Callable
from dataclasses import dataclass, field
import threading
import time

from .bhola_network import ProbeOutcome


@dataclass(frozen=True)
class ProbeDefinition:
    name: str
    interval: float
    collect: Callable[[], ProbeOutcome]
    status_key: str
    fallback: dict[str, object] = field(default_factory=dict)


@dataclass
class _ProbeRecord:
    definition: ProbeDefinition
    values: dict[str, object]
    status: str = "unknown"
    source_state: str = "pending"
    confidence: str = "low"
    last_success_epoch: int = 0
    has_good_result: bool = False

    def apply(self, outcome: ProbeOutcome, wall_epoch: int) -> None:
        if outcome.success:
            self.values.update(outcome.values)
            self.status = outcome.status
            self.source_state = "fresh"
            self.confidence = outcome.confidence
            self.last_success_epoch = wall_epoch
            self.has_good_result = True
            return
        if self.has_good_result:
            self.status = "degraded"
            self.source_state = outcome.source_state
            self.confidence = "low"
            return
        self.status = outcome.status
        self.source_state = outcome.source_state
        self.confidence = outcome.confidence

    def snapshot(self, wall_epoch: int) -> dict[str, object]:
        prefix = self.definition.name
        age = (
            max(0, wall_epoch - self.last_success_epoch)
            if self.last_success_epoch > 0
            else None
        )
        return {
            **self.values,
            self.definition.status_key: self.status,
            f"{prefix}_source_state": self.source_state,
            f"{prefix}_confidence": self.confidence,
            f"{prefix}_last_success_epoch": self.last_success_epoch,
            f"{prefix}_age_seconds": age,
        }


class ProbeManager:
    def __init__(
        self,
        definitions: list[ProbeDefinition],
        start: float,
        *,
        max_workers: int = 2,
        wall_time: Callable[[], float] = time.time,
    ) -> None:
        if not 1 <= max_workers <= 2:
            raise ValueError("Bhola Pulse permits one or two probe workers")
        self.definitions = definitions
        self.max_workers = max_workers
        self.wall_time = wall_time
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="bhola-probe",
        )
        self._next_run = {definition.name: start for definition in definitions}
        self._active: dict[str, Future[ProbeOutcome]] = {}
        self._records = {
            definition.name: _ProbeRecord(definition, dict(definition.fallback))
            for definition in definitions
        }
        self._closed = False

    @property
    def active_count(self) -> int:
        return len(self._active)

    @property
    def worker_thread_count(self) -> int:
        return sum(
            1
            for thread in threading.enumerate()
            if thread.name.startswith("bhola-probe")
        )

    def tick(self, now: float) -> bool:
        if self._closed:
            return False
        changed = False
        wall_epoch = int(self.wall_time())
        for name, future in list(self._active.items()):
            if not future.done():
                continue
            del self._active[name]
            try:
                outcome = future.result()
            except Exception:
                outcome = ProbeOutcome("unknown", "error", "low", False, {})
            self._records[name].apply(outcome, wall_epoch)
            changed = True

        capacity = self.max_workers - len(self._active)
        if capacity <= 0:
            return changed
        for definition in self.definitions:
            if capacity <= 0:
                break
            if definition.name in self._active or now + 1e-9 < self._next_run[definition.name]:
                continue
            self._active[definition.name] = self._executor.submit(definition.collect)
            self._next_run[definition.name] = now + definition.interval
            capacity -= 1
        return changed

    def update_payload(self, payload: dict[str, object]) -> None:
        wall_epoch = int(self.wall_time())
        ages: list[int] = []
        for record in self._records.values():
            snapshot = record.snapshot(wall_epoch)
            payload.update(snapshot)
            age = snapshot[f"{record.definition.name}_age_seconds"]
            if isinstance(age, int):
                ages.append(age)
        payload["network_probe_age_seconds"] = max(ages) if ages else None

    def wait_seconds(self, now: float, maximum: float = 0.5) -> float:
        if self._active:
            return min(maximum, 0.1)
        if not self._next_run:
            return maximum
        return max(0.0, min(maximum, min(self._next_run.values()) - now))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for future in self._active.values():
            future.cancel()
        self._executor.shutdown(wait=True, cancel_futures=True)
        self._active.clear()
