"""Discover active XRandR monitor indices without retaining display names."""

from __future__ import annotations

import argparse
import re
import subprocess
from collections.abc import Callable


Runner = Callable[..., subprocess.CompletedProcess[str]]
_HEADER_PATTERN = re.compile(r"^\s*Monitors:\s+(\d+)\s*$")
_INDEX_PATTERN = re.compile(r"^\s*(\d+):\s")


def parse_monitor_snapshot(output: str) -> list[int] | None:
    lines = output.splitlines()
    if not lines:
        return None
    header = _HEADER_PATTERN.match(lines[0])
    if not header:
        return None
    expected_count = int(header.group(1))
    indices = []
    for line in lines[1:]:
        match = _INDEX_PATTERN.match(line)
        if match:
            indices.append(int(match.group(1)))
    normalized = sorted(set(indices))
    if expected_count < 1 or len(normalized) != expected_count:
        return None
    return normalized


def parse_active_monitors(output: str) -> list[int]:
    return parse_monitor_snapshot(output) or [0]


def discover_monitor_snapshot(runner: Runner = subprocess.run) -> list[int] | None:
    try:
        result = runner(
            ["xrandr", "--listactivemonitors"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return parse_monitor_snapshot(result.stdout)


def discover_active_monitors(runner: Runner = subprocess.run) -> list[int]:
    return discover_monitor_snapshot(runner) or [0]


def render_interval_for_count(count: int) -> float:
    if count <= 1:
        return 0.15
    if count == 2:
        return 0.25
    return 0.35


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--indices", action="store_true")
    parser.add_argument("--render-interval", type=int, metavar="MONITOR_COUNT")
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.check:
        sample = "Monitors: 2\n 0: +*internal 1920/1x1080/1+0+0  internal\n 1: +external 1920/1x1080/1+1920+0  external\n"
        if parse_monitor_snapshot(sample) != [0, 1]:
            return 1
        print("Monitor discovery check passed.")
        return 0
    if args.indices:
        print(" ".join(str(index) for index in discover_active_monitors()))
        return 0
    if args.render_interval is not None and args.render_interval > 0:
        print(f"{render_interval_for_count(args.render_interval):.2f}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
