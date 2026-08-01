"""Privacy-preserving local network telemetry and bounded probes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import struct
import subprocess
import time
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
UrlOpener = Callable[..., Any]


@dataclass(frozen=True)
class NetworkConfig:
    internet_target: str
    dns_name: str
    https_url: str
    public_ip_url: str
    probe_timeout_seconds: float
    gateway_interval_seconds: float
    internet_interval_seconds: float
    dns_interval_seconds: float
    https_interval_seconds: float
    public_ip_interval_seconds: float


@dataclass(frozen=True)
class NetworkCounters:
    received_bytes: int
    transmitted_bytes: int


@dataclass(frozen=True)
class RouteInfo:
    present: bool
    gateway: str | None
    interface: str | None
    connection_type: str
    tunnel_present: bool


@dataclass(frozen=True)
class ProbeOutcome:
    status: str
    source_state: str
    confidence: str
    success: bool
    values: dict[str, object]


def load_network_config(
    defaults_path: Path = Path("config/network-defaults.json"),
    local_path: Path = Path("state/network.local.json"),
) -> NetworkConfig:
    values = json.loads(defaults_path.read_text(encoding="utf-8"))
    if local_path.is_file():
        try:
            overrides = json.loads(local_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            overrides = {}
        if isinstance(overrides, dict):
            for key in values:
                if key in overrides:
                    values[key] = overrides[key]

    for key in ("https_url", "public_ip_url"):
        value = str(values[key])
        if not value.startswith("https://"):
            raise ValueError(f"{key} must use HTTPS")
        values[key] = value
    timeout = float(values["probe_timeout_seconds"])
    if not 0.25 <= timeout <= 10.0:
        raise ValueError("probe timeout must be between 0.25 and 10 seconds")
    values["probe_timeout_seconds"] = timeout
    for key in (
        "gateway_interval_seconds",
        "internet_interval_seconds",
        "dns_interval_seconds",
        "https_interval_seconds",
        "public_ip_interval_seconds",
    ):
        values[key] = max(1.0, float(values[key]))
    return NetworkConfig(**values)


def read_network_counters(proc_root: Path = Path("/proc")) -> NetworkCounters:
    received = 0
    transmitted = 0
    lines = (proc_root / "net/dev").read_text(encoding="utf-8").splitlines()[2:]
    for line in lines:
        name, separator, tail = line.partition(":")
        if not separator or name.strip() == "lo":
            continue
        fields = tail.split()
        if len(fields) < 16:
            continue
        received += int(fields[0])
        transmitted += int(fields[8])
    return NetworkCounters(received, transmitted)


def _connection_type(interface: str | None, sys_root: Path) -> str:
    if not interface:
        return "unknown"
    link = sys_root / "class/net" / interface
    if (link / "tun_flags").exists() or interface.startswith(("tun", "tap", "ppp", "wg")):
        return "vpn"
    if (link / "wireless").exists():
        return "wifi"
    try:
        if (link / "type").read_text(encoding="utf-8").strip() == "1":
            return "ethernet"
    except OSError:
        pass
    return "unknown"


def _has_tunnel(proc_root: Path, sys_root: Path) -> bool:
    try:
        lines = (proc_root / "net/dev").read_text(encoding="utf-8").splitlines()[2:]
    except OSError:
        return False
    for line in lines:
        name = line.partition(":")[0].strip()
        if not name or name == "lo":
            continue
        link = sys_root / "class/net" / name
        if (link / "tun_flags").exists() or name.startswith(("tun", "tap", "ppp", "wg")):
            try:
                return (link / "operstate").read_text(encoding="utf-8").strip() in {"up", "unknown"}
            except OSError:
                return True
    return False


def read_default_route(
    proc_root: Path = Path("/proc"),
    sys_root: Path = Path("/sys"),
) -> RouteInfo:
    try:
        lines = (proc_root / "net/route").read_text(encoding="utf-8").splitlines()[1:]
    except OSError:
        return RouteInfo(False, None, None, "unknown", _has_tunnel(proc_root, sys_root))
    for line in lines:
        fields = line.split()
        if len(fields) < 8 or fields[1] != "00000000":
            continue
        try:
            flags = int(fields[3], 16)
            raw_gateway = int(fields[2], 16)
            gateway = socket.inet_ntoa(struct.pack("<L", raw_gateway)) if raw_gateway else None
        except (OSError, ValueError, struct.error):
            continue
        if not flags & 0x1:
            continue
        interface = fields[0]
        return RouteInfo(
            True,
            gateway,
            interface,
            _connection_type(interface, sys_root),
            _has_tunnel(proc_root, sys_root),
        )
    return RouteInfo(False, None, None, "unknown", _has_tunnel(proc_root, sys_root))


class NetworkLocalCollector:
    def __init__(
        self,
        proc_root: Path = Path("/proc"),
        sys_root: Path = Path("/sys"),
        monotonic: Callable[[], float] = time.monotonic,
        wall_time: Callable[[], float] = time.time,
    ) -> None:
        self.proc_root = proc_root
        self.sys_root = sys_root
        self.monotonic = monotonic
        self.wall_time = wall_time
        self._previous: tuple[NetworkCounters, float] | None = None

    def activity(self) -> dict[str, object]:
        now = self.monotonic()
        counters = read_network_counters(self.proc_root)
        download = 0.0
        upload = 0.0
        if self._previous is not None:
            previous, previous_time = self._previous
            elapsed = max(0.001, now - previous_time)
            download = max(0.0, (counters.received_bytes - previous.received_bytes) / elapsed)
            upload = max(0.0, (counters.transmitted_bytes - previous.transmitted_bytes) / elapsed)
        self._previous = counters, now
        return {
            "network_download_bytes_per_second": round(download, 1),
            "network_upload_bytes_per_second": round(upload, 1),
        }

    def route_info(self) -> RouteInfo:
        return read_default_route(self.proc_root, self.sys_root)

    def route(self) -> dict[str, object]:
        route = self.route_info()
        now = int(self.wall_time())
        return {
            "network_route_status": "ok" if route.present else "error",
            "network_route_source_state": "fresh",
            "network_route_confidence": "high",
            "network_route_last_success_epoch": now if route.present else 0,
            "network_route_age_seconds": 0 if route.present else None,
            "network_connection_type": route.connection_type,
            "network_tunnel_present": route.tunnel_present,
        }


_LOSS_PATTERN = re.compile(r"(\d+(?:\.\d+)?)%\s+packet loss")
_RTT_PATTERN = re.compile(
    r"(?:rtt|round-trip).*?=\s*[\d.]+/([\d.]+)/[\d.]+/[\d.]+\s*ms",
    re.IGNORECASE,
)


def parse_ping_output(output: str) -> tuple[float | None, float | None]:
    loss_match = _LOSS_PATTERN.search(output)
    rtt_match = _RTT_PATTERN.search(output)
    loss = float(loss_match.group(1)) if loss_match else None
    latency = float(rtt_match.group(1)) if rtt_match else None
    return latency, loss


def _command_environment() -> dict[str, str]:
    return {
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    }


def probe_ping(
    target: str,
    timeout: float,
    *,
    count: int = 2,
    runner: CommandRunner = subprocess.run,
) -> ProbeOutcome:
    try:
        completed = runner(
            ["ping", "-n", "-c", str(count), "-W", "1", target],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_command_environment(),
        )
    except subprocess.TimeoutExpired:
        return ProbeOutcome("unknown", "timeout", "low", False, {})
    except OSError:
        return ProbeOutcome("unknown", "unavailable", "low", False, {})
    latency, loss = parse_ping_output((completed.stdout or "") + "\n" + (completed.stderr or ""))
    if loss is None:
        return ProbeOutcome(
            "error" if completed.returncode else "unknown",
            "unreachable" if completed.returncode else "parse_error",
            "medium",
            False,
            {},
        )
    if loss >= 100:
        return ProbeOutcome("error", "unreachable", "high", False, {"packet_loss_percent": loss})
    status = "ok" if loss == 0 else "degraded"
    return ProbeOutcome(
        status,
        "fresh",
        "high",
        True,
        {"latency_ms": latency, "packet_loss_percent": loss},
    )


def probe_gateway(
    route_reader: Callable[[], RouteInfo],
    timeout: float,
    *,
    runner: CommandRunner = subprocess.run,
) -> ProbeOutcome:
    route = route_reader()
    if not route.present:
        return ProbeOutcome("error", "no_route", "high", False, {})
    if not route.gateway:
        return ProbeOutcome("unknown", "no_gateway", "medium", False, {})
    outcome = probe_ping(route.gateway, timeout, count=1, runner=runner)
    return ProbeOutcome(
        outcome.status,
        outcome.source_state,
        outcome.confidence,
        outcome.success,
        {},
    )


def parse_dns_result(returncode: int, output: str) -> bool:
    return returncode == 0 and bool(output.strip())


def probe_dns(
    name: str,
    timeout: float,
    *,
    runner: CommandRunner = subprocess.run,
    monotonic: Callable[[], float] = time.monotonic,
) -> ProbeOutcome:
    started = monotonic()
    try:
        completed = runner(
            ["getent", "ahosts", name],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_command_environment(),
        )
    except subprocess.TimeoutExpired:
        return ProbeOutcome("unknown", "timeout", "low", False, {})
    except OSError:
        return ProbeOutcome("unknown", "unavailable", "low", False, {})
    elapsed_ms = max(0.0, (monotonic() - started) * 1000.0)
    if parse_dns_result(completed.returncode, completed.stdout or ""):
        return ProbeOutcome(
            "ok",
            "fresh",
            "high",
            True,
            {"dns_latency_ms": round(elapsed_ms, 1)},
        )
    return ProbeOutcome("error", "resolver_error", "high", False, {})


def parse_https_status(status_code: int) -> str:
    if 200 <= status_code < 400:
        return "ok"
    if 400 <= status_code < 500:
        return "degraded"
    return "error"


def probe_https(
    url: str,
    timeout: float,
    *,
    opener: UrlOpener = urllib_request.urlopen,
) -> ProbeOutcome:
    request = urllib_request.Request(
        url,
        headers={"Accept": "text/plain", "Range": "bytes=0-63", "User-Agent": "Bhola-Pulse/2"},
        method="GET",
    )
    try:
        with opener(request, timeout=timeout) as response:
            status_code = int(getattr(response, "status", 200))
            response.read(64)
    except (TimeoutError, socket.timeout):
        return ProbeOutcome("unknown", "timeout", "low", False, {})
    except urllib_error.HTTPError as error:
        status = parse_https_status(error.code)
        return ProbeOutcome(status, "http_error", "high", False, {})
    except (urllib_error.URLError, OSError):
        return ProbeOutcome("error", "connection_error", "medium", False, {})
    status = parse_https_status(status_code)
    return ProbeOutcome(status, "fresh", "high", status == "ok", {})


def mask_public_ip(value: str) -> str:
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return "N/A"
    if address.version == 4:
        first, second, _, _ = str(address).split(".")
        return f"{first}.{second}.*.*"
    exploded = address.exploded.split(":")
    return f"{exploded[0]}:{exploded[1]}:*"


def probe_public_ip(
    url: str,
    timeout: float,
    *,
    opener: UrlOpener = urllib_request.urlopen,
) -> ProbeOutcome:
    request = urllib_request.Request(
        url,
        headers={"Accept": "text/plain", "User-Agent": "Bhola-Pulse/2"},
        method="GET",
    )
    try:
        with opener(request, timeout=timeout) as response:
            raw = response.read(128).decode("ascii", "strict").strip()
    except (TimeoutError, socket.timeout):
        return ProbeOutcome("unknown", "timeout", "low", False, {})
    except (urllib_error.URLError, OSError, UnicodeError):
        return ProbeOutcome("error", "connection_error", "medium", False, {})
    masked = mask_public_ip(raw)
    if masked == "N/A":
        return ProbeOutcome("unknown", "invalid_response", "low", False, {})
    return ProbeOutcome("ok", "fresh", "high", True, {"public_ip_masked": masked})
