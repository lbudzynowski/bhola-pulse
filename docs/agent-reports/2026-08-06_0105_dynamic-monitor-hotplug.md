# Dynamic monitor hotplug preparation report

Date: 2026-08-06 01:05 CEST

## Scope

This change prepares foreground recovery after active-monitor topology changes.
It does not configure displays, alter GNOME, enable autostart, deploy to Bhola,
change the package version, publish a release, update the PPA, or merge anything.

Base:

- repository: `lbudzynowski/bhola-pulse`;
- base branch: `main`;
- base commit: `4b230d2f581def471cf28b80bba50d2b5fca56a6`;
- implementation branch: `agent/dynamic-monitor-hotplug`;
- validated implementation commit: `ac7a0e06801779d5d6e0cb1f60e65e04aabb7457`;
- draft pull request: `#8`.

## Runtime design

The existing launcher still creates exactly one long-lived provider and waits
for its first atomic cache. It then starts one foreground Python supervisor.
The supervisor owns only the per-monitor Conky presentation processes.

Monitor discovery uses the fixed, bounded, read-only command:

```text
xrandr --listactivemonitors
```

A runtime sample is trusted only when the declared monitor count matches the
complete set of parsed numeric Xinerama heads. Failed, timed-out, malformed, or
incomplete samples are ignored rather than converted into a false one-monitor
fallback.

A changed topology is accepted only after two consecutive complete matching
samples. The default polling interval is two seconds. The diagnostic override
`BHOLA_MONITOR_POLL_INTERVAL` is constrained to 0.2–30 seconds.

After an accepted change, the supervisor:

1. terminates and waits for the complete old Conky generation;
2. recalculates the render interval for the new instance count;
3. preserves validated global and per-head scales;
4. starts exactly one Conky for each active Xinerama head;
5. passes the unchanged style and shared cache path;
6. reapplies and verifies the empty XShape input region for click-through.

The provider is not restarted during hotplug. A failed partial generation is
cleaned up completely. An unexpected Conky exit fails the foreground supervisor
instead of leaving a partial dashboard. Shutdown uses `SIGTERM` first and
escalates to `SIGKILL` only for a child that does not exit within the bounded
grace period.

## Files changed

- `src/bhola_runtime.py` — debounced topology supervision and Conky lifecycle;
- `src/bhola_monitors.py` — complete-snapshot validation with safe startup fallback;
- `scripts/run-dev.sh` — one provider plus one runtime supervisor;
- `scripts/check.sh` — runtime self-check;
- `tests/test_runtime.py` — lifecycle, debounce, click-through failure, and forced-cleanup tests;
- `tests/test_monitors.py` — complete/incomplete snapshot tests;
- `tests/test_layout.py` — ownership contract updated from Bash to the supervisor;
- `README.md` and `docs/architecture.md` — runtime behavior and boundaries.

## Validation

Focused reconstructed validation before the pull request:

- monitor/runtime unit tests: 11/11 passed before the two additional cleanup regressions were added;
- changed Python modules and tests compiled successfully;
- `python3 -m src.bhola_monitors --check` passed;
- `python3 -m src.bhola_runtime --check` passed;
- invalid monitor polling values fail with a bounded CLI error;
- `bash -n scripts/run-dev.sh` passed.

GitHub Actions at implementation commit
`ac7a0e06801779d5d6e0cb1f60e65e04aabb7457`:

- CI run `31055036171`: success;
  - privacy check: success;
  - full standard test suite: success;
  - Debian binary package build: success;
  - package inspection: success;
  - package artifact upload: success;
  - release publication: correctly skipped because the version did not change.
- Debian source package run `31055036196`: success;
  - Noble unsigned PR source build, extraction, binary rebuild, inspection, and artifact upload: success;
  - Resolute unsigned PR source build, extraction, binary rebuild, inspection, and artifact upload: success;
  - released PPA builder correctly remained fail-closed for changed runtime payload;
  - no PPA source was signed or uploaded.

The first workflow generation exposed one stale test that still expected
click-through ownership in the Bash launcher. The implementation was unchanged;
the contract test was corrected to verify delegation in the launcher and the
same PID/title/Xinerama/scale enforcement in the new supervisor. Both workflow
families then passed.

## Privacy and safety review

- no hostname, monitor name, interface name, local path, credential, token, or
  complete public address was added;
- subprocesses use fixed argument arrays and no shell command construction;
- discovery is read-only and bounded by timeout;
- display topology and GNOME settings are never mutated;
- runtime remains unprivileged and user-scoped;
- UFW capabilities and the existing root oneshot are untouched;
- the immutable released PPA payload remains protected from unreleased runtime changes;
- no host, package, service, timer, or session configuration was changed.

## Physical validation required on Bhola

Before any merge decision:

1. run the branch foreground in `modern` with the current monitor set;
2. confirm one provider, one supervisor, and exactly one Conky per active monitor;
3. connect an additional monitor and confirm one stable rebuild without duplicate windows;
4. verify that the provider PID and cache continue unchanged across the rebuild;
5. verify click-through on every new window;
6. disconnect a monitor and confirm the removed-head window disappears without an orphan;
7. repeat connection/disconnection several times, including a quick transient cycle;
8. repeat the complete sequence in `nerd`;
9. confirm render intervals and per-head scale remain correct after each topology count change;
10. inspect CPU and RAM for bounded behavior and absence of accumulating processes;
11. stop with `Ctrl+C` and confirm provider, supervisor, and all Conky children exit;
12. only after those checks decide whether the PR may leave draft status.

## Rollback

No rollback on Bhola is currently required because nothing was deployed. The
repository rollback is to close draft PR `#8` and delete
`agent/dynamic-monitor-hotplug`. `main`, release `v0.1.2`, and the published PPA
remain unchanged.

## Status

Prepared and CI-validated in draft PR `#8`. Not merged, not deployed, not
physically validated, and not approved for production yet.
