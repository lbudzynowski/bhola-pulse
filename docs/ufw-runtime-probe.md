# Verified UFW runtime probe

## Purpose and data flow

An enabled `/etc/ufw/ufw.conf` proves configuration intent, not that UFW rules
are attached to the running nftables input path. An ordinary user cannot verify
the host ruleset. Bhola Pulse therefore separates the privilege boundary:

```text
systemd root oneshot with CAP_NET_ADMIN
  -> /usr/sbin/nft --json list ruleset (memory only, 3 s timeout)
  -> structural parser
  -> atomic root-owned /run/bhola-pulse/ufw-status.json
  -> unprivileged Bhola Pulse collector
```

The dashboard, launcher, Python provider, and `nft` binary receive no file
capabilities, setuid bit, Polkit permission, or sudoers rule. There is no socket,
D-Bus API, user-selected command, or probe argument. The probe uses fixed
absolute paths and does not invoke a shell.

## Runtime evidence

The parser consumes nft JSON in memory. It builds a chain graph, identifies
strictly named UFW-managed chains and `jump`/`goto` edges, and proves whether a
UFW chain is reachable from a real nftables base chain whose hook is `input`.
It does not use a single text substring. Results are:

- `active`: a structurally valid input hook reaches a declared UFW chain that
  contains runtime rules;
- `inactive`: a valid complete ruleset has no UFW runtime path, or its attached
  UFW path contains no runtime rules;
- `unconfirmed`: UFW artifacts are orphaned or the graph is inconsistent;
- `error`: command failure, timeout, missing program, empty/oversized output,
  or invalid JSON.

Empty, malformed, oversized, or inconsistent input is never classified as
`inactive`. Full stdout and stderr are neither logged nor persisted.

## Runtime state schema

The state file is ASCII JSON, at most 4096 bytes, and currently contains only:

```json
{
  "schema_version": 1,
  "observed_at_epoch": 0,
  "config": "enabled",
  "runtime": "active",
  "verified": true,
  "source": "nftables",
  "detail": "verified_runtime_active"
}
```

Every string value is validated against a closed enumeration. `detail` is the
only extension to the minimal schema; it is required to distinguish verified
evidence from a sanitized timeout, command, parser, or consistency failure.
The file contains no ruleset, stdout, stderr, address, port, interface, comment,
counter, hostname, username, machine identifier, secret, or home path.

The probe creates a mode `0644` temporary file in the same root-owned mode
`0755` runtime directory, flushes and fsyncs it, applies its mode, replaces the
target with `os.replace()`, and fsyncs the directory. Ordinary users can read
but cannot change either the directory or file. `RuntimeDirectoryPreserve=yes`
keeps the result after the oneshot exits; `/run` remains volatile across boot.

## Collector trust checks and status mapping

Before opening the file, the collector uses `lstat()` on the parent and target.
It rejects symlinks, non-regular files, additional hard links, unexpected
owners, group/world-writable modes, empty/oversized files, inode changes during
open, partial reads, invalid JSON, extra or missing fields, wrong schema or
enums, inconsistent `verified` values, future timestamps, and observations
older than 120 seconds. The open uses `O_NOFOLLOW`, and `fstat()` must match the
earlier `lstat()`.

The visible mapping is:

| Configuration and trusted evidence | Status | Confidence | Detail |
| --- | --- | --- | --- |
| disabled | `off` | high | `config_disabled` |
| enabled + fresh verified `active` | `ok` | high | `verified_runtime_active` |
| enabled + fresh verified `inactive` | `degraded` | high | `verified_runtime_inactive` |
| missing state | `unknown` | low | `probe_missing` |
| state older than 120 seconds | `unknown` | low | `probe_stale` |
| unsafe or invalid state | `unknown` | low | `probe_invalid` |
| timeout or command/parser failure | `unknown` | low | `probe_error` |
| orphaned or inconsistent UFW evidence | `unknown` | low | `probe_unconfirmed` |

Thus a developer checkout without the installed system probe remains safe and
shows `unknown`. Permission denial is not evidence that the firewall is broken.

## Privilege boundary and service sandbox

`bhola-pulse-ufw-probe.service` is a root `Type=oneshot` service whose capability
bounding set contains only `CAP_NET_ADMIN`. It keeps the host network namespace
because nftables state is namespace-specific; `PrivateNetwork=yes` would inspect
the wrong ruleset and is intentionally absent. It permits only `AF_UNIX` and
`AF_NETLINK`, denies Internet addresses, makes the OS read-only except for
`/run/bhola-pulse`, protects home, devices, kernel interfaces, control groups,
logs, clock and hostname, blocks new privileges and executable writable memory,
restricts namespaces, SUID/SGID, realtime and syscall classes, and has a
10-second service timeout. The internal nft timeout is three seconds.

The timer first fires about 15–20 seconds after boot and then about every 45–50
seconds. systemd does not start a second instance while the oneshot is active;
there is no network-online dependency, persistence catch-up, or retry loop.

## Validation after a later package installation

Installation is intentionally outside repository validation. After installing
a signed and checksum-verified package, validate without displaying the host
ruleset:

```bash
systemctl status bhola-pulse-ufw-probe.timer --no-pager
systemctl list-timers bhola-pulse-ufw-probe.timer --no-pager
systemctl show bhola-pulse-ufw-probe.service \
  -p CapabilityBoundingSet -p NoNewPrivileges -p PrivateNetwork
systemd-analyze verify /lib/systemd/system/bhola-pulse-ufw-probe.service \
  /lib/systemd/system/bhola-pulse-ufw-probe.timer
systemd-analyze security bhola-pulse-ufw-probe.service --no-pager
stat -Lc '%U:%G %a %F %s' /run/bhola-pulse/ufw-status.json
bhola-pulse --check
```

Expected ownership and modes are `root:root 755` for the runtime directory and
`root:root 644` for the state file. Inspect only the enumerated summary, never
publish the real ruleset.

## Deployment and rollback

For a later deployment, first verify the release tag, package checksum and
package payload; record the currently installed version; install the 0.1.2-1
package with APT; confirm the debhelper-enabled timer; wait for two successful
intervals; run the checks above; and confirm Bhola Pulse maps a fresh verified
result correctly. Do not change UFW rules as part of this rollout.

Rollback uses the previously verified 0.1.1 package:

```bash
sudo apt install ./bhola-pulse_0.1.1_all.deb
systemctl status bhola-pulse-ufw-probe.timer --no-pager
bhola-pulse --check
```

The new package's debhelper-generated removal scripts stop and disable the timer
during downgrade/removal. The old collector ignores any volatile summary left
under `/run`; it disappears on reboot. For full removal use `sudo apt purge
bhola-pulse`. Rollback changes the Bhola Pulse package only and must not alter
UFW or nftables policy.
