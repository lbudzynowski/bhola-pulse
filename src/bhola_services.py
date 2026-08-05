"""Read-only local service status classification."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time

from .bhola_cache import sanitize_process_name


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
UFW_STATE_PATH = Path("/run/bhola-pulse/ufw-status.json")
UFW_STATE_MAX_BYTES = 4096
UFW_STATE_STALE_SECONDS = 120
UFW_FUTURE_TOLERANCE_SECONDS = 5
UFW_CONFIG_VALUES = frozenset({"enabled", "disabled", "unknown"})
UFW_RUNTIME_VALUES = frozenset({"active", "inactive", "unconfirmed", "error"})
UFW_DETAIL_VALUES = frozenset(
    {
        "verified_runtime_active",
        "verified_runtime_inactive",
        "orphan_ufw_runtime",
        "inconsistent_ruleset",
        "command_failed",
        "timeout",
        "invalid_json",
        "empty_output",
        "oversized_output",
        "program_missing",
    }
)


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


def _read_bounded_file(descriptor: int, limit: int) -> bytes:
    chunks: list[bytes] = []
    remaining = limit + 1
    while remaining:
        chunk = os.read(descriptor, remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _validated_ufw_state(
    path: Path,
    now: int,
    *,
    trusted_uid: int,
    stale_seconds: int,
) -> tuple[dict[str, object] | None, str]:
    try:
        parent_info = path.parent.lstat()
    except FileNotFoundError:
        return None, "probe_missing"
    except OSError:
        return None, "probe_invalid"
    if (
        not stat.S_ISDIR(parent_info.st_mode)
        or parent_info.st_uid != trusted_uid
        or parent_info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    ):
        return None, "probe_invalid"

    try:
        file_info = path.lstat()
    except FileNotFoundError:
        return None, "probe_missing"
    except OSError:
        return None, "probe_invalid"
    if (
        not stat.S_ISREG(file_info.st_mode)
        or file_info.st_uid != trusted_uid
        or file_info.st_nlink != 1
        or file_info.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        or not 0 < file_info.st_size <= UFW_STATE_MAX_BYTES
    ):
        return None, "probe_invalid"

    flags = os.O_RDONLY | os.O_CLOEXEC
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None, "probe_invalid"
    try:
        opened_info = os.fstat(descriptor)
        if (
            opened_info.st_dev != file_info.st_dev
            or opened_info.st_ino != file_info.st_ino
            or opened_info.st_size != file_info.st_size
        ):
            return None, "probe_invalid"
        payload = _read_bounded_file(descriptor, UFW_STATE_MAX_BYTES)
    except OSError:
        return None, "probe_invalid"
    finally:
        os.close(descriptor)
    if len(payload) != file_info.st_size or len(payload) > UFW_STATE_MAX_BYTES:
        return None, "probe_invalid"

    try:
        value = json.loads(payload.decode("utf-8", "strict"))
    except (UnicodeError, json.JSONDecodeError):
        return None, "probe_invalid"
    required_keys = {
        "schema_version",
        "observed_at_epoch",
        "config",
        "runtime",
        "verified",
        "source",
        "detail",
    }
    if not isinstance(value, dict) or set(value) != required_keys:
        return None, "probe_invalid"
    observed = value.get("observed_at_epoch")
    config = value.get("config")
    runtime = value.get("runtime")
    verified = value.get("verified")
    detail = value.get("detail")
    if (
        type(value.get("schema_version")) is not int
        or value["schema_version"] != 1
        or type(observed) is not int
        or observed <= 0
        or not isinstance(config, str)
        or config not in UFW_CONFIG_VALUES
        or not isinstance(runtime, str)
        or runtime not in UFW_RUNTIME_VALUES
        or type(verified) is not bool
        or value.get("source") != "nftables"
        or not isinstance(detail, str)
        or detail not in UFW_DETAIL_VALUES
    ):
        return None, "probe_invalid"
    expected_details = {
        "active": {"verified_runtime_active"},
        "inactive": {"verified_runtime_inactive"},
        "unconfirmed": {"orphan_ufw_runtime", "inconsistent_ruleset"},
        "error": {
            "command_failed",
            "timeout",
            "invalid_json",
            "empty_output",
            "oversized_output",
            "program_missing",
        },
    }
    if verified != (runtime in {"active", "inactive"}) or detail not in expected_details[runtime]:
        return None, "probe_invalid"
    if observed > now + UFW_FUTURE_TOLERANCE_SECONDS:
        return None, "probe_invalid"
    if now - observed > stale_seconds:
        return None, "probe_stale"
    return value, "fresh"


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
        ufw_state_path: Path = UFW_STATE_PATH,
        ufw_trusted_uid: int = 0,
        ufw_stale_seconds: int = UFW_STATE_STALE_SECONDS,
    ) -> None:
        self.proc_root = proc_root
        self.etc_root = etc_root
        self.runner = runner
        self.wall_time = wall_time
        self.ufw_state_path = ufw_state_path
        self.ufw_trusted_uid = ufw_trusted_uid
        self.ufw_stale_seconds = ufw_stale_seconds

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
        if ufw_config == "disabled":
            ufw_status, ufw_runtime, ufw_confidence, ufw_detail = (
                "off",
                "inactive",
                "high",
                "config_disabled",
            )
            ufw_observed = now
        else:
            ufw_state, ufw_source_detail = _validated_ufw_state(
                self.ufw_state_path,
                now,
                trusted_uid=self.ufw_trusted_uid,
                stale_seconds=self.ufw_stale_seconds,
            )
            if ufw_state is None:
                ufw_status, ufw_runtime, ufw_confidence, ufw_detail = (
                    "unknown",
                    "unconfirmed",
                    "low",
                    ufw_source_detail,
                )
                ufw_observed = 0
            else:
                state_config = str(ufw_state["config"])
                ufw_runtime = str(ufw_state["runtime"])
                ufw_observed = int(ufw_state["observed_at_epoch"])
                effective_config = ufw_config if ufw_config != "unknown" else state_config
                if effective_config == "disabled":
                    ufw_status, ufw_confidence, ufw_detail = "off", "high", "config_disabled"
                elif effective_config != "enabled" or state_config != effective_config:
                    ufw_status, ufw_confidence, ufw_detail = "unknown", "low", "probe_invalid"
                    ufw_runtime = "unconfirmed"
                    ufw_observed = 0
                elif ufw_runtime == "active" and ufw_state["verified"] is True:
                    ufw_status, ufw_confidence, ufw_detail = (
                        "ok",
                        "high",
                        "verified_runtime_active",
                    )
                elif ufw_runtime == "inactive" and ufw_state["verified"] is True:
                    ufw_status, ufw_confidence, ufw_detail = (
                        "degraded",
                        "high",
                        "verified_runtime_inactive",
                    )
                elif ufw_runtime == "error":
                    ufw_status, ufw_confidence, ufw_detail = "unknown", "low", "probe_error"
                    ufw_observed = 0
                else:
                    ufw_status, ufw_confidence, ufw_detail = (
                        "unknown",
                        "low",
                        "probe_unconfirmed",
                    )
                    ufw_observed = 0

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
            "service_ufw_detail": ufw_detail,
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
        values["service_ufw_last_success_epoch"] = ufw_observed
        values["service_ufw_age_seconds"] = now - ufw_observed if ufw_observed else None
        values["service_ufw_source_state"] = (
            "fresh" if ufw_observed else ("stale" if ufw_detail == "probe_stale" else "unavailable")
        )
        for name in ("ufw", "fortivpn", "numberpad", "ntfy", "monitors"):
            if name == "ufw":
                continue
            status = str(values[f"service_{name}"])
            values[f"service_{name}_last_success_epoch"] = now if status != "unknown" else 0
            values[f"service_{name}_age_seconds"] = 0 if status != "unknown" else None
            values[f"service_{name}_source_state"] = "fresh" if status != "unknown" else "unavailable"
        return values
