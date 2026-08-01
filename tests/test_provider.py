from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import unittest

from src.bhola_provider import DEFAULT_PAYLOAD, create_scheduler, run_provider


class FakeCollectors:
    def fast(self) -> dict[str, object]:
        return {
            "cpu_percent": 12.5,
            "memory_percent": 33.0,
            "load_1": 0.1,
            "load_5": 0.2,
            "load_15": 0.3,
            "uptime_seconds": 123,
        }

    def activity(self) -> dict[str, object]:
        return {
            "disk_read_bytes_per_second": 1024.0,
            "disk_write_bytes_per_second": 2048.0,
            "disk_rate_estimated": True,
            "process_count": 42,
        }

    def network_activity(self) -> dict[str, object]:
        return {
            "network_download_bytes_per_second": 4096.0,
            "network_upload_bytes_per_second": 1024.0,
        }

    def network_route(self) -> dict[str, object]:
        return {
            "network_route_status": "ok",
            "network_route_source_state": "fresh",
            "network_route_confidence": "high",
            "network_route_last_success_epoch": 100,
            "network_route_age_seconds": 0,
            "network_connection_type": "wifi",
            "network_tunnel_present": False,
        }

    def temperatures(self) -> dict[str, object]:
        return {
            "temperature_cpu_c": None,
            "temperature_gpu_c": 51.0,
            "temperature_nvme_c": None,
        }

    def top_process(self) -> dict[str, object]:
        return {
            "top_process_name": "conky",
            "top_process_cpu_percent": 1.0,
            "top_process_estimated": True,
        }

    def power(self) -> dict[str, object]:
        return {
            "power_source": "ac",
            "battery_percent": 80.0,
            "battery_state": "charging",
        }

    def services(self) -> dict[str, object]:
        return {
            "service_ufw": "degraded",
            "service_fortivpn": "off",
            "service_numberpad": "ok",
            "service_ntfy": "ok",
            "service_monitors": "unknown",
        }

    def updates(self) -> dict[str, object]:
        return {"updates_count": None, "updates_status": "unknown"}


class ProviderTests(unittest.TestCase):
    def test_minimum_intervals_match_dashboard_contract(self) -> None:
        scheduler = create_scheduler(FakeCollectors(), start=0.0)  # type: ignore[arg-type]
        intervals = {source.name: source.interval for source in scheduler.sources}
        self.assertEqual(
            intervals,
            {
                "fast": 1.0,
                "network_activity": 1.0,
                "activity": 2.0,
                "temperatures": 5.0,
                "top_process": 5.0,
                "power": 10.0,
                "network_route": 12.0,
                "services": 12.0,
                "updates": 3600.0,
            },
        )

    def test_once_writes_one_complete_shared_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "dashboard.json"
            result = run_provider(
                output,
                threading.Event(),
                once=True,
                collectors=FakeCollectors(),  # type: ignore[arg-type]
            )
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result, 0)
            self.assertEqual(payload["schema_version"], 3)
            self.assertEqual(payload["cpu_percent"], 12.5)
            self.assertIsNone(payload["temperature_cpu_c"])
            self.assertEqual(payload["service_numberpad"], "ok")
            self.assertEqual(payload["top_process_name"], "conky")
            self.assertEqual(payload["network_connection_type"], "wifi")
            self.assertEqual(payload["network_download_bytes_per_second"], 4096.0)
            self.assertEqual(set(DEFAULT_PAYLOAD) - set(payload), set())

    def test_stop_event_closes_probe_manager_without_network(self) -> None:
        class FakeProbeManager:
            def __init__(self, stop_event: threading.Event) -> None:
                self.stop_event = stop_event
                self.closed = False

            def tick(self, _now: float) -> bool:
                self.stop_event.set()
                return False

            def update_payload(self, _payload: dict[str, object]) -> None:
                return None

            def wait_seconds(self, _now: float) -> float:
                return 0.1

            def close(self) -> None:
                self.closed = True

        with tempfile.TemporaryDirectory() as directory:
            stop_event = threading.Event()
            manager = FakeProbeManager(stop_event)
            result = run_provider(
                Path(directory) / "dashboard.json",
                stop_event,
                collectors=FakeCollectors(),  # type: ignore[arg-type]
                probe_manager=manager,  # type: ignore[arg-type]
            )
            self.assertEqual(result, 0)
            self.assertTrue(manager.closed)


if __name__ == "__main__":
    unittest.main()
