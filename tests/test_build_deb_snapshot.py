from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILDER = PROJECT_ROOT / "scripts/build-deb.sh"
UNTRACKED_MARKER = "BHOLA_LOCAL_" + "SECRET_MUST_NOT_PACKAGE"
IGNORED_MARKER = "BHOLA_IGNORED_LOCAL_" + "SECRET_MUST_NOT_PACKAGE"

FAKE_DPKG_BUILDPACKAGE = r"""#!/usr/bin/env python3
from pathlib import Path
import os
import re
import shutil
import tarfile

source_root = Path.cwd()
capture_root = Path(os.environ["BHOLA_TEST_CAPTURE_DIR"])
capture_root.mkdir(parents=True, exist_ok=False)
captured_source = capture_root / "source-root"
shutil.copytree(source_root, captured_source, symlinks=True)

paths = sorted(source_root.rglob("*"))
files = [path.relative_to(source_root).as_posix() for path in paths if path.is_file()]
(capture_root / "snapshot-files.txt").write_text("\n".join(files) + "\n", encoding="utf-8")
with tarfile.open(capture_root / "source-snapshot.tar", "w") as archive:
    for path in paths:
        archive.add(path, arcname=path.relative_to(source_root), recursive=False)

changelog = (source_root / "debian/changelog").read_text(encoding="utf-8")
match = re.match(r"bhola-pulse \(([^)]+)\)", changelog)
if match is None:
    raise SystemExit("invalid test changelog")
package_version = match.group(1)
deb_path = source_root.parent / f"bhola-pulse_{package_version}_all.deb"
with tarfile.open(deb_path, "w") as archive:
    for path in paths:
        archive.add(
            path,
            arcname=Path("payload") / path.relative_to(source_root),
            recursive=False,
        )
"""


class BuildDebSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.test_root = Path(self.temporary.name)
        self.repo = self.test_root / "repo"
        self.fake_bin = self.test_root / "fake-bin"
        self.capture = self.test_root / "capture"
        self.repo.mkdir()
        self.fake_bin.mkdir()
        self._write_fake_tools()
        self._create_committed_fixture()

    def _git(
        self,
        *arguments: str,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *arguments],
            cwd=cwd or self.repo,
            check=True,
            capture_output=True,
            text=True,
        )

    def _write_executable(self, path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)

    def _write_fake_tools(self) -> None:
        self._write_executable(
            self.fake_bin / "dpkg-buildpackage",
            FAKE_DPKG_BUILDPACKAGE,
        )
        harmless_tool = "#!/bin/sh\nexit 0\n"
        self._write_executable(self.fake_bin / "dpkg-deb", harmless_tool)
        self._write_executable(self.fake_bin / "dh", harmless_tool)

    def _create_project_files(self, root: Path) -> None:
        (root / "scripts").mkdir(parents=True, exist_ok=True)
        (root / "src").mkdir(parents=True, exist_ok=True)
        (root / "debian").mkdir(parents=True, exist_ok=True)
        shutil.copy2(BUILDER, root / "scripts/build-deb.sh")
        (root / "VERSION").write_text("0.1.2\n", encoding="utf-8")
        (root / ".gitignore").write_text(
            "dist/\nbuild/\n/config/local-secret.txt\n",
            encoding="utf-8",
        )
        (root / "src/tracked.py").write_text(
            'VALUE = "committed-source"\n',
            encoding="utf-8",
        )
        (root / "debian/changelog").write_text(
            "bhola-pulse (0.1.2-1) UNRELEASED; urgency=medium\n\n"
            "  * Test committed-source package build.\n\n"
            " -- Test Builder <builder@example.invalid>  Wed, 05 Aug 2026 12:00:00 +0200\n",
            encoding="utf-8",
        )

    def _create_committed_fixture(self) -> None:
        self._create_project_files(self.repo)
        self._git("init", "--quiet", "--initial-branch=main")
        self._git("config", "user.name", "Bhola Test")
        self._git("config", "user.email", "builder@example.invalid")
        self._git("add", ".")
        self._git("commit", "--quiet", "-m", "fixture")

    def _environment(self, capture: Path | None = None) -> dict[str, str]:
        environment = os.environ.copy()
        environment["PATH"] = f"{self.fake_bin}{os.pathsep}{environment['PATH']}"
        environment["BHOLA_TEST_CAPTURE_DIR"] = str(capture or self.capture)
        return environment

    def _run_builder(
        self,
        *,
        cwd: Path | None = None,
        repo: Path | None = None,
        capture: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        selected_repo = repo or self.repo
        return subprocess.run(
            [str(selected_repo / "scripts/build-deb.sh")],
            cwd=cwd or selected_repo,
            env=self._environment(capture),
            capture_output=True,
            text=True,
            check=False,
        )

    def _snapshot_files(self) -> set[str]:
        return set(
            (self.capture / "snapshot-files.txt").read_text(encoding="utf-8").splitlines()
        )

    def _tracked_files(self) -> set[str]:
        return set(self._git("ls-files").stdout.splitlines())

    def _assert_marker_absent_from_artifacts(self, marker: str) -> None:
        encoded = marker.encode()
        for root in (self.capture, self.repo / "dist"):
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if path.is_file():
                    self.assertNotIn(encoded, path.read_bytes(), str(path))

    def test_clean_committed_head_builds_complete_snapshot_and_checksum(self) -> None:
        completed = self._run_builder()

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(self._snapshot_files(), self._tracked_files())
        self.assertFalse(
            any(
                part == ".git"
                for path in self._snapshot_files()
                for part in Path(path).parts
            )
        )
        deb = self.repo / "dist/bhola-pulse_0.1.2-1_all.deb"
        checksum = self.repo / "dist/SHA256SUMS"
        self.assertTrue(deb.is_file())
        self.assertTrue(checksum.is_file())
        expected_digest = hashlib.sha256(deb.read_bytes()).hexdigest()
        self.assertEqual(
            checksum.read_text(encoding="utf-8"),
            f"{expected_digest}  {deb.name}\n",
        )
        with tarfile.open(deb) as archive:
            payload_names = set(archive.getnames())
        self.assertIn("payload/VERSION", payload_names)
        self.assertIn("payload/scripts/build-deb.sh", payload_names)
        self.assertNotIn("payload/.git", payload_names)

    def test_modified_tracked_file_is_rejected_before_artifacts(self) -> None:
        tracked = self.repo / "src/tracked.py"
        tracked.write_text('VALUE = "modified"\n', encoding="utf-8")

        completed = self._run_builder()

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("clean worktree", completed.stderr)
        self.assertFalse((self.repo / "dist").exists())
        self.assertFalse(self.capture.exists())

    def test_staged_change_is_rejected_before_artifacts(self) -> None:
        tracked = self.repo / "src/tracked.py"
        tracked.write_text('VALUE = "staged"\n', encoding="utf-8")
        self._git("add", "src/tracked.py")

        completed = self._run_builder()

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("clean worktree", completed.stderr)
        self.assertFalse((self.repo / "dist").exists())
        self.assertFalse(self.capture.exists())

    def test_untracked_secret_is_rejected_preserved_and_never_packaged(self) -> None:
        secret_path = self.repo / "src/local-secret.txt"
        secret_path.write_text(UNTRACKED_MARKER, encoding="utf-8")

        completed = self._run_builder()

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("clean worktree", completed.stderr)
        self.assertEqual(secret_path.read_text(encoding="utf-8"), UNTRACKED_MARKER)
        self.assertFalse((self.repo / "dist").exists())
        self.assertFalse(self.capture.exists())
        self._assert_marker_absent_from_artifacts(UNTRACKED_MARKER)

    def test_untracked_directory_is_rejected_before_artifacts(self) -> None:
        local_directory = self.repo / "conky/local-only"
        local_directory.mkdir(parents=True)
        (local_directory / "note.txt").write_text("local-only", encoding="utf-8")

        completed = self._run_builder()

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("clean worktree", completed.stderr)
        self.assertFalse((self.repo / "dist").exists())
        self.assertFalse(self.capture.exists())

    def test_ignored_local_file_is_not_snapshotted_or_packaged(self) -> None:
        ignored_path = self.repo / "config/local-secret.txt"
        ignored_path.parent.mkdir()
        ignored_path.write_text(IGNORED_MARKER, encoding="utf-8")
        status = self._git("status", "--porcelain=v1", "--untracked-files=all").stdout
        self.assertEqual(status, "")

        completed = self._run_builder()

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertNotIn("config/local-secret.txt", self._snapshot_files())
        self.assertFalse((self.capture / "source-root/config/local-secret.txt").exists())
        self.assertEqual(ignored_path.read_text(encoding="utf-8"), IGNORED_MARKER)
        self._assert_marker_absent_from_artifacts(IGNORED_MARKER)

    def test_invocation_outside_repo_uses_script_project_and_not_cwd(self) -> None:
        outside = self.test_root / "outside"
        outside.mkdir()
        outside_marker = outside / "local-secret.txt"
        outside_marker.write_text(UNTRACKED_MARKER, encoding="utf-8")

        completed = self._run_builder(cwd=outside)

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(self._snapshot_files(), self._tracked_files())
        self.assertTrue((self.repo / "dist/bhola-pulse_0.1.2-1_all.deb").is_file())
        self.assertEqual(outside_marker.read_text(encoding="utf-8"), UNTRACKED_MARKER)
        self._assert_marker_absent_from_artifacts(UNTRACKED_MARKER)

    def test_repository_without_head_fails_before_artifacts(self) -> None:
        headless_repo = self.test_root / "headless"
        headless_repo.mkdir()
        self._create_project_files(headless_repo)
        self._git("init", "--quiet", "--initial-branch=main", cwd=headless_repo)
        capture = self.test_root / "headless-capture"

        completed = self._run_builder(repo=headless_repo, capture=capture)

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("valid committed HEAD", completed.stderr)
        self.assertFalse((headless_repo / "dist").exists())
        self.assertFalse(capture.exists())

    def test_directory_outside_git_repository_fails_before_artifacts(self) -> None:
        non_repo = self.test_root / "not-a-repo"
        non_repo.mkdir()
        self._create_project_files(non_repo)
        capture = self.test_root / "non-repo-capture"

        completed = self._run_builder(repo=non_repo, capture=capture)

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("valid Git worktree", completed.stderr)
        self.assertFalse((non_repo / "dist").exists())
        self.assertFalse(capture.exists())

    def test_builder_has_no_whole_worktree_copy_fallback(self) -> None:
        builder = BUILDER.read_text(encoding="utf-8")
        self.assertIn("archive", builder)
        for forbidden in ("-cf - .", "cp -a .", "rsync"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, builder)


if __name__ == "__main__":
    unittest.main()
