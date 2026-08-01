"""Read-only local service status classification."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import time

from .bhola_cache import sanitize_process_name


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class UnitState:
    loaded: bool
    active: str
    sub: str
    enabled: str


def _process_labels(proc_root: Path) -> set[str]:
    labels: set[str] = set()
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            labels.add(sanitize_process_name((entry / "comm").read_text(encoding="utf-8").strip()).lower())
            for raw in (entry / "cmdline").read_bytes().split(b"\0"):
                if raw:
                    labels.add(sanitize_process_name(raw.decode("utf-8", "ignore")).lower())
        except OSError:
            continue
    return labels


def _parse_unit_blocks(output: str) -> dict[str, UnitState]:
    result: dict[str, UnitState] = {}
    for block in re.split(r"\n\s*\n", output.strip()):
        values: dict[str, str] = {}
        for line in block.splitlines():
            key, separator, value = line.partition("=")
            if separator:
                values[key] = value
        unit = values.get("Id")
        if not unit:
            continue
        result[unit] = UnitState(
            loaded=values.get("LoadState") == "loaded",
            active=values.get("ActiveState", "unknown"),
            sub=values.get("SubState", "unknown"),
            enabled=values.get("UnitFileState", "unknown"),
        )
    return result


def read_unit_states(
    runner: CommandRunner = subprocess.run,
    timeout: float = 2.0,
) -> dict[str, UnitState]:
    units = [
        "asus_touchpad_numpad.service",
        "ntfy-flush.service",
        "ntfy-flush.timer",
    ]
    try:
        completed = runner(
            [
                "systemctl",
                "show",
                *units,
                "--property=Id,LoadState,ActiveState,SubState,UnitFileState",
                "--no-pager",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if completed.returncode != 0:
        return {}
    return _parse_unit_blocks(completed.stdout or "")


def _ufw_config(etc_root: Path) -> str:
    try:
        content = (etc_root / "ufw/ufw.conf").read_text(encoding="utf-8")
    except OSError:
        return "unknown"
    match = re.search(r"(?im)^\s*ENABLED\s*=\s*(yes|no)\s*$", content)
    if not match:
        return "unknown"
    return "enabled" if match.group(1).lower() == "yes" else "disabled"


def _ufw_runtime(runner: CommandRunner, timeout: float = 2.0) -> str:
    try:
        completed = runner(
            ["nft", "list", "ruleset"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unconfirmed"
    if completed.returncode != 0:
        return "unconfirmed"
    rules = (completed.stdout or "").lower()
    if "ufw" in rules and ("hook input" in rules or "chain input" in rules):
        return "active"
    return "inactive"


def _contains(labels: set[str], candidates: tuple[str, ...]) -> bool:
    return any(label in candidates for label in labels)


class ServiceCollector:
    def __init__(
        self,
        proc_root: Path = Path("/proc"),
        etc_root: Path = Path("/etc"),
        *,
        runner: CommandRunner = subprocess.run,
        wall_time: Callable[[], float] = time.time,
    ) -> None:
        self.proc_root = proc_root
        self.etc_root = etc_root
        self.runner = runner
        self.wall_time = wall_time

    def collect(self, tunnel_present: bool) -> dict[str, object]:
        labels = _process_labels(self.proc_root)
        units = read_unit_states(self.runner)
        now = int(self.wall_time())

        forti_process = _contains(
            labels,
            ("openfortivpn", "fortivpn", "forticlient", "forticlientvpn"),
        )
        forti_indicator = any("fortivpn_indicator" in label or "fortivpn-indicator" in label for label in labels)
        if forti_process and tunnel_present:
            forti_status, forti_confidence, forti_detail = "ok", "high", "process_and_tunnel"
        elif forti_process or tunnel_present:
            forti_status, forti_confidence, forti_detail = "degraded", "medium", "partial_signal"
        elif forti_indicator:
            forti_status, forti_confidence, forti_detail = "off", "medium", "indicator_idle"
        else:
            forti_status, forti_confidence, forti_detail = "unknown", "low", "no_signal"

        ufw_config = _ufw_config(self.etc_root)
        ufw_runtime = _ufw_runtime(self.runner) if ufw_config == "enabled" else "inactive"
        if ufw_config == "disabled":
            ufw_status, ufw_confidence = "off", "high"
        elif ufw_config == "enabled" and ufw_runtime == "active":
            ufw_status, ufw_confidence = "ok", "high"
        elif ufw_config == "enabled":
            ufw_status, ufw_confidence = "degraded", "medium"
        else:
            ufw_status, ufw_confidence = "unknown", "low"

        numberpad_process = "asus_touchpad.py" in labels
        numberpad_unit = units.get("asus_touchpad_numpad.service")
        numberpad_active = bool(numberpad_unit and numberpad_unit.active == "active")
        if numberpad_process and numberpad_active:
            numberpad_status, numberpad_confidence, numberpad_detail = "ok", "high", "process_and_unit"
        elif numberpad_process or numberpad_active:
            numberpad_status, numberpad_confidence, numberpad_detail = "degraded", "medium", "partial_signal"
        elif numberpad_unit and numberpad_unit.loaded:
            numberpad_status, numberpad_confidence, numberpad_detail = "off", "high", "unit_inactive"
        else:
            numberpad_status, numberpad_confidence, numberpad_detail = "unknown", "low", "no_signal"

        ntfy_process = "ntfy" in labels
        ntfy_timer = units.get("ntfy-flush.timer")
        ntfy_service = units.get("ntfy-flush.service")
        if ntfy_timer and ntfy_timer.active == "active":
            ntfy_status, ntfy_confidence, ntfy_detail = "ok", "high", "timer_active"
        elif ntfy_process or (ntfy_service and ntfy_service.active == "active"):
            ntfy_status, ntfy_confidence, ntfy_detail = "ok", "medium", "process_active"
        elif (ntfy_timer and ntfy_timer.loaded) or (ntfy_service and ntfy_service.loaded):
            ntfy_status, ntfy_confidence, ntfy_detail = "off", "high", "configured_inactive"
        else:
            ntfy_status, ntfy_confidence, ntfy_detail = "unknown", "low", "no_signal"

        monitor_markers = (
            "uptime-kuma",
            "gatus",
            "healthchecks",
            "local-monitor",
            "url-monitor",
            "monitor-url",
        )
        monitor_process = _contains(labels, monitor_markers)
        if monitor_process:
            monitor_status, monitor_confidence, monitor_detail = "ok", "medium", "process_active"
        else:
            monitor_status, monitor_confidence, monitor_detail = "unknown", "low", "no_known_signal"

        values: dict[str, object] = {
            "service_ufw": ufw_status,
            "service_ufw_config": ufw_config,
            "service_ufw_runtime": ufw_runtime,
            "service_ufw_confidence": ufw_confidence,
            "service_fortivpn": forti_status,
            "service_fortivpn_process": forti_process,
            "service_fortivpn_tunnel": tunnel_present,
            "service_fortivpn_indicator": forti_indicator,
            "service_fortivpn_detail": forti_detail,
            "service_fortivpn_confidence": forti_confidence,
            "service_numberpad": numberpad_status,
            "service_numberpad_detail": numberpad_detail,
            "service_numberpad_confidence": numberpad_confidence,
            "service_ntfy": ntfy_status,
            "service_ntfy_detail": ntfy_detail,
            "service_ntfy_confidence": ntfy_confidence,
            "service_monitors": monitor_status,
            "service_monitors_detail": monitor_detail,
            "service_monitors_confidence": monitor_confidence,
        }
        for name in ("ufw", "fortivpn", "numberpad", "ntfy", "monitors"):
            status = str(values[f"service_{name}"])
            values[f"service_{name}_last_success_epoch"] = now if status != "unknown" else 0
            values[f"service_{name}_age_seconds"] = 0 if status != "unknown" else None
            values[f"service_{name}_source_state"] = "fresh" if status != "unknown" else "unavailable"
        return values
