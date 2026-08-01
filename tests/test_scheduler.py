from __future__ import annotations

import unittest

from src.bhola_scheduler import ScheduledSource, SourceScheduler


class SchedulerTests(unittest.TestCase):
    def test_sources_run_on_independent_intervals(self) -> None:
        calls = {"fast": 0, "slow": 0}

        def fast() -> dict[str, object]:
            calls["fast"] += 1
            return {"fast_value": calls["fast"]}

        def slow() -> dict[str, object]:
            calls["slow"] += 1
            return {"slow_value": calls["slow"]}

        scheduler = SourceScheduler(
            [
                ScheduledSource("fast", 1.0, fast, {"fast_value": 0}),
                ScheduledSource("slow", 5.0, slow, {"slow_value": 0}),
            ],
            start=10.0,
        )
        payload: dict[str, object] = {}
        self.assertEqual(scheduler.run_due(10.0, payload), ["fast", "slow"])
        self.assertEqual(scheduler.run_due(10.5, payload), [])
        self.assertEqual(scheduler.run_due(11.0, payload), ["fast"])
        self.assertEqual(scheduler.run_due(15.0, payload), ["fast", "slow"])
        self.assertEqual(calls, {"fast": 3, "slow": 2})

    def test_collector_failure_uses_safe_fallback(self) -> None:
        def broken() -> dict[str, object]:
            raise OSError("private path must not escape into cache")

        scheduler = SourceScheduler(
            [ScheduledSource("broken", 2.0, broken, {"value": "unknown"})],
            start=0.0,
        )
        payload: dict[str, object] = {}
        scheduler.run_due(0.0, payload)
        self.assertEqual(payload, {"value": "unknown", "source_broken": "unknown"})

    def test_wait_is_bounded_and_never_negative(self) -> None:
        scheduler = SourceScheduler(
            [ScheduledSource("source", 10.0, lambda: {}, {})],
            start=20.0,
        )
        self.assertEqual(scheduler.wait_seconds(10.0), 0.5)
        self.assertEqual(scheduler.wait_seconds(20.5), 0.0)


if __name__ == "__main__":
    unittest.main()
