# Conky/Cairo compatibility after May 2026

## Confirmed failure on Ubuntu 26.04

Haiyan (Ubuntu 26.04.1 Resolute, Wayland/XWayland, Conky 1.22.2)
installed Bhola Pulse 0.1.2 from the signed apps PPA. The package
installed and `bhola-pulse --check` passed, but both renderer styles share
the Lua drawing hook, which failed on each of three monitors:

```text
conky/bhola_pulse.lua:39: attempt to call a nil value
(global 'cairo_xlib_surface_create')
```

A passing preflight proved only the provider, monitor discovery and XShape
helper, **not** a successful graphical draw.

### Haiyan live test of the first 0.1.3-1 candidate

On Haiyan, the first CI-built 0.1.3-1 artifact installed successfully
with a verified SHA256SUMS. Both `--style nerd` and `--style modern`
started and the user explicitly confirmed that **everything was displayed**.
The previous recurring `cairo_xlib_surface_create` error did not recur.

During startup each monitor instance printed
`Bhola Pulse: X11 drawing window is not ready` once. This diagnostic
is emitted only on the first unavailable drawing frame per process and
does **not** prove a lasting draw failure: later frames may recover.
The first interpretation of that line as a rendering outage was wrong.

Conky v1.22.2 has distinct X11/Wayland output settings and exposes
X11-specific window fields conditionally, but the **observed visual
success** means there was no basis for forcibly switching the backend
in this release. The speculative `out_to_x=true` / `out_to_wayland=false`
override was removed again before merge. Treat the startup diagnostic
as a possible transient and investigate separately if it persists or
panels really fail to update. A one-line startup warning is not
equivalent to a failed graphical test.

## Upstream changes in May 2026

* On 12 May 2026, Conky contributor Caellian confirmed that the
  X11-specific `cairo_xlib_surface_create` was moved out of
  `require "cairo"` for Wayland migration. On older Conky versions,
  applications using the X11 constructor must separately
  `require "cairo_xlib"`.
* On 17 May 2026, Conky **1.23.0** introduced `conky_surface()`,
  returning the active output's Cairo surface on X11 or native Wayland.
  It must be obtained inside every draw hook. Conky owns that surface:
  **do not destroy it**. Destroy only the Cairo context that the
  application creates.
* The old `conky_window.display`, `drawable` and `visual` fields are
  deprecated. The 1.23 release also deprecates old ARGB transparency
  settings and adjusts background alpha handling. Those require
  separate real-compositor visual testing.

Sources:
- https://github.com/brndnmtthws/conky/discussions/2358
- https://github.com/brndnmtthws/conky/releases/tag/v1.23.0
- https://conky.cc/lua

## Compatibility approach in Bhola Pulse 0.1.3

The shared `conky/bhola_surface.lua` selects the API during a draw hook:

1. Prefer `conky_surface()` when present (Conky 1.23+), treating it as
   a **borrowed** surface that must not be destroyed.
2. Otherwise, try `require "cairo_xlib"` (Conky 1.22.x X11 path),
   validate the window fields, and create a surface owned by the app.
3. Destroy only the app-owned legacy Xlib surface. Always destroy
   the app-created Cairo drawing context.
4. If the binding is absent or the X11 window cannot be used, print one
   diagnostic per Conky process, not endless `nil`-function errors.

The same surface handling is used by both `modern` and `nerd`; neither
renderer geometry nor telemetry collection is changed. Mocked Lua tests
check API preference, ownership, no fallback from a temporarily
unavailable native surface, legacy import, invalid window data and
missing Cairo Xlib support.

## Potential breakages for users

| Scenario | Symptom | Mitigation / follow-up |
| --- | --- | --- |
| Conky 1.22.x split Xlib module | `nil cairo_xlib_surface_create` on the old release | Install a candidate with the separately required `cairo_xlib` module; use our verified XWayland configuration |
| Conky build without Xlib Cairo support and without `conky_surface()` | No renderer; one clear diagnostic | Install appropriate Conky build or update to 1.23+ |
| Conky 1.23+ native Wayland | Cairo surface exists, but native Wayland may lack required XShape/Xinerama semantics | Verify rendering, click-through and monitor selection on a real desktop; no backend switch is forced by this patch |
| Newer Conky with different output-backend selection | Surface initialization or click-through can behave differently | Test the real compositor and Conky version before forcing any backend choice |
| 1.23+ alpha/opacity semantics | Panel opacity or stacking changes | Audit old `own_window_argb_visual/value` and `own_window_transparent`; test `own_window_colour` migration separately |
| Fractional scaling or different compositor | Panel is clipped, badly positioned or blocks clicks | Inspect logical/device pixel handling, XShape and per-display `BHOLA_SCALE_HEAD_n` |
| Monitor plug/unplug after startup | Stale monitor instances | Restart Bhola Pulse; dynamic hotplug is handled in a separate draft PR |
| Missing fonts or future Lua/Conky changes | Missing glyphs or new draw errors | Report the Conky version and capture the first error, then test both styles on real hardware |
| Conky GUI backend unavailable | `--check` passes but no graphical output | Test the live draw hook and verify Conky output backend instead of interpreting `--check` as a GUI smoke test |

## Verification

```bash
bhola-pulse --version
conky --version
bhola-pulse --check
bhola-pulse --style nerd
# Exit with Ctrl+C, then test:
bhola-pulse --style modern
```

Verify rendering visually on **all active monitors**, click-through,
clean process shutdown and absence of recurring Conky/Lua/Cairo errors.
Both styles must be tested because they use the same shared draw hook.

`--check` is still **not** a live graphical test; it now says so explicitly.
CI exercises the two surface API paths under Lua 5.3 without an X server.
The user confirmed post-fix visual output on Haiyan in both styles; click-through and ongoing telemetry refresh should still be explicitly checked before release acceptance.

## Packaging and release safety

The original signed PPA snapshot `0.1.2-2~ppa1~resolute1` stays
**immutable** and remains broken on the reproduced setup. A draft PR,
tag or test binary does not modify packages already published in the PPA.

A future 0.1.3 release needs complete CI, a fresh verified binary
package, and a separately signed PPA source upload for Noble and
Resolute. Before claiming the update is published, verify Launchpad's
published status and an `apt-cache policy bhola-pulse` readback on
the target host. Do not hot-patch files in `/usr/lib/bhola-pulse`.
