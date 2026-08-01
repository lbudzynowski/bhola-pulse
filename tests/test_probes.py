from __future__ import annotations

import json
import threading
import time
import unittest

from src.bhola_network import ProbeOutcome
from src.bhola_probes import ProbeDefinition, ProbeManager


class ProbeManagerTests(unittest.TestCase):
    def test_pool_is_bounded_and_same_probe_never_overlaps(self) -> None:
        release = threading.Event()
        started = [threading.Event() for _ in range(3)]
        calls = [0, 0, 0]

        def task(index: int):
            def collect() -> ProbeOutcome:
                calls[index] += 1
                started[index].set()
                release.wait(1.0)
                return ProbeOutcome("ok", "fresh", "high", True, {})

            return collect

        manager = ProbeManager(
            [
                ProbeDefinition(f"probe_{index}", 10.0, task(index), f"probe_{index}_status")
                for index in range(3)
            ],
            0.0,
            max_workers=2,
        )
        try:
            manager.tick(0.0)
            self.assertTrue(started[0].wait(0.5))
            self.assertTrue(started[1].wait(0.5))
            self.assertFalse(started[2].is_set())
            self.assertEqual(manager.active_count, 2)
            manager.tick(20.0)
            self.assertEqual(calls, [1, 1, 0])
            release.set()
            deadline = time.monotonic() + 1.0
            while not started[2].is_set() and time.monotonic() < deadline:
                manager.tick(20.1)
                time.sleep(0.01)
            self.assertTrue(started[2].is_set())
            self.assertLessEqual(manager.worker_thread_count, 2)
        finally:
            release.set()
            manager.close()
        self.assertEqual(manager.active_count, 0)
        self.assertEqual(manager.worker_thread_count, 0)

    def test_last_good_result_is_retained_and_ages_after_failure(self) -> None:
        outcomes = [
            ProbeOutcome("ok", "fresh", "high", True, {"network_latency_ms": 12.0}),
            ProbeOutcome("unknown", "timeout", "low", False, {}),
        ]
        wall = [100.0]

        def collect() -> ProbeOutcome:
            return outcomes.pop(0)

        manager = ProbeManager(
            [
                ProbeDefinition(
                    "network_internet",
                    10.0,
                    collect,
                    "network_internet_status",
                    {"network_latency_ms": None},
                )
            ],
            0.0,
            max_workers=1,
            wall_time=lambda: wall[0],
        )
        try:
            manager.tick(0.0)
            deadline = time.monotonic() + 1.0
            payload: dict[str, object] = {}
            while time.monotonic() < deadline:
                manager.tick(0.1)
                manager.update_payload(payload)
                if payload.get("network_internet_status") == "ok":
                    break
                time.sleep(0.01)
            self.assertEqual(payload["network_latency_ms"], 12.0)
            self.assertEqual(payload["network_internet_age_seconds"], 0)

            wall[0] = 115.0
            manager.tick(10.0)
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                manager.tick(10.1)
                manager.update_payload(payload)
                if payload.get("network_internet_source_state") == "timeout":
                    break
                time.sleep(0.01)
            self.assertEqual(payload["network_internet_status"], "degraded")
            self.assertEqual(payload["network_internet_source_state"], "timeout")
            self.assertEqual(payload["network_latency_ms"], 12.0)
            self.assertEqual(payload["network_internet_age_seconds"], 15)
            self.assertNotIn("token", json.dumps(payload))
        finally:
            manager.close()

    def test_close_waits_for_worker_and_leaves_no_probe_thread(self) -> None:
        release = threading.Event()

        def collect() -> ProbeOutcome:
            release.wait(1.0)
            return ProbeOutcome("ok", "fresh", "high", True, {})

        manager = ProbeManager(
            [ProbeDefinition("probe", 60.0, collect, "probe_status")],
            0.0,
            max_workers=1,
        )
        manager.tick(0.0)
        release.set()
        manager.close()
        self.assertEqual(manager.worker_thread_count, 0)


if __name__ == "__main__":
    unittest.main()
