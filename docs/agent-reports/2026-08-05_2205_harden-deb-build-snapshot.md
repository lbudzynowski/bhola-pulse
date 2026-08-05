# Harden committed-source Debian build snapshot

## Session metadata

- Date: 2026-08-05 22:05 CEST (Europe/Warsaw)
- Repository: `lbudzynowski/bhola-pulse`
- Branch: `agent/verified-ufw-runtime-probe`
- Previous HEAD: `a8f3b4599d057f613fd50393246c21451c49b2c5`
- Implementation HEAD: `f30619010a837ede526e81936ccd66d3143ad564`
- Pull request: draft PR #5, `Add verified UFW runtime probe`
- Functional and Debian versions: `0.1.2` and `0.1.2-1` (unchanged)

## Risk and previous behavior

`scripts/build-deb.sh` previously constructed its temporary source directory by
piping a tar archive of the current filesystem worktree into another tar
process. A manual exclusion list removed `.git`, `build`, `dist`, Python cache
files, and one generated Debian directory. It did not establish a complete
trust boundary: an untracked, non-ignored local file outside that list could
have entered the source directory and subsequently the package build.

The old implementation also created the output directory before proving that
the source state was clean. The risk was limited to the package builder; the
UFW probe, nftables parser, collector, systemd units, capability model, timer,
status mapping, dependencies, release pin, and PPA builder were not changed in
this session.

## New snapshot source and fail-closed boundary

The builder now resolves the project root from its own script location and
requires Git to report that exact directory as the top level of a non-bare
worktree. It resolves `HEAD^{commit}` once and uses the resulting immutable SHA
as the sole input to:

```text
git -C PROJECT_ROOT -c tar.umask=0022 archive --format=tar --prefix=source/ HEAD_SHA
```

The archive is extracted into a temporary directory with ownership inherited
from the unprivileged build user. `VERSION` and `debian/changelog` are read from
that extracted committed snapshot, not from the live worktree. The binary and
`SHA256SUMS` are installed into the selected output directory with mode `0644`.

Before creating an output directory or temporary build directory, copying or
extracting source, or running packaging tools, the builder requires all of the
following:

1. a valid Git worktree rooted exactly at the project directory;
2. a valid commit object at `HEAD`;
3. a successful `git status --porcelain=v1 --untracked-files=all` query;
4. completely empty output from that status query.

Any Git error, diagnostic output, staged change, modified/deleted tracked file,
or untracked non-ignored file causes refusal. An untracked non-ignored
directory is rejected when it contains a filesystem entry, which is the state
Git can represent. Ignored files do not make status dirty, but cannot enter the
snapshot because `git archive` reads only the selected commit. The builder does
not copy the worktree and does not rely on `.gitignore` as its packaging filter.

## Regression tests and synthetic markers

`tests/test_build_deb_snapshot.py` creates a new temporary Git repository for
each scenario. It uses fake, non-privileged package tools to observe the exact
temporary source tree and package input without installing software or
modifying the real checkout. Ten behavioral tests cover:

- acceptance of a clean committed HEAD and equality between tracked files and
  snapshot files;
- absence of `.git`, correct versioned package path, and valid `SHA256SUMS`;
- refusal for a modified tracked file;
- refusal for a staged change;
- refusal for an untracked file and an untracked directory before `.deb`
  creation;
- exclusion of an ignored local file while allowing an otherwise clean build;
- invocation from a different current directory without importing its files;
- refusal without a valid HEAD and outside a Git repository;
- absence of a whole-worktree-copy fallback.

The untracked-file test creates the exact runtime marker formed as
`BHOLA_LOCAL_` plus `SECRET_MUST_NOT_PACKAGE`. The builder refuses, leaves the
source file unchanged, and creates neither capture nor package artifacts. The
ignored-file test uses a separate marker formed as `BHOLA_IGNORED_LOCAL_` plus
`SECRET_MUST_NOT_PACKAGE`; the build succeeds, but the marker is absent from
the captured source directory, source archive, generated test package, and
checksum output. Splitting the literals here and in the test source prevents
the regression marker itself from becoming committed package input.

Artifact leak checks covered the captured source file list, captured source
directory, captured source tar archive, generated test package, checksum
output, CI-built binary package, extracted CI payload, and extracted Debian
control scripts. The synthetic untracked marker and `.git` were absent from the
CI artifact validation tree.

## Local validation

- `bash scripts/check.sh`: passed; 126 tests, provider check, compile check,
  privacy check, and shell syntax checks passed.
- `python3 -m unittest discover -s tests -v`: passed; 126 tests.
- `python3 scripts/privacy-check.py`: passed; 70 tracked files scanned.
- `python3 scripts/privacy-check.py tests/test_build_deb_snapshot.py`: passed.
- `bash -n` for all repository shell entrypoints: passed.
- `git diff --check`: passed.
- Static scan of `scripts/build-deb.sh` for whole-worktree tar/copy/rsync
  patterns: passed.
- Isolated builder regression suite: 10 tests passed.

The host does not provide `dh`. No package was installed to fill that gap, so a
local real Debian build stopped safely with `Missing package build command:
dh` before producing artifacts. A fresh GitHub Actions checkout performed the
real binary build and all package inspections described below.

## Implementation CI and package inspection

All workflows for implementation HEAD
`f30619010a837ede526e81936ccd66d3143ad564` succeeded:

- CI push run `31042211704`: standard checks, real binary build, payload and
  maintainer-script inspection, checksum verification, and artifact upload
  passed; release job skipped.
- CI pull-request run `31042212452`: the same binary validation passed; release
  job skipped.
- Debian source package run `31042212731`: Noble and Resolute source package
  build, extraction, binary rebuild, inspection, and pinned PPA fail-closed
  proof passed.
- Remote deployment safety run `31042212587`: passed.

The downloaded CI artifact contained
`bhola-pulse_0.1.2-1_all.deb` and `SHA256SUMS`. The checksum passed. Package
metadata was `Package: bhola-pulse`, `Version: 0.1.2-1`, and `Architecture:
all`. The extracted payload contained 27 regular files with the expected probe,
systemd units, application, configuration, renderers, and documentation. Probe
and launchers were mode `0755`; data, documentation, and units were mode
`0644`. Generated `postinst`, `prerm`, and `postrm` scripts contained the
expected debhelper timer lifecycle hooks.

## Changed files

- `scripts/build-deb.sh`
- `tests/test_build_deb_snapshot.py`
- `docs/agent-reports/2026-08-05_2205_harden-deb-build-snapshot.md` (this report)

## Limits and rollback

The real binary package was built in GitHub Actions rather than locally because
the host lacks `dh`. The behavioral builder tests remain fully local and do not
need Debian packaging tools. Source-package validation uses the separate
`debian/build-pr-source` path; both supported Ubuntu series still passed in CI.

Rollback is a normal revert of the implementation commit and this report
commit. No host state must be undone because the package was not installed.

## Explicit non-actions

- No package was installed or removed on the host.
- No host files, UFW rules, nftables rules, systemd units, capabilities, or
  services were changed.
- No tag, GitHub Release, signature, `dput`, PPA upload, or package publication
  was performed.
- The existing draft PR was not merged or marked ready.
- The release and PPA pinning policy was not changed.
