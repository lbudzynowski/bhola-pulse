local source = [=[
def create_scheduler(collectors: SystemCollectors, start: float) -> SourceScheduler:
    sources = [
        ScheduledSource(
            "fast",
            1.0,
            collectors.fast,
            {
                "cpu_percent": 0.0,
                "memory_percent": 0.0,
                "load_1": 0.0,
                "load_5": 0.0,
                "load_15": 0.0,
                "uptime_seconds": 0,
            },
        ),
        ScheduledSource(
            "network_activity",
            1.0,
            collectors.network_activity,
            {
                "network_download_bytes_per_second": 0.0,
                "network_upload_bytes_per_second": 0.0,
            },
        ),
        ScheduledSource(
            "activity",
            2.0,
            collectors.activity,
            {
                "disk_read_bytes_per_second": 0.0,
                "disk_write_bytes_per_second": 0.0,
                "disk_rate_estimated": True,
                "process_count": 0,
            },
        ),
        ScheduledSource(
            "temperatures",
            5.0,
            collectors.temperatures,
            {
                "temperature_cpu_c": None,
                "temperature_gpu_c": None,
                "temperature_nvme_c": None,
            },
        ),
        ScheduledSource(
            "top_process",
            5.0,
            collectors.top_process,
            {
                "top_process_name": "unknown",
                "top_process_cpu_percent": 0.0,
                "top_process_estimated": True,
            },
        ),
        ScheduledSource(
            "power",
            10.0,
            collectors.power,
            {
                "power_source": "unknown",
                "battery_percent": None,
                "battery_state": "unknown",
            },
        ),
        ScheduledSource(
            "network_route",
            12.0,
            collectors.network_route,
            {
                "network_route_status": "unknown",
                "network_route_source_state": "unavailable",
                "network_route_confidence": "low",
                "network_route_last_success_epoch": 0,
                "network_route_age_seconds": None,
                "network_connection_type": "unknown",
                "network_tunnel_present": False,
            },
        ),
        ScheduledSource(
            "services",
            12.0,
            collectors.services,
            SERVICE_FALLBACK,
        ),
        ScheduledSource(
            "updates",
            3600.0,
            collectors.updates,
            {"updates_count": None, "updates_status": "unknown"},
        ),
    ]
    return SourceScheduler(sources, start)


def _remap_outcome(outcome: ProbeOutcome, mapping: dict[str, str]) -> ProbeOutcome:
    return ProbeOutcome(
        outcome.status,
        outcome.source_state,
        outcome.confidence,
        outcome.success,
        {
            destination: outcome.values.get(source)
            for source, destination in mapping.items()
            if source in outcome.values
        },
    )


def create_probe_manager(
    collectors: SystemCollectors,
    config: NetworkConfig,
    start: float,
) -> ProbeManager:
    def gateway() -> ProbeOutcome:
        return probe_gateway(collectors.network.route_info, config.probe_timeout_seconds)

    def internet() -> ProbeOutcome:
        return _remap_outcome(
            probe_ping(config.internet_target, config.probe_timeout_seconds),
            {
                "latency_ms": "network_latency_ms",
                "packet_loss_percent": "network_packet_loss_percent",
            },
        )

    def dns() -> ProbeOutcome:
        return _remap_outcome(
            probe_dns(config.dns_name, config.probe_timeout_seconds),
            {"dns_latency_ms": "network_dns_latency_ms"},
        )

    def https() -> ProbeOutcome:
        return probe_https(config.https_url, config.probe_timeout_seconds)

    def public_ip() -> ProbeOutcome:
        return _remap_outcome(
            probe_public_ip(config.public_ip_url, config.probe_timeout_seconds),
            {"public_ip_masked": "network_public_ip_masked"},
        )

    return ProbeManager(
        [
            ProbeDefinition(
                "network_gateway",
                config.gateway_interval_seconds,
                gateway,
                "network_gateway_status",
            ),
            ProbeDefinition(
                "network_internet",
                config.internet_interval_seconds,
                internet,
                "network_internet_status",
                {
                    "network_latency_ms": None,
                    "network_packet_loss_percent": None,
                },
            ),
            ProbeDefinition(
                "network_dns",
                config.dns_interval_seconds,
                dns,
                "network_dns_status",
                {"network_dns_latency_ms": None},
            ),
            ProbeDefinition(
                "network_https",
                config.https_interval_seconds,
                https,
                "network_https_status",
            ),
            ProbeDefinition(
                "network_public_ip",
                config.public_ip_interval_seconds,
                public_ip,
                "network_public_ip_status",
                {"network_public_ip_masked": "N/A"},
            ),
        ],
        start,
        max_workers=2,
    )


def _refresh_local_ages(payload: dict[str, object], wall_epoch: int) -> None:
    prefixes = ["network_route"] + [
        f"service_{name}"
        for name in ("ufw", "fortivpn", "numberpad", "ntfy", "monitors")
    ]
    for prefix in prefixes:
        last_success = payload.get(f"{prefix}_last_success_epoch")
        payload[f"{prefix}_age_seconds"] = (
            max(0, wall_epoch - last_success)
            if isinstance(last_success, int) and last_success > 0
            else None
        )


def run_provider(
    output: Path,
    stop_event: threading.Event,
    once: bool = False,
    collectors: SystemCollectors | None = None,
    probe_manager: ProbeManager | None = None,
    network_config: NetworkConfig | None = None,
) -> int:
    active_collectors = collectors or SystemCollectors()
    started = time.monotonic()
    scheduler = create_scheduler(active_collectors, started)
    active_probes = None
    if not once:
        active_probes = probe_manager or create_probe_manager(
            active_collectors,
            network_config or load_network_config(),
            started,
        )
    payload = dict(DEFAULT_PAYLOAD)
    try:
        while not stop_event.is_set():
            now = time.monotonic()
            completed = scheduler.run_due(now, payload)
            if active_probes is not None:
                active_probes.tick(now)
                active_probes.update_payload(payload)
            if completed:
                wall_time = datetime.now(timezone.utc)
                wall_epoch = int(wall_time.timestamp())
                payload["updated_at"] = wall_time.isoformat()
                payload["updated_at_epoch"] = wall_epoch
                _refresh_local_ages(payload, wall_epoch)
                atomic_write_json(output, payload)
                if once:
                    return 0
            wait = scheduler.wait_seconds(time.monotonic())
            if active_probes is not None:
                wait = min(wait, active_probes.wait_seconds(time.monotonic()))
            stop_event.wait(wait)
        return 0
    finally:
        if active_probes is not None:
            active_probes.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("state/dashboard.json"))
    parser.add_argument("--once", action="store_true", help="collect all sources once and exit")
    parser.add_argument("--check", action="store_true", help="validate startup without running the loop")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.check:
        collectors = SystemCollectors()
        create_scheduler(collectors, time.monotonic())
        load_network_config()
        print("Unified provider check passed.")
        return 0

    stop_event = threading.Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    return run_provider(args.output, stop_event, once=args.once)


if __name__ == "__main__":
    raise SystemExit(main())
]=]

local lines = {}
for line in (source .. "\n"):gmatch("(.-)\n") do
    lines[#lines + 1] = line
end

return lines
