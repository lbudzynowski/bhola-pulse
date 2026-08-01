"""Local-only Linux telemetry collectors for Bhola Pulse."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import subprocess
import time

from .bhola_cache import sanitize_process_name
from .bhola_network import NetworkLocalCollector
from .bhola_services import CommandRunner, ServiceCollector


@dataclass(frozen=True)
class CpuTimes:
    idle: int
    total: int


@dataclass(frozen=True)
class DiskCounters:
    read_bytes: int
    write_bytes: int


def read_cpu_times(proc_root: Path = Path("/proc")) -> CpuTimes:
    fields = (proc_root / "stat").read_text(encoding="utf-8").splitlines()[0].split()
    if not fields or fields[0] != "cpu" or len(fields) < 5:
        raise ValueError("aggregate CPU counters are unavailable")
    values = [int(value) for value in fields[1:9]]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return CpuTimes(idle=idle, total=sum(values))


def cpu_percent(previous: CpuTimes, current: CpuTimes) -> float:
    total_delta = current.total - previous.total
    idle_delta = current.idle - previous.idle
    if total_delta <= 0:
        return 0.0
    active = 100.0 * (total_delta - idle_delta) / total_delta
    return max(0.0, min(100.0, active))


def read_memory_percent(proc_root: Path = Path("/proc")) -> float:
    values: dict[str, int] = {}
    for line in (proc_root / "meminfo").read_text(encoding="utf-8").splitlines():
        key, _, tail = line.partition(":")
        if key in {"MemTotal", "MemAvailable"}:
            values[key] = int(tail.strip().split()[0])
    total = values.get("MemTotal", 0)
    if total <= 0:
        raise ValueError("memory totals are unavailable")
    return max(0.0, min(100.0, 100.0 * (total - values.get("MemAvailable", 0)) / total))


def read_load(proc_root: Path = Path("/proc")) -> tuple[float, float, float]:
    fields = (proc_root / "loadavg").read_text(encoding="utf-8").split()
    if len(fields) < 3:
        raise ValueError("load averages are unavailable")
    return float(fields[0]), float(fields[1]), float(fields[2])


def read_uptime(proc_root: Path = Path("/proc")) -> int:
    return max(0, int(float((proc_root / "uptime").read_text(encoding="utf-8").split()[0])))


def _temperature_value(path: Path) -> float | None:
    try:
        celsius = float(path.read_text(encoding="utf-8").strip()) / 1000.0
    except (OSError, ValueError):
        return None
    return celsius if -40.0 <= celsius <= 150.0 else None


def read_temperatures(sys_root: Path = Path("/sys")) -> dict[str, float | None]:
    candidates: dict[str, list[tuple[int, float]]] = {"cpu": [], "gpu": [], "nvme": []}
    for hwmon in sorted((sys_root / "class/hwmon").glob("hwmon*")):
        try:
            device = (hwmon / "name").read_text(encoding="utf-8").strip().lower()
        except OSError:
            device = "unknown"
        for input_path in sorted(hwmon.glob("temp*_input")):
            value = _temperature_value(input_path)
            if value is None:
                continue
            label_path = input_path.with_name(input_path.name.replace("_input", "_label"))
            try:
                label = label_path.read_text(encoding="utf-8").strip().lower()
            except OSError:
                label = "unlabelled"
            if device in {"k10temp", "coretemp"}:
                priority = 0 if label in {"tctl", "package id 0"} else 1
                candidates["cpu"].append((priority, value))
            elif device == "acpitz":
                candidates["cpu"].append((5, value))
            if device in {"amdgpu", "radeon", "nouveau", "nvidia"}:
                priority = 0 if label in {"edge", "junction", "gpu"} else 2
                candidates["gpu"].append((priority, value))
            if device == "nvme":
                priority = 0 if label == "composite" else 2
                candidates["nvme"].append((priority, value))

    result: dict[str, float | None] = {}
    for category, values in candidates.items():
        result[category] = round(min(values)[1], 1) if values else None
    if result["cpu"] is None:
        for zone in sorted((sys_root / "class/thermal").glob("thermal_zone*")):
            value = _temperature_value(zone / "temp")
            if value is not None:
                result["cpu"] = round(value, 1)
                break
    return result


def read_disk_counters(proc_root: Path = Path("/proc"), sys_root: Path = Path("/sys")) -> DiskCounters:
    read_sectors = 0
    write_sectors = 0
    for line in (proc_root / "diskstats").read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) < 14:
            continue
        name = fields[2]
        if name.startswith(("loop", "ram", "zram", "fd", "sr", "dm-")):
            continue
        block = sys_root / "class/block" / name
        if (block / "partition").exists():
            continue
        try:
            read_sectors += int(fields[5])
            write_sectors += int(fields[9])
        except ValueError:
            continue
    return DiskCounters(read_sectors * 512, write_sectors * 512)


def _process_stat(path: Path) -> tuple[int, str] | None:
    try:
        content = (path / "stat").read_text(encoding="utf-8")
        end = content.rfind(")")
        fields = content[end + 2 :].split()
        ticks = int(fields[11]) + int(fields[12])
        name = (path / "comm").read_text(encoding="utf-8").strip()
        return ticks, sanitize_process_name(name)
    except (OSError, ValueError, IndexError):
        return None


class SystemCollectors:
    def __init__(
        self,
        proc_root: Path = Path("/proc"),
        sys_root: Path = Path("/sys"),
        etc_root: Path = Path("/etc"),
        monotonic: Callable[[], float] = time.monotonic,
        wall_time: Callable[[], float] = time.time,
        command_runner: CommandRunner = subprocess.run,
    ) -> None:
        self.proc_root = proc_root
        self.sys_root = sys_root
        self.etc_root = etc_root
        self.monotonic = monotonic
        self.wall_time = wall_time
        self._cpu_previous: CpuTimes | None = None
        self._disk_previous: tuple[DiskCounters, float] | None = None
        self._process_previous: tuple[dict[int, int], int] | None = None
        self.network = NetworkLocalCollector(proc_root, sys_root, monotonic, wall_time)
        self._services = ServiceCollector(
            proc_root,
            etc_root,
            runner=command_runner,
            wall_time=wall_time,
        )

    def fast(self) -> dict[str, object]:
        current = read_cpu_times(self.proc_root)
        cpu = 0.0 if self._cpu_previous is None else cpu_percent(self._cpu_previous, current)
        self._cpu_previous = current
        load1, load5, load15 = read_load(self.proc_root)
        return {
            "cpu_percent": round(cpu, 1),
            "memory_percent": round(read_memory_percent(self.proc_root), 1),
            "load_1": round(load1, 2),
            "load_5": round(load5, 2),
            "load_15": round(load15, 2),
            "uptime_seconds": read_uptime(self.proc_root),
        }

    def temperatures(self) -> dict[str, object]:
        values = read_temperatures(self.sys_root)
        return {
            "temperature_cpu_c": values["cpu"],
            "temperature_gpu_c": values["gpu"],
            "temperature_nvme_c": values["nvme"],
        }

    def activity(self) -> dict[str, object]:
        now = self.monotonic()
        counters = read_disk_counters(self.proc_root, self.sys_root)
        read_rate = 0.0
        write_rate = 0.0
        if self._disk_previous is not None:
            previous, previous_time = self._disk_previous
            elapsed = max(0.001, now - previous_time)
            read_rate = max(0.0, (counters.read_bytes - previous.read_bytes) / elapsed)
            write_rate = max(0.0, (counters.write_bytes - previous.write_bytes) / elapsed)
        self._disk_previous = counters, now
        process_count = sum(1 for entry in self.proc_root.iterdir() if entry.name.isdigit())
        return {
            "disk_read_bytes_per_second": round(read_rate, 1),
            "disk_write_bytes_per_second": round(write_rate, 1),
            "disk_rate_estimated": True,
            "process_count": process_count,
        }

    def network_activity(self) -> dict[str, object]:
        return self.network.activity()

    def network_route(self) -> dict[str, object]:
        return self.network.route()

    def top_process(self) -> dict[str, object]:
        current_total = read_cpu_times(self.proc_root).total
        current: dict[int, int] = {}
        names: dict[int, str] = {}
        for entry in self.proc_root.iterdir():
            if not entry.name.isdigit():
                continue
            value = _process_stat(entry)
            if value is None:
                continue
            ticks, name = value
            current[int(entry.name)] = ticks
            names[int(entry.name)] = name
        top_name = "unknown"
        top_percent = 0.0
        if self._process_previous is not None:
            previous, previous_total = self._process_previous
            total_delta = current_total - previous_total
            if total_delta > 0:
                top_pid, top_delta = max(
                    ((pid, ticks - previous.get(pid, ticks)) for pid, ticks in current.items()),
                    key=lambda item: item[1],
                    default=(0, 0),
                )
                top_name = names.get(top_pid, "unknown")
                top_percent = max(0.0, min(100.0, 100.0 * top_delta / total_delta))
        self._process_previous = current, current_total
        return {
            "top_process_name": sanitize_process_name(top_name),
            "top_process_cpu_percent": round(top_percent, 1),
            "top_process_estimated": True,
        }

    def power(self) -> dict[str, object]:
        battery_percent: float | None = None
        battery_state = "unknown"
        ac_online = False
        for supply in sorted((self.sys_root / "class/power_supply").glob("*")):
            try:
                supply_type = (supply / "type").read_text(encoding="utf-8").strip().lower()
            except OSError:
                continue
            if supply_type == "battery" and battery_percent is None:
                try:
                    battery_percent = float((supply / "capacity").read_text(encoding="utf-8").strip())
                except (OSError, ValueError):
                    battery_percent = None
                try:
                    battery_state = (supply / "status").read_text(encoding="utf-8").strip().lower()
                except OSError:
                    battery_state = "unknown"
            elif supply_type in {"mains", "usb", "usb_c"}:
                try:
                    ac_online = ac_online or (supply / "online").read_text(encoding="utf-8").strip() == "1"
                except OSError:
                    pass
        if ac_online:
            source = "ac"
        elif battery_percent is not None:
            source = "battery"
        else:
            source = "unknown"
        return {
            "power_source": source,
            "battery_percent": None if battery_percent is None else round(battery_percent, 1),
            "battery_state": battery_state,
        }

    def services(self) -> dict[str, object]:
        route = self.network.route_info()
        return self._services.collect(route.tunnel_present)

    def updates(self) -> dict[str, object]:
        return {
            "updates_count": None,
            "updates_status": "unknown",
        }
