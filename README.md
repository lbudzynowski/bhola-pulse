# Bhola Pulse

[![CI](https://github.com/lbudzynowski/bhola-pulse/actions/workflows/ci.yml/badge.svg)](https://github.com/lbudzynowski/bhola-pulse/actions/workflows/ci.yml)
[![Latest release](https://img.shields.io/github/v/release/lbudzynowski/bhola-pulse)](https://github.com/lbudzynowski/bhola-pulse/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Bhola Pulse is an animated system-telemetry dashboard for Ubuntu GNOME on
Wayland/XWayland. It combines one long-lived, standard-library-only Python
provider, one atomic JSON cache, and transparent Conky/Lua/Cairo renderers.

**Hardware scope:** This is **not an ASUS-only package**. Core Linux
telemetry can run on other manufacturers' hardware, but some fixed status
indicators detect optional local services. In the **0.1.6 test candidate**
the numeric keyboard field reads the real **Num Lock LED**, not the
ASUS Touchpad NumberPad helper. Those integrations are **not** installation
requirements; an unavailable sensor can still appear as `UNKNOWN`. See
[hardware requirements, optional integrations and known limitations](docs/hardware-and-optional-integrations.md)
before deploying to another computer.

The dashboard remains user-scoped and does not change GNOME, display, VPN,
firewall, or package-manager configuration. A separate, tightly sandboxed
systemd oneshot verifies UFW runtime state read-only; the dashboard itself
never receives firewall capabilities.

## Screenshots

<table>
  <tr>
    <td width="49%">
      <a href="docs/images/large-sharp.png"><img src="docs/images/large-sharp.png" alt="Bhola Pulse LARGE SHARP dashboard showing live system, activity, status, and network panels" width="100%"></a><br>
      <sub>LARGE SHARP — live modern renderer.</sub>
    </td>
    <td width="49%">
      <a href="docs/images/nerd-mode.png"><img src="docs/images/nerd-mode.png" alt="Bhola Pulse NERD MODE dashboard showing live terminal-style system telemetry" width="100%"></a><br>
      <sub>NERD MODE — live terminal/BBS renderer.</sub>
    </td>
  </tr>
</table>

## Dashboard

Bhola Pulse renders the same four-section 760×570 dashboard on every monitor
active at startup:

- **System Pulse** — CPU, RAM, load, uptime, temperatures, power, battery, and
  three large meters;
- **Status Grid** — local indicators for UFW, SSH server, keyboard Num Lock,
  locally detected ntfy and known monitoring processes (in 0.1.6); earlier
  releases used FortiVPN and ASUS Touchpad NumberPad. Unavailable sensors
  are not falsely reported ACTIVE.
- **System Activity** — aggregate disk read/write activity and top-process data;
- **Network & Services** — aggregate RX/TX, route presence, bounded gateway,
  Internet, DNS, HTTPS, and masked public-address probes.

All windows share one provider and one atomically replaced cache. The cache does
not contain interface names, hostnames, process arguments, private URLs,
credentials, or a complete public address.

### Presentation styles

`modern` is the default **LARGE SHARP** presentation with rings, smooth plots,
status points, temperature interpolation, and a moving ticker.

`nerd` keeps the same data and geometry but uses a terminal/BBS presentation:
ASCII bars, fixed NOW/FAST/SLOW/PEAK banks, large character-only CPU/RAM/NVMe
meters, spinner, status pulses, and a terminal ticker.

`cinematic` is an **optional test-only style**, combining the existing NERD
renderer with a 4.6-second startup sequence, original ASCII skull during some
brief glitch bursts, CRT scanlines and dual terminal panels. Its left panel
types a real excerpt from the local provider code; its right panel displays
only cache-backed samples and state transitions, not fabricated system events.
It uses a larger 760×720 canvas and a faster 0.03 s render cadence; on three
monitors this may produce substantially higher CPU use. Stop it with `Ctrl+C`.

**As of this candidate, cinematic is not part of the public v0.1.2 release.**
The experimental 0.1.4-1 artifact combines the unmerged Cairo changes from
[PR #10](https://github.com/lbudzynowski/bhola-pulse/pull/10) with the
cinematic implementation from [PR #9](https://github.com/lbudzynowski/bhola-pulse/pull/9).

Select a style for one run:

```bash
bhola-pulse --style modern
bhola-pulse --style nerd
bhola-pulse --style cinematic
BHOLA_STYLE=nerd bhola-pulse
```

Save a user preference:

```bash
bhola-pulse config set nerd
bhola-pulse config set cinematic
bhola-pulse config show
bhola-pulse config set modern
bhola-pulse config reset
```

Style precedence is:

1. `--style`;
2. `BHOLA_STYLE`;
3. the saved user preference;
4. `modern`.

The saved preference is stored in
`${XDG_CONFIG_HOME:-~/.config}/bhola-pulse/style`. Runtime state is stored in
`${XDG_STATE_HOME:-~/.local/state}/bhola-pulse/dashboard.json`. Neither path is
removed when the Debian package is uninstalled.

## Monitor selection (0.1.5 and 0.1.6 test candidates)

By default Bhola Pulse starts on **all active XRandR monitors**. Identify the
indices on the current desktop (number before each colon):

```bash
bhola-pulse --list-monitors
```

Start Cinematic on only one display or a subset:

```bash
bhola-pulse --style cinematic --monitor 1
bhola-pulse --style cinematic --monitors 0,2
```

Or save a choice across runs:

```bash
bhola-pulse config monitors set 1
bhola-pulse config monitors show
bhola-pulse config monitors reset
```

Precedence: CLI `--monitor`/`--monitors`, then `BHOLA_MONITORS`, then
the saved selection, then `all`. An unavailable head triggers an error
rather than silently switching to all screens. Selection is performed on
startup; after monitor hotplug restart the dashboard.

## Optional status meanings (0.1.5 and 0.1.6 test candidates)

- An **undetected local** ASUS NumberPad, Fortinet, ntfy or local monitoring
  integration is labeled `N/A`, not `ACTIVE`. This **does not** verify or
  certify a remote service or prove that a VPN binary is absent.
- `UNKNOWN` remains when local service verification itself is unavailable.
- A locally running Beszel agent is now recognized under `LOCAL MON`.
  The actual remote Beszel server or ntfy server on Coringa is **not**
  probed; no service addresses or credentials are guessed.
- `UPDATES (N)` is the number of upgradable packages from **currently
  cached APT metadata**, checked at most hourly using the read-only
  `apt list --upgradable` command. It displays `PENDING` when N > 0
  or `CURRENT` when N = 0. It never runs `apt update` or upgrades
  packages. Cached metadata may be stale.
- Intel GPU temperature `N/A` is a separate sensor-discovery problem,
  not falsely converted into a working temperature sensor.

### 0.1.6: Dell physical Num Lock and SSH instead of FortiVPN

The fixed `NUMBERPAD` tile used to check an ASUS touchpad daemon. On
Haiyan, a Dell with a **physical numeric keypad**, 0.1.6 instead displays
`NUM LOCK` and reads Linux `/sys/class/leds/*::numlock/brightness`:
`ACTIVE` means the LED reports Num Lock **on**, `OFF` means **off**,
`UNKNOWN` means no readable LED is exposed or different keyboards report
conflicting states. It never toggles Num Lock. The JSON field retains the
legacy name `service_numberpad` for renderer/cache compatibility.

`FORTIVPN` is replaced visually with **SSH**, based on the actual systemd
`ssh.service` / `sshd.service` state. SSH is **not** installed, enabled,
started or exposed by the dashboard. An absent SSH server shows N/A.

`NTFY` remains a local-helper indicator; do **not** confuse N/A with remote
Coringa server failure. Real ntfy notification delivery is separate work:
no URL/token has been verified for this host. Local Beszel already shows ACTIVE.
The 0.1.6 test build supersedes locally tested 0.1.5 and is not published
to GitHub Releases or a PPA.

## Install

Download the `.deb` and `SHA256SUMS` from the latest GitHub release, verify the
package, and install it with APT. **The public v0.1.2 release has a known
Cairo compatibility issue with Conky 1.22.2 (Ubuntu 26.04);** the separately
tested 0.1.3 candidate in [PR #10](https://github.com/lbudzynowski/bhola-pulse/pull/10)
is not yet part of the public release or published PPA. Read the
[compatibility guide](docs/hardware-and-optional-integrations.md) before installing:

**Testing cinematic on Haiyan?** Obtain only the CI-built candidate from the
separate development PR; it is not yet in the latest release or apps PPA.
The downloadable candidate artifact requires a successful CI run and SHA256
verification. Upgrading an installed 0.1.3 package with
`sudo apt install ./bhola-pulse_0.1.4-1_all.deb` retains config/state; uninstall
first is unnecessary. Validate `bhola-pulse --style cinematic` in the actual
graphical session. You can restore the known-good local 0.1.3-1 file with
`sudo apt install --allow-downgrades ./bhola-pulse_0.1.3-1_all.deb` from its
previous download directory.

```bash
sha256sum --check SHA256SUMS
sudo apt install ./bhola-pulse_0.1.2-1_all.deb
bhola-pulse --check
bhola-pulse
```

Stop the foreground dashboard with `Ctrl+C`. The launcher terminates every Conky
instance and the shared provider and does not leave a daemon behind.

The package depends on:

- Python 3.11 or newer;
- `conky-all` with Lua and Cairo bindings;
- `nftables` for the mandatory read-only UFW runtime probe;
- `xrandr` from `x11-xserver-utils`;
- the X11 client library used by the verified click-through helper.

`ping` is recommended. Missing, stale, or invalid optional signals produce an
honest `unknown` state instead of terminating the dashboard. On non-ASUS
hardware, `NUMBERPAD UNKNOWN` is expected without the specific ASUS
software; `UPDATES UNKNOWN` is currently unconditional because update
collection is not implemented. `NTFY` only detects specific local
processes/systemd units, not remote servers; `LOCAL MONITORS` refers to
recognized monitoring tools, not physical screens. Details and the precise
meaning of `UNKNOWN`, `OFF`, and `N/A` are documented in the
[optional integration matrix](docs/hardware-and-optional-integrations.md).

**Important:** `bhola-pulse --check` does not exercise actual graphical
Cairo rendering. After installation, visually verify `modern`, `nerd`, and (if available) `cinematic`
in the target desktop session and confirm input click-through.

### Verified UFW status

The package installs `bhola-pulse-ufw-probe.service` and a 45-second timer.
Only that short root oneshot retains `CAP_NET_ADMIN`; it executes the fixed
read-only command `/usr/sbin/nft --json list ruleset` and atomically writes a
small root-owned summary to `/run/bhola-pulse/ufw-status.json`. It never stores
the ruleset, addresses, ports, interfaces, comments, counters, or raw command
output. The unprivileged collector validates the file before using it.

UFW is rendered as `ok` only for fresh verified active runtime, `degraded` only
for fresh verified inactive runtime while configuration is enabled, `off` for
disabled configuration, and `unknown` when verification is missing, stale,
invalid, timed out, or otherwise inconclusive. See
[the UFW runtime probe design](docs/ufw-runtime-probe.md) for security,
validation, deployment, and rollback details.

## Network and privacy behavior

Network probes run outside the provider loop in a pool capped at two workers.
Each probe has a 2.5-second hard timeout and cannot overlap another invocation
of itself. Gateway runs every 30 seconds, Internet latency/loss every 45
seconds, DNS and HTTPS every 60 seconds, and the public-address lookup at
startup and at most every six hours. A failed refresh retains the last valid
value with its age and a degraded source state.

Public, non-secret defaults live in `config/network-defaults.json`. An optional
machine-local override may be placed in the runtime state directory as
`network.local.json`. Web endpoints must use HTTPS. Tests and CI use injected
fakes and perform no real network traffic.

## Development

Check requirements without launching a window:

```bash
./scripts/run-dev.sh --check
```

Run from the repository:

```bash
./scripts/run-dev.sh
./scripts/run-dev.sh --style nerd
./scripts/run-dev.sh --style cinematic
```

Run all environment-independent checks:

```bash
bash scripts/check.sh
```

Build the Debian package and checksum file:

```bash
bash scripts/build-deb.sh
```

The output is written to `dist/`. Pull-request CI compiles the Python sources,
runs the complete unit-test suite, validates shell syntax, builds the `.deb`,
checks its metadata and checksum, extracts it, and verifies the installed
launcher and payload. A successful version-changing merge to `main` creates the
matching annotated tag and GitHub release when that release does not already
exist.

## Runtime design

The provider schedules fast metrics every second, disk activity every two
seconds, temperatures and the top process every five seconds, power and local
statuses every 12 seconds, and the optional update count no more than hourly.
The current standard-library implementation reports the update count as
`unknown` instead of spawning a package manager or refreshing package metadata.

With one monitor Conky renders every 0.15 seconds. Startup selection increases
the interval to 0.25 seconds for two monitors and 0.35 seconds for three or more.
Monitor discovery occurs once at startup. Automatic recovery after later
monitor hotplug remains an explicit backlog item.

Temperature colors interpolate between cool cyan at 45°C and below, normal
green at 65°C, warm yellow at 75°C, high orange at 85°C, and alarm red at 95°C.
Missing sensors use neutral gray and `N/A`.

## Layout

- `packaging/bhola-pulse` — installed command and persistent style management;
- `packaging/debian/` — Debian package metadata;
- `packaging/systemd/` — capability-bounded UFW probe service and timer;
- `scripts/build-deb.sh` — package and SHA-256 builder;
- `scripts/run-dev.sh` — foreground multi-monitor lifecycle;
- `conky/bhola-pulse.conf` — transparent Conky window and render cadence;
- `conky/bhola_pulse.lua` — style selection and shared scaled draw hook;
- `conky/bhola_render.lua` — `modern` renderer;
- `conky/bhola_render_nerd.lua` — `nerd` renderer;
- `conky/bhola_render_cinematic.lua` — opt-in cinematic wrapper;
- `conky/bhola_cinetty_panels.lua` — source auto-typing and cache stream;
- `src/bhola_provider.py` — provider lifecycle and task composition;
- `src/bhola_collectors.py` — local Linux telemetry sources;
- `src/bhola_network.py` — aggregate counters, route discovery, parsers, and
  bounded probes;
- `src/bhola_probes.py` — two-worker non-overlapping network task manager;
- `src/bhola_services.py` — confidence-aware read-only local service status;
- `src/bhola_ufw_probe.py` — privileged parser and minimal atomic runtime state;
- `src/bhola_clickthrough.py` — one-shot verified XShape input-region helper;
- `src/bhola_monitors.py` — sanitized startup-only active-monitor discovery;
- `src/bhola_style.py` — validated CLI/environment style resolution;
- `tests/` — environment-independent provider, layout, and packaging tests.

## License

Bhola Pulse is released under the [MIT License](LICENSE).
