from __future__ import annotations

import json
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from urllib import error as urllib_error

from src.bhola_network import (
    NetworkLocalCollector,
    load_network_config,
    mask_public_ip,
    parse_dns_result,
    parse_https_status,
    parse_ping_output,
    probe_dns,
    probe_https,
    probe_ping,
    probe_public_ip,
    read_default_route,
    read_network_counters,
)


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.body = body
        self.status = status

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, limit: int) -> bytes:
        return self.body[:limit]


class NetworkTests(unittest.TestCase):
    def test_local_counters_and_route_do_not_return_interface_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc = root / "proc"
            sys_root = root / "sys"
            (proc / "net").mkdir(parents=True)
            link = sys_root / "class/net/private-test-link"
            (link / "wireless").mkdir(parents=True)
            (link / "type").write_text("1\n", encoding="utf-8")
            (proc / "net/dev").write_text(
                "header\nheader\n"
                "lo: 99 0 0 0 0 0 0 0 99 0 0 0 0 0 0 0\n"
                "private-test-link: 1000 0 0 0 0 0 0 0 2000 0 0 0 0 0 0 0\n",
                encoding="utf-8",
            )
            (proc / "net/route").write_text(
                "Iface Destination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT\n"
                "private-test-link 00000000 0101A8C0 0003 0 0 100 00000000 0 0 0\n",
                encoding="utf-8",
            )
            counters = read_network_counters(proc)
            self.assertEqual((counters.received_bytes, counters.transmitted_bytes), (1000, 2000))
            route = read_default_route(proc, sys_root)
            self.assertTrue(route.present)
            self.assertEqual(route.connection_type, "wifi")

            times = iter((10.0, 11.0))
            collector = NetworkLocalCollector(proc, sys_root, lambda: next(times), lambda: 100.0)
            collector.activity()
            (proc / "net/dev").write_text(
                "header\nheader\n"
                "private-test-link: 2024 0 0 0 0 0 0 0 2512 0 0 0 0 0 0 0\n",
                encoding="utf-8",
            )
            payload = {**collector.activity(), **collector.route()}
            serialized = json.dumps(payload)
            self.assertEqual(payload["network_download_bytes_per_second"], 1024.0)
            self.assertEqual(payload["network_upload_bytes_per_second"], 512.0)
            self.assertNotIn("private-test-link", serialized)
            self.assertNotIn("192.", serialized)

    def test_public_defaults_allow_ignored_local_override_and_require_https(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            defaults = root / "defaults.json"
            local = root / "local.json"
            defaults.write_text(
                json.dumps(
                    {
                        "internet_target": "198.51.100.1",
                        "dns_name": "example.com",
                        "https_url": "https://example.com/",
                        "public_ip_url": "https://example.com/ip",
                        "probe_timeout_seconds": 2.5,
                        "gateway_interval_seconds": 30,
                        "internet_interval_seconds": 45,
                        "dns_interval_seconds": 60,
                        "https_interval_seconds": 60,
                        "public_ip_interval_seconds": 21600,
                    }
                ),
                encoding="utf-8",
            )
            local.write_text('{"dns_name":"override.example"}', encoding="utf-8")
            config = load_network_config(defaults, local)
            self.assertEqual(config.dns_name, "override.example")
            self.assertEqual(config.public_ip_interval_seconds, 21600)
            defaults.write_text(
                defaults.read_text(encoding="utf-8").replace(
                    "https://example.com/ip", "http://example.com/ip"
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_network_config(defaults, local)

    def test_ping_parsing_success_loss_and_timeout(self) -> None:
        output = (
            "2 packets transmitted, 2 received, 0% packet loss\n"
            "rtt min/avg/max/mdev = 10.000/12.500/15.000/2.500 ms\n"
        )
        self.assertEqual(parse_ping_output(output), (12.5, 0.0))

        def success(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess([], 0, output, "")

        outcome = probe_ping("198.51.100.10", 2.5, runner=success)
        self.assertTrue(outcome.success)
        self.assertEqual(outcome.values["latency_ms"], 12.5)

        def timeout(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            raise subprocess.TimeoutExpired(["ping"], 2.5)

        outcome = probe_ping("198.51.100.10", 2.5, runner=timeout)
        self.assertEqual((outcome.status, outcome.source_state), ("unknown", "timeout"))

        def unreachable(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                [],
                1,
                "2 packets transmitted, 0 received, 100% packet loss\n",
                "",
            )

        outcome = probe_ping("198.51.100.10", 2.5, runner=unreachable)
        self.assertEqual((outcome.status, outcome.source_state), ("error", "unreachable"))

    def test_dns_and_https_parsers_are_mocked(self) -> None:
        self.assertTrue(parse_dns_result(0, "address data"))
        self.assertFalse(parse_dns_result(2, ""))
        self.assertEqual(parse_https_status(204), "ok")
        self.assertEqual(parse_https_status(404), "degraded")
        self.assertEqual(parse_https_status(503), "error")

        moments = iter((1.0, 1.025))

        def resolver(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess([], 0, "address data", "")

        dns = probe_dns("example.com", 2.5, runner=resolver, monotonic=lambda: next(moments))
        self.assertEqual(dns.values["dns_latency_ms"], 25.0)

        https = probe_https(
            "https://example.com/",
            2.5,
            opener=lambda *_args, **_kwargs: FakeResponse(b"ok", 204),
        )
        self.assertTrue(https.success)

        def timeout_opener(*_args: object, **_kwargs: object) -> FakeResponse:
            raise socket.timeout()

        timed_out = probe_https("https://example.com/", 2.5, opener=timeout_opener)
        self.assertEqual((timed_out.status, timed_out.source_state), ("unknown", "timeout"))

    def test_public_ip_is_masked_and_never_returned_in_full(self) -> None:
        self.assertEqual(mask_public_ip("203.0.113.42"), "203.0.*.*")
        self.assertEqual(mask_public_ip("not-an-address"), "N/A")
        outcome = probe_public_ip(
            "https://example.com/ip",
            2.5,
            opener=lambda *_args, **_kwargs: FakeResponse(b"203.0.113.42"),
        )
        serialized = json.dumps(outcome.values)
        self.assertEqual(outcome.values["public_ip_masked"], "203.0.*.*")
        self.assertNotIn("203.0.113.42", serialized)
        self.assertNotIn("example.com", serialized)

        def unavailable(*_args: object, **_kwargs: object) -> FakeResponse:
            raise urllib_error.URLError("redacted")

        failed = probe_public_ip("https://secret.invalid/", 2.5, opener=unavailable)
        self.assertNotIn("secret.invalid", json.dumps(failed.values))


if __name__ == "__main__":
    unittest.main()
