# Bhola environment discovery

Discovery was performed on 2026-07-30 using read-only commands and public Linux
telemetry interfaces. No package was installed and no system, GNOME, Wayland,
network, or autostart configuration was changed. Hostnames, addresses, hardware
serials, and full network-interface names were not recorded.

## Platform and graphical session

| Item | Observation |
| --- | --- |
| Distribution | Ubuntu 24.04.4 LTS (`noble`) |
| Kernel | 6.17.0-35-generic, x86_64 |
| Desktop | GNOME Shell 46.0 (`ubuntu:GNOME`) |
| Session | Wayland |
| Compatibility display | Both `WAYLAND_DISPLAY` and `DISPLAY` are set, so XWayland is available |

Conky is traditionally an X11 client. On this session it can target XWayland,
but GNOME Shell ultimately controls stacking and desktop-window behavior.
The proof-of-concept therefore uses an undecorated, transparent `desktop` window
with `below`, `sticky`, `skip_taskbar`, and `skip_pager` hints. Those hints are a
best-effort request under GNOME/Wayland, not a guarantee of native Wayland
layer-shell behavior.

## Runtime and graphics dependencies

| Component | Observation |
| --- | --- |
| Conky | Missing (`conky` and `conky-all` are not installed) |
| Standalone Lua | Missing for Lua 5.1 through 5.4 and LuaJIT |
| Cairo | 1.18.0 available (`libcairo2` 1.18.0-3build1) |
| Python | 3.12.3 at `/usr/bin/python3`; `tomllib` available |
| lm-sensors | `sensors` 3.6.0 with libsensors 3.6.0 |

Because Conky is absent, its compile-time modules could not be enumerated and a
real transparent/noninteractive window could not be launched. The target build
must expose Lua and Cairo bindings; `scripts/run-dev.sh --check` reports the
observed Conky build summary when it becomes available. A standalone Lua binary
is useful for linting but is not required when the chosen Conky package embeds
the compatible Lua/Cairo bindings.

## Telemetry sources

The following unprivileged, local sources are readable:

| Metric | Primary source used by the proof of concept |
| --- | --- |
| CPU utilization | `/proc/stat` deltas |
| Load average | `/proc/loadavg` / Python `os.getloadavg()` |
| Memory | `MemTotal` and `MemAvailable` in `/proc/meminfo` |
| Filesystem | `statvfs` through Python `shutil.disk_usage()` |
| Network totals | Aggregated non-loopback counters from `/proc/net/dev` |
| Temperatures | `/sys/class/hwmon/*/temp*_input`, then `/sys/class/thermal/thermal_zone*/temp` |
| Disk activity (future) | `/proc/diskstats` |

No network-interface name is persisted: the provider sums receive/transmit
bytes for all non-loopback interfaces.

Temperature discovery found readable ACPI, CPU, NVMe, GPU, and wireless thermal
sources. During the short discovery sample, CPU/ACPI readings were approximately
90.5–92.0 °C, NVMe readings approximately 49.9–58.9 °C, GPU edge 67.0 °C, and a
wireless thermal source 61.0 °C. These are transient observations, not a thermal
diagnosis. The provider prefers the CPU control sensor (`k10temp`/`Tctl`) when
present and otherwise falls back to another readable hwmon or thermal-zone value.

## Limits of this discovery

- Conky launch, animation, transparency, stacking, and input pass-through could
  not be verified because Conky and its Lua binding are missing.
- Conky compile flags/modules could not be inspected for the same reason.
- No native Wayland layer-shell implementation was evaluated; the PoC targets
  the available XWayland bridge.
- Network traffic sources were checked only for readability; no addresses,
  routes, Wi-Fi identifiers, or private service data were inspected or stored.
- Sensor values are momentary and can change substantially with system load.

## Commands and safety

The discovery used version commands, `dpkg-query`, environment-variable presence
checks, and reads under `/etc/os-release`, `/proc`, `/sys/class/thermal`, and
`/sys/class/hwmon`. It did not use `sudo`, a package manager, privileged files,
or authentication files.

## Network and services follow-up

A second read-only pass on 2026-07-31 established the signals used by the V2
Network & Services iteration. No connection, service, firewall, VPN, display, or
driver state was changed.

| Component | Sanitized observation |
| --- | --- |
| Active route | One default route is present; its address and interface name were not recorded |
| Connection source | The active routed link is wireless |
| Aggregate traffic | Non-loopback RX/TX counters are readable in `/proc` |
| FortiVPN | The indicator application is present, but no core VPN process or active tunnel signal was found |
| UFW | Configuration is enabled; unprivileged runtime filtering could not be confirmed |
| NumberPad | Both the known local process and its active service are present |
| ntfy | An enabled active timer drives a short idle oneshot service |
| Local URL monitors | No sufficiently specific process or unit signal was discovered |
| Probe tools | Local ping, resolver, HTTPS, route, and connection-state tools are available |

The provider therefore reports the observed FortiVPN state as `off` with medium
confidence, UFW as `degraded` with medium confidence, NumberPad and ntfy as
`ok` with high confidence, and local monitors as `unknown` with low confidence.
These classifications deliberately avoid treating configuration, binary
presence, or an indicator process as proof that a protected function is active.
