# Architecture

## V2 runtime

The V2 foundation separates collection, caching, and presentation:

```text
/proc + /sys + read-only local state ----+
                                         |
bounded network probes (max 2 workers) --+--> one Python provider
                                                    |
                                              atomic replace
                                                    |
                                                    v
                                          state/dashboard.json
                                                    |
                                                    v
                                        Conky + Lua/Cairo dashboard
```

One long-lived Python process schedules every local source and owns one bounded
thread pool for network probes. One Conky per monitor owns a transparent,
click-through, top-right X11/XWayland window. The default one-monitor render
interval is 0.15 seconds; startup selects 0.25 seconds for two monitors and 0.35
seconds for three or more. Every instance reads the same cache. All four visible
sections share the same snapshot and never start their own collectors.

`scripts/run-dev.sh` discovers active monitor indices through a bounded,
read-only `xrandr --listactivemonitors` call at startup. It starts one Conky on
each corresponding Xinerama head and one shared provider. If discovery is
unavailable or malformed, it safely falls back to head 0. After each Conky
creates its uniquely titled window, a short-lived Python helper finds the
single matching window by PID when available or by that fixed title, applies an
empty XShape input region, verifies the result, and exits. Ambiguous matches
fail closed. The launcher's signal and exit traps terminate every Conky and the
provider, then wait for all of them. The provider handles
SIGINT and SIGTERM with an event-driven stop and sleeps until the next scheduled
source. There is no busy-loop, service, daemon, or autostart entry.

## Source cadence

- CPU, RAM, load 1/5/15, and uptime: 1 second.
- Aggregate disk read/write rate and process count: 2 seconds.
- CPU/GPU/NVMe temperatures and sanitized top process: 5 seconds.
- Power and battery: 10 seconds.
- Aggregate download/upload rate: 1 second.
- Route and confidence-aware local status signals: 12 seconds.
- Gateway reachability: 30 seconds.
- Internet latency/loss: 45 seconds.
- DNS and HTTPS: 60 seconds.
- Masked public address: startup and no more than every 6 hours.
- Available update count: at most 60 minutes.

The standard-library implementation deliberately leaves the update count as
`unknown`. It does not invoke a package manager, refresh package metadata, use
sudo, or create network traffic.

## Cache

The provider writes a complete, flat JSON document to a temporary file in the
destination directory, flushes and fsyncs it, then replaces the target with
`os.replace`. Readers therefore see either the previous complete document or
the next complete document.

The cache does not contain raw sensor paths, process arguments, usernames, home
paths, interface names, hostnames, private URLs, or secrets. The top-process collector
uses only `/proc/<pid>/comm`, sanitizes it to a short label, and marks its CPU
value as an estimate. Service detection may inspect process arguments in memory
but stores only an aggregate state.

Schema v3 adds flat network fields so the intentionally small Lua reader never
needs a general JSON library. Each probe exposes a status, source state,
confidence, last-success timestamp, and age. Full public addresses exist only
briefly in a probe worker; only a masked value is cached. Public defaults are
versioned while local overrides remain below ignored `state/`.

Conky renders animation at the startup-selected interval, but the Lua reader
reparses the one-second cache at most twice per second. This preserves calm
motion and sub-second telemetry pickup without repeating JSON pattern scans on
every animation frame. Animation displacement is derived from the same selected
interval, so movement speed remains stable across monitor counts.

## Local sources

- CPU, memory, load, uptime, process, and aggregate disk counters come from
  `/proc`.
- Temperatures, power, and battery come from `/sys`.
- UFW distinguishes an enabled configuration from runtime filtering that can
  actually be read without privilege.
- FortiVPN combines a core-process signal, generic tunnel presence, and the
  indicator application. Indicator presence alone never produces `ok`.
- NumberPad combines its known service state with the actual local process.
- ntfy recognizes the local timer/oneshot mechanism as healthy while idle.
- Local URL monitors require a known process signal; absence of a discovered
  signal remains `unknown` instead of claiming `off`.
- Missing or unreadable sources become `unknown`, `N/A`, or a zero safe
  fallback. A source exception cannot terminate the provider.

## Network task safety

`bhola_probes.ProbeManager` owns at most two worker threads and never submits a
probe while another invocation of the same probe is active. The main provider
loop only polls futures and writes the shared cache; DNS, ping, HTTPS, and public
address operations cannot block it. Subprocess calls use `shell=False` behavior
with explicit argument arrays. HTTPS reads are capped, send no cookies or user
data, and have a hard timeout.

Status meanings are shared across the renderer:

- `ok`: a sufficiently strong current signal confirms operation;
- `degraded`: a partial signal, failed refresh with retained good data, or
  enabled configuration whose runtime cannot be confirmed;
- `error`: a positive failure signal such as complete loss or unreachable
  target;
- `off`: a known component is configured or present but inactive;
- `unknown`: no reliable conclusion can be made.

Timeout, resolver failure, unreachable target, HTTP failure, missing tool, and
stale retained data remain distinct source states. Probe exceptions are reduced
to these safe enums and are never logged with targets or private values.

## Two-column dashboard

The renderer draws one 760×570 panel with four continuously visible sections.
System Pulse sits above Status Grid in the left column; System Activity sits
above Network & Services in the right column. The old scene timer and crossfade
remain absent. Thin, locally shadowed separators and balanced spacing
distinguish the cells without creating a card, fill, or outer border.

System Pulse keeps the large clock, Polish date, CPU ring, scanner, core graph,
CPU/RAM/load, and three temperatures. System Activity keeps disk rates,
processes, uptime, top activity, and its radar graph. Status Grid retains its
six state cells plus power/battery. Network & Services keeps Internet state,
latency/loss, DNS, HTTPS, transfer rates, route/gateway, the network graph, and
five local-service indicators.

A single clipped ticker spans the bottom of the complete grid and contains only
short summaries derived from the cache. Larger headers, values, labels, status
points, and graphs restore readability compared with the narrow vertical
stack. The 28-pixel top gap plus 570-pixel configured panel height occupies only
the upper portion of a 1080-pixel Full HD monitor, keeping the previous
right-bottom desktop-icon area outside the dashboard window.

Ticker, scanner, radar, status pulse, and temperature alarm pulse use
pixel-per-second or radian-per-second rates derived from the animation clock.
Changing the Conky render cadence therefore does not change their apparent
speed.

### Presentation styles

The launcher resolves presentation before starting the provider. The explicit
`--style` option has priority over `BHOLA_STYLE`; an absent selection resolves
to `modern`. Any value outside `modern` and `nerd` fails before a runtime process
is created. The resolved value is passed unchanged to every per-monitor Conky,
so one launch cannot mix accidental renderer defaults across monitors.

`modern` remains the default LARGE SHARP renderer in `bhola_render.lua`. It
retains the scaled Cairo rings, smooth traces, flat status points, current
typography, and temperature interpolation.

`nerd` is isolated in `bhola_render_nerd.lua`. It consumes the identical metric
snapshot and implements the same four cells plus one global ticker using crisp
monospace text and ASCII primitives. CPU/RAM bars, equalizers, VU meters,
spinner, peak hold, status pulses, and ticker are character-based. Its palette
is flat terminal cyan, green, amber, red, magenta, white, and gray. It does not
use gradients, Cairo arcs, or modern line plots.

The NERD disk and network equalizers are five-row vertical ASCII banks with four
fixed columns per signal. The columns are persistent meters, not successive
history samples: their x positions never change and only their heights react to
the current disk read/write or network RX/TX values. Each real signal feeds four
different time-domain views:

- `NOW` is the current value and attacks or falls immediately;
- `FAST` is an exponential moving average with alpha 0.55;
- `SLOW` is an exponential moving average with alpha 0.18;
- `PEAK` attacks immediately, holds for two cache updates, then decays by a
  factor of 0.88 per update until the real signal catches it.

These are presentation envelopes, not frequency bands. No fixed per-column gain
is applied. A slowly decaying shared reference within each complete eight-column
bank keeps the two signal groups comparable without abrupt rescaling. Positive
activity occupies at least one row and all heights are clamped to five rows.

Disk read and network RX use cyan; disk write and network TX use magenta. Empty
cells are not drawn and the visible segments remain literal `---` glyphs above
a shared hyphen baseline. The label row uses `N F S P` for NOW, FAST, SLOW, and
PEAK in both halves of each bank.

SYSTEM PULSE uses three larger character-only VU meters for CPU, RAM, and NVMe
temperature. Each has a fixed `0 50 100` scale, a fixed `o` pivot, a visible
numeric value, and nine discrete needle positions composed only of `/`, `|`,
and `\`. CPU and RAM use 0–100%; NVMe uses 0–100°C and shows `?` when data is
unavailable. The former decorative OSC and SCN rows are removed to provide the
vertical space. LOAD plus CPU/GPU temperatures share one compact line below the
meters. This is presentation-only and does not change collection cadence or the
cache schema.

Style selection does not alter provider scheduling, cache schema, monitor
discovery, per-monitor scale, click-through, render cadence, or cleanup.

Temperature color points are:

- 45°C and below: cool cyan;
- 65°C: normal green;
- 75°C: warm yellow;
- 85°C: high orange;
- 95°C and above: alarm red.

Linear interpolation avoids abrupt changes between points. Temperatures at or
above 85°C gain a subtle alpha pulse. Unavailable sensors render neutral gray
as `N/A`.

## Deliberate boundaries

- The provider and renderer use the Python and Lua standard facilities already
  present on the host; no package is installed.
- Runtime state stays under ignored `state/`.
- Active monitors are discovered only at launcher startup. Hotplug recovery
  remains backlog; display layout and GNOME settings are untouched.
- Google Calendar, GitHub, A1, printer telemetry, authenticated services, and
  remote monitor APIs remain outside this iteration.
