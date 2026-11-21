# Bhola Pulse Cinematic — user guide (0.1.6-1 test candidate)

> **Release status:** This guide describes the **unmerged test candidate**
> on [PR #14](https://github.com/lbudzynowski/bhola-pulse/pull/14).
> The public GitHub Release/PPA still use the earlier version (latest GitHub
> Release: `v0.1.2`, as checked on 2026-11-21). Do not confuse PR CI
> artifacts with official releases.

Bhola Pulse is a user-scoped Ubuntu GNOME/Linux system dashboard.
`cinematic` is an **opt-in** presentation based on `nerd`, not a separate
daemon, service, required ASUS component, or remote monitoring system.

## What Cinematic shows

- Four live sections: **System Pulse**, **System Activity**, **Status Grid**,
  **Network & Services**; one shared Python provider and sanitized cache
  back all display windows.
- Around **4.6 seconds** of boot animation, CRT scanlines, bounded
  glitch bursts of roughly **1.6 s** on an approximately **11.7 s**
  cycle (after an initial lead), and an original ASCII skull
  intermittently, not continuously.
- A two-panel lower deck: **read-only typed excerpt** from the local
  `src/bhola_provider.py` source and a **real cache-backed event/sample
  stream**. It is an animation of source text, **not** active code editing
  or arbitrary command execution.
- A **760×720** canvas (before per-monitor scaling) and a fast **0.03 s**
  render interval; this can increase load with several active displays.
- The other visual modes, `modern` and `nerd`, remain available inside
  the same package. Selecting Cinematic does **not** physically remove them.

## Tested desktop and prerequisites

Manual observation on **Haiyan**, a Dell running Ubuntu 26.04.1
GNOME Wayland/XWayland with Conky **1.22.2**:

- Conky Lua/Cairo rendering: visibly functional after the shared
  compatibility adapter from [PR #10](https://github.com/lbudzynowski/bhola-pulse/pull/10).
- Cinematic live telemetry and animation: observed running on
  **three active monitors**.
- Monitor-selection workflow: user subsequently confirmed it works.
  Exact selected XRandR head and mapping were **not recorded**.
- Latest observed test candidate: **0.1.6-1**.
  See [Haiyan validation log](HAIYAN_VALIDATION_2026-11-21.md).

The package depends on `python3 >= 3.11`, `conky-all`,
`libx11-6`, `x11-xserver-utils` and `nftables`. The recommended
`iputils-ping` enables latency probes. No ASUS NumberPad, Fortinet
client, ntfy server or SSH daemon is a prerequisite for **rendering**.

**Important:** `bhola-pulse --check` verifies prerequisite probes, but
**does not draw an actual Cairo frame**. A successful check is not enough
to certify visual output, click-through or all monitors.

## Get the tested candidate (GitHub Actions, not PPA)

Use the latest successful PR CI run for the exact commit being tested.
For the already tested 0.1.6-1 candidate:
[CI run 44897139083](https://github.com/lbudzynowski/bhola-pulse/actions/runs/44897139083)
at commit `25817b3ec106492632167fa1047e03d85e5dc86e`.

```bash
mkdir -p ~/Downloads/bhola-pulse-numlock-pr14
gh run download 44897139083 \
  -R lbudzynowski/bhola-pulse \
  -n bhola-pulse-debian \
  -D ~/Downloads/bhola-pulse-numlock-pr14
cd ~/Downloads/bhola-pulse-numlock-pr14
sha256sum --check SHA256SUMS
sudo apt install ./bhola-pulse_0.1.6-1_all.deb
bhola-pulse --version
bhola-pulse --check
```

Do not continue if the SHA-256 comparison fails. This is a local
`.deb` upgrade; `sudo apt remove` and especially `purge` are
**not necessary** before installing a newer test candidate.
System APT may print an unsandboxed local download notice for a file
in a non-traversable home directory; that is not a package integrity
check, hence the explicit SHA-256 verification above.

Do **not** upload this candidate to the public PPA without an
independent release approval. Keep a verified copy of the earlier
package if you might need to roll back with
`sudo apt install --allow-downgrades ./<previous-version>.deb`.

## Run and choose a monitor

```bash
bhola-pulse --style cinematic
# Stop it using Ctrl+C in the foreground terminal.

bhola-pulse --list-monitors
# The XRandR index appears at the start of each listed line (0:, 1:, 2: ...).

bhola-pulse --style cinematic --monitor 1
bhola-pulse --style cinematic --monitors 0,2

# Save this choice for later invocations:
bhola-pulse config set cinematic
bhola-pulse config monitors set 1
bhola-pulse config monitors show
bhola-pulse

# To restore all active XRandR heads:
bhola-pulse config monitors reset
```

The actual numbering depends on the machine and is **not** interchangeable
with physical left/right ordering or GNOME monitor names. The default is
`all` active heads. A nonexistent requested XRandR head is rejected,
not silently substituted. Head selection takes effect at **startup**;
hotplug after launch requires restart (future work).

CLI monitor selector overrides `BHOLA_MONITORS`, which overrides the
saved monitor selection, which overrides the default `all`. Display
preferences live under `${XDG_CONFIG_HOME:-~/.config}/bhola-pulse/`;
the sanitized provider cache lives under
`${XDG_STATE_HOME:-~/.local/state}/bhola-pulse/dashboard.json`.

## How to read Status Grid in 0.1.6

| Indicator | Interpretation | What it does **not** do |
| --- | --- | --- |
| **UFW** | Read-only verification of configured firewall and a bounded trusted runtime probe | It does not enable/disable firewall rules |
| **SSH** | `ssh.service` or `sshd.service`: `ACTIVE` for a loaded active unit; `OFF` for loaded inactive; `N/A` if no recognized unit; `UNKNOWN` when probe unavailable | It does **not** install, start or publish SSH on the network |
| **NUM LOCK** | A readable `/sys/class/leds/*::numlock/brightness` indication: `ACTIVE`/ `OFF`; `UNKNOWN` for missing, unreadable or conflicting indicators | It does **not** emulate Num Lock or assert that the keyboard lacks a keypad |
| **NTFY** | Current implementation checks **local** `ntfy` process or `ntfy-flush` systemd units; otherwise may show `N/A` | It does **not** check remote ntfy on Coringa or actual message delivery |
| **LOCAL MON** | Recognized running local monitoring process (including `beszel-agent`) | It does **not** prove the remote Beszel hub is reachable |
| **UPDATES (N)** | Count of upgradable packages based on the **existing local** APT index: `PENDING` for N>0, `CURRENT` for N=0 | It does **not** refresh APT metadata, install upgrades or prove lists are current |
| **GPU temperature** | Actual readable supported sensor or `N/A` if not available | Never invents Intel GPU temperature using the CPU reading |

`ACTIVE` means a **specific positive signal** was observed; `OFF`
means an explicitly recognized inactive state; `N/A` indicates that
the optional local integration was not detected; `UNKNOWN` means the
reading could not be reliably determined. These words do not have
universal cross-system health semantics.

For NTFY remote checks, Intel GPU sensors, opt-in SSH configuration
and public release acceptance, see
[Issues #15–#18](https://github.com/lbudzynowski/bhola-pulse/issues).

## Known limits and safety

- **No** SSH/NTFY/FortiVPN process or systemd service is installed or
  started automatically by Bhola Pulse.
- Display discovery is XRandR/Xinerama-oriented: behavior may vary with
  Wayland compositors and hotplug. Conky 1.22.2 on the tested workstation
  did draw correctly using the patched Cairo API.
- Conky should release foreground child processes on `Ctrl+C`.
  Always verify this in a live session; `--check` alone does not.
- GPU Intel may remain `N/A` if there is no reliable dedicated sensor.
- Only sanitized status fields are suitable for public reporting.
  Do **not** paste raw local configuration, secrets, private addresses,
  full network dumps or SSH keys into GitHub Issues.
