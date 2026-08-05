from __future__ import annotations

import subprocess
import unittest

from src.bhola_monitors import (
    discover_active_monitors,
    discover_monitor_snapshot,
    parse_active_monitors,
    parse_monitor_snapshot,
    render_interval_for_count,
)


class MonitorDiscoveryTests(unittest.TestCase):
    def test_parses_complete_snapshot_without_retaining_names(self) -> None:
        output = """Monitors: 3
 0: +*private-one 1920/1x1080/1+0+0  private-one
 1: +private-two 1920/1x1080/1+1920+0  private-two
 2: +private-three 1920/1x1080/1+3840+0  private-three
"""
        self.assertEqual(parse_monitor_snapshot(output), [0, 1, 2])
        self.assertEqual(parse_active_monitors(output), [0, 1, 2])

    def test_incomplete_snapshot_is_unreliable_but_startup_falls_back(self) -> None:
        incomplete = "Monitors: 2\n 0: +*only 1920/1x1080/1+0+0  only\n"
        self.assertIsNone(parse_monitor_snapshot(incomplete))
        self.assertEqual(parse_active_monitors(incomplete), [0])
        self.assertIsNone(parse_monitor_snapshot(""))
        self.assertEqual(parse_active_monitors(""), [0])

    def test_command_failure_is_unreliable_and_startup_falls_back(self) -> None:
        def failed_runner(*args, **kwargs):
            return subprocess.CompletedProcess(args[0], 1, "", "unavailable")

        def timed_out_runner(*args, **kwargs):
            raise subprocess.TimeoutExpired(args[0], 2.0)

        self.assertIsNone(discover_monitor_snapshot(failed_runner))
        self.assertIsNone(discover_monitor_snapshot(timed_out_runner))
        self.assertEqual(discover_active_monitors(failed_runner), [0])
        self.assertEqual(discover_active_monitors(timed_out_runner), [0])

    def test_discovery_uses_bounded_read_only_command(self) -> None:
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(
                command, 0, "Monitors: 2\n 0: +a\n 1: +b\n", ""
            )

        self.assertEqual(discover_monitor_snapshot(runner), [0, 1])
        command, kwargs = calls[0]
        self.assertEqual(command, ["xrandr", "--listactivemonitors"])
        self.assertFalse(kwargs["check"])
        self.assertEqual(kwargs["timeout"], 2.0)

    def test_render_interval_scales_with_instance_count(self) -> None:
        self.assertEqual(render_interval_for_count(1), 0.15)
        self.assertEqual(render_interval_for_count(2), 0.25)
        self.assertEqual(render_interval_for_count(3), 0.35)
        self.assertEqual(render_interval_for_count(8), 0.35)


if __name__ == "__main__":
    unittest.main()
