"""Discover active XRandR monitor indices without retaining display names."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Callable


Runner = Callable[..., subprocess.CompletedProcess[str]]


def parse_active_monitors(output: str) -> list[int]:
    indices = []
    for line in output.splitlines()[1:]:
        match = re.match(r"^\s*(\d+):\s", line)
        if match:
            indices.append(int(match.group(1)))
    return sorted(set(indices)) or [0]


def discover_active_monitors(runner: Runner = subprocess.run) -> list[int]:
    try:
        result = runner(
            ["xrandr", "--listactivemonitors"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return [0]
    if result.returncode != 0:
        return [0]
    return parse_active_monitors(result.stdout)


def select_active_monitors(indices: list[int], selection: str = "all") -> list[int]:
    """Select active XRandR monitor indices; fail closed for invalid indices."""
    available = sorted(set(indices))
    if selection == "all":
        return available
    if re.fullmatch(r"[0-9]+(?:,[0-9]+)*", selection) is None:
        raise ValueError("expected all or comma-separated indices, for example 0,2")
    requested = [int(value) for value in selection.split(",")]
    if len(requested) != len(set(requested)):
        raise ValueError("repeated monitor indices are not permitted")
    missing = sorted(set(requested).difference(available))
    if missing:
        raise ValueError(f"monitor(s) {missing} not active; available: {available}")
    return sorted(requested)


def render_interval_for_count(count: int) -> float:
    if count <= 1:
        return 0.15
    if count == 2:
        return 0.25
    return 0.35


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--indices", action="store_true")
    parser.add_argument("--select", default="all")
    parser.add_argument("--render-interval", type=int, metavar="MONITOR_COUNT")
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.check:
        sample = "Monitors: 2\n 0: +*internal 1920/1x1080/1+0+0  internal\n 1: +external 1920/1x1080/1+1920+0  external\n"
        if parse_active_monitors(sample) != [0, 1]:
            return 1
        print("Monitor discovery check passed.")
        return 0
    if args.indices:
        try:
            selected = select_active_monitors(discover_active_monitors(), args.select)
        except ValueError as error:
            print(f"Bhola Pulse: {error}", file=sys.stderr)
            return 2
        print(" ".join(str(index) for index in selected))
        return 0
    if args.render_interval is not None and args.render_interval > 0:
        print(f"{render_interval_for_count(args.render_interval):.2f}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
