from __future__ import annotations

import subprocess
import unittest

from src.bhola_runtime import (
    MonitorSupervisor,
    TopologyDebouncer,
    launch_generation,
    monitor_launches,
)


class FakeProcess:
    next_pid = 1000

    def __init__(self, return_code=None):
        self.pid = FakeProcess.next_pid
        FakeProcess.next_pid += 1
        self.return_code = return_code
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.return_code

    def terminate(self):
        self.terminated = True
        self.return_code = 0

    def kill(self):
        self.killed = True
        self.return_code = -9

    def wait(self, timeout=None):
        if self.return_code is None:
            raise subprocess.TimeoutExpired("fake", timeout)
        return self.return_code


class FakeStopEvent:
    def __init__(self, iterations):
        self.iterations = iterations
        self.calls = 0
        self.was_set = False

    def wait(self, _timeout):
        self.calls += 1
        return self.was_set or self.calls > self.iterations

    def set(self):
        self.was_set = True


class RuntimeTests(unittest.TestCase):
    def test_topology_change_requires_two_matching_observations(self):
        debouncer = TopologyDebouncer([0], required_observations=2)
        self.assertIsNone(debouncer.observe([0, 1]))
        self.assertIsNone(debouncer.observe([0]))
        self.assertIsNone(debouncer.observe([0, 1]))
        self.assertEqual(debouncer.observe([1, 0]), (0, 1))
        self.assertIsNone(debouncer.observe([0, 1]))

    def test_monitor_launches_preserve_scales_and_adjust_interval(self):
        launches = monitor_launches(
            [2, 0],
            {
                "BHOLA_SCALE": "1.25",
                "BHOLA_SCALE_HEAD_2": "1.50",
            },
        )
        self.assertEqual([launch.index for launch in launches], [0, 2])
        self.assertEqual([launch.scale for launch in launches], ["1.25", "1.50"])
        self.assertEqual({launch.render_interval for launch in launches}, {"0.25"})

    def test_launch_generation_uses_fixed_commands_and_clickthrough(self):
        commands = []
        clicks = []
        processes = []

        def process_factory(command, **kwargs):
            commands.append((command, kwargs))
            process = FakeProcess()
            processes.append(process)
            return process

        def clickthrough_runner(command, **kwargs):
            clicks.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0)

        result = launch_generation(
            [0, 1],
            state_file="state/test.json",
            style="nerd",
            environment={"BHOLA_SCALE": "1.25"},
            process_factory=process_factory,
            clickthrough_runner=clickthrough_runner,
        )
        self.assertEqual(result, processes)
        self.assertEqual(len(commands), 2)
        self.assertEqual(commands[0][0][-1], "--xinerama-head=0")
        self.assertEqual(commands[1][0][-1], "--xinerama-head=1")
        self.assertEqual(commands[0][1]["env"]["BHOLA_UPDATE_INTERVAL"], "0.25")
        self.assertEqual(commands[0][1]["env"]["BHOLA_STATE_FILE"], "state/test.json")
        self.assertEqual(len(clicks), 2)
        self.assertIn("src.bhola_clickthrough", clicks[0][0])

    def test_supervisor_restarts_only_after_stable_hotplug(self):
        discoveries = iter(([0], [0, 1], [0, 1], [0, 1]))
        launched = []
        stopped = []

        def discoverer():
            return next(discoveries)

        def launcher(indices):
            generation = [FakeProcess() for _ in indices]
            launched.append((tuple(indices), generation))
            return generation

        def stopper(processes):
            stopped.append(list(processes))
            for process in processes:
                process.terminate()

        supervisor = MonitorSupervisor(
            discoverer=discoverer,
            launcher=launcher,
            stopper=stopper,
            stop_event=FakeStopEvent(iterations=3),
            poll_interval=0.2,
            required_observations=2,
        )
        self.assertEqual(supervisor.run(), 0)
        self.assertEqual([item[0] for item in launched], [(0,), (0, 1)])
        self.assertEqual(stopped[0], launched[0][1])
        self.assertEqual(stopped[-1], launched[-1][1])

    def test_unreliable_discovery_breaks_debounce_sequence(self):
        discoveries = iter(([0], [0, 1], None, [0, 1], [0, 1]))
        launched = []

        def launcher(indices):
            generation = [FakeProcess() for _ in indices]
            launched.append(tuple(indices))
            return generation

        supervisor = MonitorSupervisor(
            discoverer=lambda: next(discoveries),
            launcher=launcher,
            stop_event=FakeStopEvent(iterations=4),
            poll_interval=0.2,
            required_observations=2,
        )
        self.assertEqual(supervisor.run(), 0)
        self.assertEqual(launched, [(0,), (0, 1)])

    def test_unexpected_child_exit_stops_the_generation(self):
        process = FakeProcess(return_code=7)
        stopped = []
        supervisor = MonitorSupervisor(
            discoverer=lambda: [0],
            launcher=lambda _indices: [process],
            stopper=lambda processes: stopped.append(list(processes)),
            stop_event=FakeStopEvent(iterations=1),
            poll_interval=0.2,
        )
        self.assertEqual(supervisor.run(), 7)
        self.assertEqual(stopped, [[process]])


if __name__ == "__main__":
    unittest.main()
