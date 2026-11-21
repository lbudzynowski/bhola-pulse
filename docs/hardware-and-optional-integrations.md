# Hardware, platform and optional integrations

Bhola Pulse is a Linux telemetry dashboard, **not an ASUS-only application**.
It was initially designed around a particular Ubuntu GNOME environment,
which explains why the fixed-status grid includes an ASUS NumberPad and
specific local monitoring services. **None of those optional applications
is needed to start the dashboard.** Their status can be `unknown` on
other machines even while CPU, memory, disk and network telemetry work.

This document describes the **currently published v0.1.2** behavior and
the runtime checks in the repository's `main` branch. Unmerged PR
artifacts are not public releases and may behave differently.

## Supported and observed environment

- Intended desktop: **Ubuntu GNOME**, with a working **X11/XWayland** path
  for XShape click-through and XRandR/Xinerama monitor selection. A session
  identified as Wayland does **not** by itself demonstrate that native
  Wayland click-through and multi-monitor positioning are supported.
- The package is `Architecture: all` and has no ASUS manufacturer check.
  It uses Python, Conky/Lua/Cairo, X11 client APIs and Linux `/proc`
  and `/sys` data. It does not install ASUS drivers or any of the optional
  services listed below.
- Display discovery is performed **at launch** using
  `xrandr --listactivemonitors`. Later monitor hotplug is **not**
  automatically reconciled in the published release.
- Ubuntu 26.04.1 / Conky 1.22.2 exposed a **known v0.1.2 drawing
  incompatibility**: `cairo_xlib_surface_create` can be unavailable
  after the Conky Lua/Cairo API changes in May 2026. Do not assume a
  successful APT installation or `--check` means a panel renders.
  The Cairo compatibility fix is under review in
  [PR #10](https://github.com/lbudzynowski/bhola-pulse/pull/10);
  it is not part of the immutable v0.1.2 release or its existing PPA package.
  Both visual styles were observed rendering on a separately built PR
  candidate on Ubuntu 26.04.1; this is **not** a claim that the published
  v0.1.2 package works on that Conky build.

These are **observed/targeted environments, not a certification matrix**.
Other distributions, desktop environments, compositor versions, and
headless sessions have not been established as supported by the project.

## Required packages vs. optional capabilities

The Debian package declares these **runtime dependencies** in
[`debian/control`](../debian/control). APT normally resolves them:

| Debian package | Required for |
| --- | --- |
| `python3 (>= 3.11)` | Provider, cache, local and network collectors |
| `conky-all` | Dashboard window and Lua/Cairo drawing |
| `libx11-6` | X11 client access required by XShape click-through helper |
| `x11-xserver-utils` | `xrandr` monitor discovery |
| `nftables` | Read-only, bounded UFW runtime verification via the packaged systemd probe |

The package **recommends**, but does not depend on, `iputils-ping` for
latency/loss probes. A missing or blocked network probe should not
prevent the dashboard from launching. A usable graphical desktop and
Conky build with compatible Lua/Cairo bindings are runtime conditions,
not separately installable ASUS requirements.

Do **not** install Fortinet, ASUS NumberPad, a monitoring daemon, or a
local ntfy service just to satisfy Bhola Pulse: these are optional
indicators, not hard dependencies.

## Optional status indicators and their detection rules

The visible `Status Grid` is **fixed** in v0.1.2; unsupported indicators
are not hidden automatically. These are the current implementation's
specific detection rules, not universal service discovery:

| Indicator | What is actually checked | When absent |
| --- | --- | --- |
| **UFW** | `/etc/ufw/ufw.conf` plus the package's bounded, root-run `nftables` runtime probe and a fresh trusted result in `/run/bhola-pulse/ufw-status.json` | `off` if UFW is verifiably disabled; `unknown` if enabled but runtime evidence is missing, stale or inconclusive |
| **FORTIVPN / VPN** | Known Fortinet process names (`openfortivpn`, `fortivpn`, `forticlient`, `forticlientvpn`), a known indicator name, and whether a tunnel is detected | Normally `unknown` with no signal; it does **not** prove that all VPNs are off |
| **NUMBERPAD / PAD** | ASUS-specific process `asus_touchpad.py` and systemd unit `asus_touchpad_numpad.service` | Normally `unknown` on non-ASUS machines; ASUS hardware and its NumberPad software are **not required** |
| **NTFY** | Local `ntfy` process or local systemd `ntfy-flush.service` / `ntfy-flush.timer` | `unknown` when those local signals are absent; it **does not test a remote ntfy server**, notification delivery or a client integration |
| **LOCAL MONITORS / MONITORS** | Matching local process names such as `uptime-kuma`, `gatus`, `healthchecks`, `local-monitor`, `url-monitor` and `monitor-url` | `unknown` with no recognized local process; this field is **not** the count or status of connected physical displays |
| **UPDATES** | No APT/package update query in v0.1.2; the collector returns `updates_status = unknown` unconditionally | Always `unknown` regardless of whether updates are available |

Additional hardware-dependent fields:

- **GPU temperature** is obtained only from supported `/sys/class/hwmon`
  entries for `amdgpu`, `radeon`, `nouveau` and `nvidia`. Intel
  integrated GPU temperature is **not separately detected** by this
  collector. No matching readable sensor is shown as `N/A`.
- **CPU temperature** considers `k10temp`, `coretemp`, `acpitz`
  and a thermal-zone fallback; **NVMe temperature** looks for `nvme`
  hwmon sources. Missing hardware or readable sensors may yield `N/A`.
- **Battery/AC** depends on readable entries in
  `/sys/class/power_supply`. A desktop with no relevant power-supply
  entries may have `unknown` power source.
- **Top process** is sampled over time; the initial frame may show
  `unknown` until two usable CPU/process samples are available.

## Status semantics (do not confuse absence with failure)

| Displayed value | Meaning in the current software |
| --- | --- |
| `ok` / `ACTIVE` | A supported signal has been positively detected |
| `off` | The specific monitored feature was observed inactive or disabled through a recognized signal |
| `degraded` | A partial signal or a verified degraded state was observed |
| `unknown` | Insufficient evidence **or** an unimplemented collector; it is not equivalent to `off`, `failed`, or `N/A` |
| `N/A` | Some numeric fields (notably temperatures) lack a usable reading; **service indicators do not currently use a general N/A state** |

Consequently, a Dell or another non-ASUS laptop can show
`NUMBERPAD UNKNOWN` while Bhola Pulse itself is healthy. Setting
unsupported indicators to `OK` would be misleading; automatically
hiding or marking them `N/A` would require a future code change.

## Diagnose safely

From an installed package, check version, dependencies and startup:

```bash
bhola-pulse --version
apt-cache policy bhola-pulse
conky --version
bhola-pulse --check
bhola-pulse --style nerd
# Ctrl+C, then:
bhola-pulse --style modern
```

`--check` is a **prerequisite check**, not a live Cairo drawing test.
Confirm the panel is visible, readings change, and pointer input passes
through as intended. Check each active display, and verify
`Ctrl+C` terminates the foreground Conky/provider processes.

For a read-only explanation of local statuses (without printing host
identifiers, network configuration or credentials), run while the
dashboard is active:

```bash
python3 - <<'PY'
import json
import os
from pathlib import Path

base = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
data = json.loads((base / "bhola-pulse/dashboard.json").read_text())
for name in ("ufw", "fortivpn", "numberpad", "ntfy", "monitors"):
    print(name, data.get("service_" + name),
          data.get("service_" + name + "_detail"))
print("updates", data.get("updates_status"))
print("gpu_temperature", data.get("temperature_gpu_c"))
PY
```

This command only prints selected sanitized cache fields. It does not
modify services or firewall rules. A missing cache file means the
provider has not created it yet (or uses a custom state directory).

## Compatibility and reporting

For the May 2026 Conky compatibility work, see
[PR #10](https://github.com/lbudzynowski/bhola-pulse/pull/10)
and its [draft compatibility notes](https://github.com/lbudzynowski/bhola-pulse/blob/agent/fix-conky-may-2026-cairo-api/docs/CONKY_COMPATIBILITY.md).
If reporting a rendering issue, provide Ubuntu, desktop session and
Conky versions, the installed Bhola Pulse package version, whether
`--check` passes, and whether **both** styles actually draw. Do not
publish raw local cache files, usernames, home paths, network addresses
or other private diagnostics in public issues.
