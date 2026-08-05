"""Supervise per-monitor Conky instances and recover after display hotplug."""

from __future__ import annotations

import argparse
import os
import re
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from src.bhola_monitors import discover_monitor_snapshot, render_interval_for_count


_SCALE_PATTERN = re.compile(r"^([0-9]+([.][0-9]*)?|[.][0-9]+)$")
_PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ChildProcess(Protocol):
    pid: int

    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float | None = None) -> int: ...


@dataclass(frozen=True)
class MonitorLaunch:
    index: int
    title: str
    scale: str
    render_interval: str


def normalize_indices(indices: Sequence[int]) -> tuple[int, ...]:
    return tuple(sorted(set(indices))) or (0,)


def _validated_scale(value: str, fallback: str, variable_name: str) -> str:
    if _SCALE_PATTERN.fullmatch(value):
        return value
    print(
        f"Invalid {variable_name}={value!r}; using {fallback}.",
        file=sys.stderr,
    )
    return fallback


def monitor_launches(
    indices: Sequence[int], environment: Mapping[str, str]
) -> list[MonitorLaunch]:
    normalized = normalize_indices(indices)
    default_scale = _validated_scale(
        environment.get("BHOLA_SCALE", "1.25"), "1.25", "BHOLA_SCALE"
    )
    render_interval = f"{render_interval_for_count(len(normalized)):.2f}"
    launches = []
    for index in normalized:
        variable_name = f"BHOLA_SCALE_HEAD_{index}"
        scale = _validated_scale(
            environment.get(variable_name, default_scale), default_scale, variable_name
        )
        launches.append(
            MonitorLaunch(
                index=index,
                title=f"conky (Bhola {index})",
                scale=scale,
                render_interval=render_interval,
            )
        )
    return launches


class TopologyDebouncer:
    """Accept a topology only after it is observed repeatedly."""

    def __init__(self, current: Sequence[int], required_observations: int = 2) -> None:
        if required_observations < 1:
            raise ValueError("required_observations must be positive")
        self.current = normalize_indices(current)
        self.required_observations = required_observations
        self._candidate: tuple[int, ...] | None = None
        self._observations = 0

    def reset_pending(self) -> None:
        self._candidate = None
        self._observations = 0

    def observe(self, indices: Sequence[int]) -> tuple[int, ...] | None:
        observed = normalize_indices(indices)
        if observed == self.current:
            self.reset_pending()
            return None
        if observed == self._candidate:
            self._observations += 1
        else:
            self._candidate = observed
            self._observations = 1
        if self._observations < self.required_observations:
            return None
        self.current = observed
        self._candidate = None
        self._observations = 0
        return observed


def stop_processes(processes: Sequence[ChildProcess], timeout: float = 5.0) -> None:
    alive = [process for process in processes if process.poll() is None]
    for process in alive:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + timeout
    for process in alive:
        remaining = max(0.0, deadline - time.monotonic())
        try:
            process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except ProcessLookupError:
                pass
    for process in alive:
        if process.poll() is None:
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass


def launch_generation(
    indices: Sequence[int],
    *,
    state_file: str,
    style: str,
    environment: Mapping[str, str] | None = None,
    process_factory: Callable[..., ChildProcess] = subprocess.Popen,
    clickthrough_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[ChildProcess]:
    base_environment = dict(os.environ if environment is None else environment)
    launches = monitor_launches(indices, base_environment)
    processes: list[ChildProcess] = []
    try:
        print(
            "Starting Bhola Pulse "
            f"{style} on {len(launches)} active monitor(s) at "
            f"{launches[0].render_interval} s."
        )
        for launch in launches:
            child_environment = base_environment.copy()
            child_environment.update(
                {
                    "BHOLA_WINDOW_TITLE": launch.title,
                    "BHOLA_UPDATE_INTERVAL": launch.render_interval,
                    "BHOLA_SCALE": launch.scale,
                    "BHOLA_STYLE": style,
                    "BHOLA_STATE_FILE": state_file,
                }
            )
            print(f"Starting monitor head {launch.index} at scale {launch.scale}.")
            process = process_factory(
                [
                    "conky",
                    "--config=conky/bhola-pulse.conf",
                    f"--xinerama-head={launch.index}",
                ],
                cwd=_PROJECT_ROOT,
                env=child_environment,
            )
            processes.append(process)
            clickthrough = clickthrough_runner(
                [
                    sys.executable,
                    "-m",
                    "src.bhola_clickthrough",
                    "--pid",
                    str(process.pid),
                    "--name",
                    launch.title,
                ],
                cwd=_PROJECT_ROOT,
                env=base_environment,
                check=False,
                capture_output=False,
                text=True,
                timeout=8.0,
            )
            if clickthrough.returncode != 0 or process.poll() is not None:
                raise RuntimeError(
                    f"Could not make dashboard instance {launch.index} click-through."
                )
        return processes
    except BaseException:
        stop_processes(processes)
        raise


class MonitorSupervisor:
    def __init__(
        self,
        *,
        discoverer: Callable[[], Sequence[int] | None],
        launcher: Callable[[Sequence[int]], list[ChildProcess]],
        stopper: Callable[[Sequence[ChildProcess]], None] = stop_processes,
        stop_event: threading.Event | None = None,
        poll_interval: float = 2.0,
        required_observations: int = 2,
    ) -> None:
        if not 0.2 <= poll_interval <= 30.0:
            raise ValueError("poll_interval must be between 0.2 and 30 seconds")
        self.discoverer = discoverer
        self.launcher = launcher
        self.stopper = stopper
        self.stop_event = stop_event or threading.Event()
        self.poll_interval = poll_interval
        self.required_observations = required_observations

    def request_stop(self) -> None:
        self.stop_event.set()

    def run(self) -> int:
        initial = self.discoverer()
        current = normalize_indices(initial or (0,))
        debouncer = TopologyDebouncer(current, self.required_observations)
        processes = self.launcher(current)
        try:
            while not self.stop_event.wait(self.poll_interval):
                for process in processes:
                    return_code = process.poll()
                    if return_code is not None:
                        print(
                            f"A Conky instance exited unexpectedly with status {return_code}.",
                            file=sys.stderr,
                        )
                        return return_code or 1
                observed = self.discoverer()
                if observed is None:
                    debouncer.reset_pending()
                    continue
                changed = debouncer.observe(observed)
                if changed is None:
                    continue
                print(
                    "Stable monitor topology change detected: "
                    f"{len(current)} -> {len(changed)} active monitor(s)."
                )
                self.stopper(processes)
                processes = []
                processes = self.launcher(changed)
                current = changed
            return 0
        finally:
            self.stopper(processes)


def _poll_interval(value: str) -> float:
    try:
        interval = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be a number") from error
    if not 0.2 <= interval <= 30.0:
        raise argparse.ArgumentTypeError("must be between 0.2 and 30 seconds")
    return interval


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-file")
    parser.add_argument("--style", choices=("modern", "nerd"))
    parser.add_argument(
        "--poll-interval",
        type=_poll_interval,
        default=os.environ.get("BHOLA_MONITOR_POLL_INTERVAL", "2.0"),
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if not args.check and (not args.state_file or not args.style):
        parser.error("--state-file and --style are required")
    return args


def main() -> int:
    args = parse_args()
    if args.check:
        debouncer = TopologyDebouncer([0], required_observations=2)
        if debouncer.observe([0, 1]) is not None:
            return 1
        if debouncer.observe([0, 1]) != (0, 1):
            return 1
        print("Dynamic monitor supervisor check passed.")
        return 0

    supervisor = MonitorSupervisor(
        discoverer=discover_monitor_snapshot,
        launcher=lambda indices: launch_generation(
            indices,
            state_file=args.state_file,
            style=args.style,
        ),
        poll_interval=args.poll_interval,
    )

    def handle_signal(_signum: int, _frame: object) -> None:
        supervisor.request_stop()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    try:
        return supervisor.run()
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Dynamic monitor supervisor failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
