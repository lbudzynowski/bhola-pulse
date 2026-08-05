# Deploy Bhola Pulse 0.1.2

## Result

- Date: 2026-08-05 23:08 CEST (Europe/Warsaw)
- Repository: `lbudzynowski/bhola-pulse` (public)
- Branch: `agent/deploy-bhola-pulse-0.1.2`
- Base SHA: `009ca2331f2a14159f26a31fe7fa193859676750`
- Outcome: successful deployment of Debian package `0.1.2-1`
- Rollback: prepared and verified, not executed
- Firewall policy changes: none

The fresh `origin/main` contained merge commit
`009ca2331f2a14159f26a31fe7fa193859676750` from PR #5 and reported
`VERSION=0.1.2`. The deployment branch was created directly from that commit,
with a clean worktree before this report was added.

## Release and artifact verification

Release `v0.1.2` existed, was neither a draft nor a prerelease, and its tag
dereferenced exactly to `009ca2331f2a14159f26a31fe7fa193859676750`.
The release contained exactly two uploaded assets:

- `bhola-pulse_0.1.2-1_all.deb`
- `SHA256SUMS`

Both files were downloaded with `gh release download` into a new private
temporary directory with mode `0700`. `sha256sum --check SHA256SUMS` passed.
The package checksum was:

```text
ae425a74fedcae0eecc289075b9c0347b8efab87792d3b24eb092b332055661c  bhola-pulse_0.1.2-1_all.deb
```

Package metadata was `Package: bhola-pulse`, `Version: 0.1.2-1`, and
`Architecture: all`. The non-empty payload contained the launcher, the root
UFW probe, and both systemd units. The launcher and probe were mode `0755`;
the service and timer were mode `0644`. Generated `postinst`, `prerm`, and
`postrm` scripts contained debhelper timer lifecycle hooks. Package md5
verification passed. Static scans found no home-directory paths, local account
name, `.git`, secrets, setuid files, or build artifacts.

The installed probe contains only the read-only command vector
`/usr/sbin/nft --json list ruleset`. Its stdout is parsed in memory and is
never emitted by the service. No mutating UFW, nftables, iptables, capability,
sudoers, or Polkit operation is present in the package lifecycle or probe.

## Rollback preparation

Release `v0.1.1` existed, was neither a draft nor a prerelease, and its tag
dereferenced to `5f2620aac97ca3a60377babab6929791f73ad6a1`. Its uploaded rollback
assets were downloaded through GitHub Release into a separate private
subdirectory:

- `bhola-pulse_0.1.1_all.deb`
- `SHA256SUMS`

Checksum verification passed:

```text
6ff8800a610905670f3c63bc47a4878d468af23f8b04e43ef708e515648d7a6d  bhola-pulse_0.1.1_all.deb
```

Rollback metadata was `Package: bhola-pulse`, `Version: 0.1.1`, and
`Architecture: all`. After deployment, an APT simulation confirmed a
package-only downgrade from `0.1.2-1` to `0.1.1`, with no other install,
removal, kernel, network, UFW, or nftables transaction.

The 0.1.1 payload contains no UFW probe units. One lifecycle caveat was found:
the generated 0.1.2 `prerm` explicitly stops the units for `remove`, while a
dpkg downgrade normally uses the `upgrade` maintainer-script path. Therefore a
real rollback must explicitly confirm that the timer is inactive and disabled;
if it is not, it must be stopped and disabled before `daemon-reload` and the
unprivileged dashboard restart. This is an operational verification step, not
a firewall-policy change. No rollback was performed because the deployed
version remained healthy.

No `.deb` file was copied into the repository.

## State before installation

- dpkg package: installed and managed by dpkg
- dpkg version: `0.1.1-1~ppa1~noble1`
- CLI version: `Bhola Pulse 0.1.1`
- saved style: `modern` (default source)
- dashboard launcher: not running; no existing launch mechanism was observable
- Bhola Pulse provider processes: `0`
- Bhola Pulse Conky processes: `0`
- UFW probe service: not found
- UFW probe timer: not found
- `bhola-pulse --check`: passed

Because no Bhola Pulse process was running, no signal was sent before
installation and no unrelated Conky process was touched.

## Installation and installed-file validation

The pre-install APT simulation proposed exactly one upgrade: `bhola-pulse`
from `0.1.1-1~ppa1~noble1` to `0.1.2-1`. The interactive APT installation then
completed under the authorized root session.

Post-install results:

- dpkg version: `0.1.2-1`
- CLI version: `Bhola Pulse 0.1.2`
- dpkg package state: `install ok installed`
- `dpkg --verify bhola-pulse`: no differences
- `/usr/bin/bhola-pulse`: root-owned regular file, mode `0755`
- `/usr/lib/bhola-pulse/bhola-pulse-ufw-probe`: root-owned regular file, mode `0755`
- system service and timer: root-owned regular files in the system unit directory, mode `0644`
- probe interpreter: `/usr/bin/python3`
- file capabilities: none
- setuid/setgid package files: none

## systemd probe and security model

The timer was `enabled` and `active`. The oneshot service was inactive after
each completed measurement, with `Result=success` and `ExecMainStatus=0`.
Status was inspected without journal lines.

The effective service model was:

```text
User=root
Group=root
Type=oneshot
CapabilityBoundingSet=cap_net_admin
NoNewPrivileges=yes
PrivateNetwork=no
RestrictAddressFamilies=AF_NETLINK AF_UNIX
ReadWritePaths=/run/bhola-pulse
RuntimeDirectory=bhola-pulse
RuntimeDirectoryPreserve=yes
```

`systemd-analyze verify` returned success for both Bhola Pulse units. It also
reported two pre-existing parse warnings from an unrelated ASUS unit; these
did not affect Bhola Pulse. `systemd-analyze security` reported overall
exposure `1.4 OK`. A controlled root start of the installed read-only oneshot
completed successfully and refreshed the state timestamp.

## Minimal UFW state

The runtime directory was a real root-owned directory with mode `0755`. The
state was a root-owned regular file with mode `0644`, one hardlink, no symlink,
and size `161` bytes. Its keys matched the exact seven-field schema; no extra
field, address, port, interface, comment, counter, host/account identifier, or
home-directory path was present.

One final validated sample was:

```json
{
  "schema_version": 1,
  "observed_at_epoch": 1785964089,
  "config": "enabled",
  "runtime": "active",
  "verified": true,
  "source": "nftables",
  "detail": "verified_runtime_active"
}
```

This is the expected success result for enabled UFW. No full nftables ruleset
was displayed, logged, copied into this report, or published.

## Dashboard and cache

The saved `modern` style was preserved. Since no prior dashboard instance or
autostart mechanism was running, the installed `bhola-pulse` launcher was
started as the ordinary desktop user. The execution transport cleans up child
processes when a command session closes, so two otherwise successful direct
starts ended with their sessions. Their sanitized logs showed successful
provider checks, three Conky starts, and click-through verification with no
error marker. No overlapping instance remained.

The stable launch uses the same installed launcher in a transient, collectible
user systemd unit. Output is identity-redacted before it reaches a user-state
log with mode `0600`. This did not change saved configuration or install a
persistent user unit. Final process state was:

- launcher: `1`, ordinary user
- provider: `1`, ordinary user
- Bhola Pulse Conky instances: `3` of `3` expected, ordinary user
- transient dashboard unit: active
- crash loop: none
- `bhola-pulse --check`: passed

The fresh dashboard cache contained:

```json
{
  "service_ufw": "ok",
  "service_ufw_config": "enabled",
  "service_ufw_runtime": "active",
  "service_ufw_detail": "verified_runtime_active",
  "service_ufw_confidence": "high"
}
```

The renderer presents the `ok` value as `ACTIVE`, so the visible dashboard
status is `UFW ACTIVE`. It is semantically the requested UFW OK state, but the
literal text is not `UFW OK`.

## Timer intervals

The controlled-start baseline and subsequent timer observations were:

```text
1785963889 -> 1785963938 -> 1785963985 -> 1785964035 -> 1785964089
```

At least two complete approximately 45-second intervals renewed the timestamp.
The timer remained active and re-armed, the oneshot repeatedly returned
success, the state stayed below the 120-second stale limit, and the dashboard
cache remained fresh and correct. One validation sampled the exact transition
while the service was `activating`; the next read confirmed a successful new
timestamp rather than a stale-state or error loop.

## Checks completed

- GitHub authentication, origin, public visibility, fresh main, merge SHA, and version
- release draft/prerelease/tag/asset-name/asset-state checks for 0.1.2 and 0.1.1
- both SHA256 checksum files
- package metadata, payload paths, modes, control scripts, md5sums, and privacy scan
- pre-install and rollback APT simulations
- installed dpkg/CLI versions and dpkg integrity
- capabilities, setuid/setgid, interpreter, unit ownership, and unit location
- systemd enabled/active/status/show/verify/security validation
- controlled read-only probe start
- exact state-file type, ownership, permissions, link count, size, schema, enums, and freshness
- dashboard process counts, cache values, renderer mapping, log health, and `--check`
- more than two timer refresh intervals

## Rollback and explicit non-actions

Rollback was not executed. The verified rollback package remains outside the
repository in the private deployment temporary directory for this session.

- No UFW rule was enabled, disabled, reset, reloaded, added, denied, or deleted.
- No nftables rule was added, deleted, replaced, flushed, reset, or monitored.
- No privileged manual full-ruleset command was executed.
- No full ruleset was displayed, logged, reported, or published.
- No file capability, sudoers entry, or Polkit rule was added.
- No unrelated Conky or Python process was signalled.
- No user data or saved style was removed or changed.
- The dashboard runs as an ordinary user, never as root.
- No branch was deleted, and no pull request was merged or marked ready.
