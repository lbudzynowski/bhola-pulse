# Haiyan acceptance notes — Bhola Pulse Cinematic (21 November 2026)

**Status: manual functional acceptance in progress; NOT a public release.**

These notes capture the user's actual test evidence supplied in the
conversation, cross-checked against repository changes. The original
screenshots are **not committed** here, since they contain local desktop
and terminal context; this is a privacy-preserving textual summary.
Do not treat observations as automated tests or as broad platform
certification.

## Observed environment

- Test host: **Haiyan**, Dell laptop with a **physical numeric keypad**.
- OS/session: Ubuntu **26.04.1**, GNOME **Wayland/XWayland**.
- Conky version: **1.22.2**, with Cairo/Lua enabled and XShape support.
- Displays: **three active monitors**, confirmed showing the live
  Cinematic scene; user also reported that the subsequently added
  **monitor-selection feature works**. Specific XRandR index used in the
  selection test was not captured here.
- Execution: interactive foreground `bhola-pulse --style cinematic`.
  The overall dashboard and changing live readings were visibly observed.

## Chronology: v0.1.2 → tested v0.1.6

| Candidate | Change | Evidence and limit |
| --- | --- | --- |
| **v0.1.2** | Existing public release/PPA | Installation and `--check` could succeed while Cairo drawing failed on Conky 1.22.2; known `cairo_xlib_surface_create` missing binding. |
| **v0.1.3-1**, PR #10 | Shared compatibility adapter for Conky 1.22.x and newer surface APIs | User verified both `modern` and `nerd` visually rendering on Haiyan; an initial transient X11 window-not-ready message does **not** mean the whole dashboard failed. |
| **v0.1.4-1**, PR #12 | Cinematic: NERD + boot, glitch, skull, source and real-cache panels | User installed GitHub Actions CI `.deb` after checking `SHA256SUMS`, then confirmed Cinematic visually works on all three displays. No publication/merge. |
| **v0.1.5-1**, PR #13 | Select XRandR heads, `N/A` for absent local options, Beszel detection and cached APT update count | User confirmed selection works and sent a live screenshot showing `LOCAL MON ACTIVE`, `UPDATES (19) PENDING`, `UFW ACTIVE`, and optional N/A. |
| **v0.1.6-1**, PR #14 | Correct Dell physical Num Lock detection; replace FortiVPN tile with SSH | Screenshot shows `NUM LOCK OFF`, `SSH N/A`, `NTFY N/A`, `LOCAL MON ACTIVE`, `UPDATES (19) PENDING`. User called the result satisfactory. `NUM LOCK` change to ACTIVE after a keypress was **not independently documented**. |

Related PRs:
[#9 original Cinematic](https://github.com/lbudzynowski/bhola-pulse/pull/9),
[#10 Conky fix](https://github.com/lbudzynowski/bhola-pulse/pull/10),
[#12 integrated 0.1.4](https://github.com/lbudzynowski/bhola-pulse/pull/12),
[#13 monitors/status 0.1.5](https://github.com/lbudzynowski/bhola-pulse/pull/13),
[#14 useful services/Num Lock 0.1.6](https://github.com/lbudzynowski/bhola-pulse/pull/14).

## Latest screenshot: what is actually established

The screen (approximately 12:05:23 on 2026-11-21) shows:
- `SYSTEM PULSE` and `SYSTEM ACTIVITY` updating; CPU, RAM,
  CPU/NVMe temperatures, load and process counters visible.
- `NETWORK & SERVICES`: `INTERNET ACTIVE`, `DNS`, `HTTPS`,
  `GATEWAY` and `UFW` positive, as displayed by the dashboard;
  the user did not perform independent packet-level tests.
- `STATUS GRID`: `UFW ACTIVE`, `SSH N/A`, `NUM LOCK OFF`,
  `NTFY N/A`, `LOCAL MON ACTIVE`, `UPDATES (19) PENDING`.
- `GPU N/A` — no validated Intel GPU-specific temperature reading.
- `BATTERY` around 51%, `POWER AC` at screenshot time.
- Cinematic two-panel read-only source visual and real-cache event stream.

**Interpretation caveats:**
- `SSH N/A` means no recognized loaded `ssh.service/sshd.service`
  was detected; **no SSH server was installed or enabled** by this
  feature. This does not show that remote SSH access was tested.
- `NTFY N/A` refers to the **local** `ntfy` helper only.
  It is **not** a test of the user's server on Coringa or notification
  delivery.
- `LOCAL MON ACTIVE` follows a recognized local process
  (e.g., `beszel-agent`); remote hub reachability is not proved.
- `19 PENDING` comes from local **cached** APT package lists,
  not a fresh `apt update`. No automatic update was performed.
- `NUM LOCK OFF` is an observed LED state, not a test of toggling.

The background terminal in the screenshot contains older command/log
fragments. The visible functioning display alone is not enough to
attribute every terminal line to the current candidate; do not
report the entire current launch as failed based on a stale fragment.

## Package build and installation provenance

Candidate from [CI run 44897139083](https://github.com/lbudzynowski/bhola-pulse/actions/runs/44897139083),
head `25817b3ec106492632167fa1047e03d85e5dc86e`:
**completed / success**. Artifact name `bhola-pulse-debian`, containing
`bhola-pulse_0.1.6-1_all.deb` and `SHA256SUMS`.
Prior candidates were similarly downloaded as PR CI artifacts, *not*
signed public PPA releases.

The user supplied a successful SHA256 verification for **0.1.4** and
a successful APT install; later live screenshots establish 0.1.5/0.1.6
features are present. Do **not** assume that a complete terminal
install transcript for every later candidate was captured.

No branch among the listed feature PRs has been merged into `main`
as part of this acceptance log, and no 0.1.6 GitHub release or PPA
publication has been authorized.

## Acceptance items not yet signed off

- [x] Cinematic visible and live on all three active displays.
- [x] User confirmed selecting which monitor receives Cinematic works.
- [x] Updated Num Lock and SSH tiles appear in v0.1.6.
- [x] Screenshot shows real `NUM LOCK OFF` and `SSH N/A`.
- [x] Beszel-related `LOCAL MON ACTIVE` and `UPDATES (19) PENDING`
      visible in v0.1.5/0.1.6.
- [ ] Observe `NUM LOCK ACTIVE` after pressing the actual Dell Num Lock,
      then `OFF` when turning it off.
- [ ] Independently verify click-through and `Ctrl+C` cleanup on
      v0.1.6 with the selected monitor configuration.
- [ ] Check resource use of cinematic 0.03 s rendering under load and
      after extended runtime.
- [ ] Verify behavior after external monitor hotplug, if needed;
      current release only discovers heads at startup.
- [ ] Decide what to do about local-only `NTFY N/A` and
      `SSH N/A` without enabling extra network-facing services
      automatically.
- [ ] Assess Intel iGPU temp hardware sensors before changing
      `GPU N/A`.
- [ ] Obtain explicit authorization for any merge, public GitHub Release
      or PPA upload. Note: this repository's `main` CI workflow can
      generate a release on version-changing pushes.

Tracked follow-ups:
[#15 remote ntfy](https://github.com/lbudzynowski/bhola-pulse/issues/15),
[#16 Intel GPU](https://github.com/lbudzynowski/bhola-pulse/issues/16),
[#17 opt-in SSH](https://github.com/lbudzynowski/bhola-pulse/issues/17),
[#18 release readiness](https://github.com/lbudzynowski/bhola-pulse/issues/18).

## Safety and deployment boundaries

- A dashboard tile is *read-only* and must not itself cause a service
  to be installed, started, enabled or exposed to the Internet.
- `N/A` is not a critical failure; `UNKNOWN` cannot be upgraded
  to `ACTIVE` without evidence.
- `sudo apt autoremove` is **not necessary** as part of a local
  Bhola Pulse package upgrade, and `purge` could remove useful state.
- Preserve previous trusted `.deb` files for
  `apt install --allow-downgrades` rollback if needed.
- Do not publish raw cache, interface names, network addresses or
  credentials as troubleshooting evidence.
