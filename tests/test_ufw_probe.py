from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest

from src import bhola_ufw_probe as probe


FIXTURES = Path(__file__).parent / "fixtures" / "ufw"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class UfwRulesetParserTests(unittest.TestCase):
    def classify(self, name: str) -> probe.ProbeEvidence:
        return probe.classify_ruleset(json.loads(fixture_bytes(name)))

    def test_active_ufw_is_reachable_from_real_input_hook(self) -> None:
        self.assertEqual(
            self.classify("active.json"),
            probe.ProbeEvidence("active", True, "verified_runtime_active"),
        )

    def test_ruleset_without_ufw_runtime_is_verified_inactive(self) -> None:
        self.assertEqual(
            self.classify("inactive.json"),
            probe.ProbeEvidence("inactive", True, "verified_runtime_inactive"),
        )

    def test_attached_but_empty_ufw_chain_is_verified_inactive(self) -> None:
        self.assertEqual(
            self.classify("attached-empty-chain.json"),
            probe.ProbeEvidence("inactive", True, "verified_runtime_inactive"),
        )

    def test_ufw_chains_without_active_hook_are_unconfirmed(self) -> None:
        self.assertEqual(
            self.classify("orphan-chains.json"),
            probe.ProbeEvidence("unconfirmed", False, "orphan_ufw_runtime"),
        )

    def test_input_hook_without_ufw_evidence_is_not_active(self) -> None:
        self.assertEqual(
            self.classify("unrelated-input-hook.json"),
            probe.ProbeEvidence("inactive", True, "verified_runtime_inactive"),
        )

    def test_inconsistent_ruleset_is_never_inactive(self) -> None:
        self.assertEqual(
            self.classify("inconsistent.json"),
            probe.ProbeEvidence("unconfirmed", False, "inconsistent_ruleset"),
        )


class UfwProbeCommandTests(unittest.TestCase):
    @staticmethod
    def runner_with(
        stdout: bytes,
        *,
        returncode: int = 0,
    ):
        def runner(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
            if args != list(probe.NFT_COMMAND):
                raise AssertionError(args)
            if kwargs.get("timeout") != probe.NFT_TIMEOUT_SECONDS:
                raise AssertionError(kwargs)
            return subprocess.CompletedProcess(args, returncode, stdout, b"private stderr")

        return runner

    def test_malformed_json_is_error(self) -> None:
        evidence = probe.run_probe(self.runner_with(fixture_bytes("malformed.json")))
        self.assertEqual(evidence, probe.ProbeEvidence("error", False, "invalid_json"))

    def test_empty_output_is_error(self) -> None:
        evidence = probe.run_probe(self.runner_with(b""))
        self.assertEqual(evidence, probe.ProbeEvidence("error", False, "empty_output"))

    def test_timeout_is_error(self) -> None:
        def timeout(*_args: object, **_kwargs: object):
            raise subprocess.TimeoutExpired(list(probe.NFT_COMMAND), 3.0)

        self.assertEqual(
            probe.run_probe(timeout),
            probe.ProbeEvidence("error", False, "timeout"),
        )

    def test_nonzero_exit_is_sanitized_error(self) -> None:
        evidence = probe.run_probe(self.runner_with(b"secret output", returncode=1))
        self.assertEqual(evidence, probe.ProbeEvidence("error", False, "command_failed"))
        self.assertNotIn("secret", evidence.detail)

    def test_oversized_output_is_error(self) -> None:
        output = b" " * (probe.MAX_NFT_OUTPUT_BYTES + 1)
        evidence = probe.run_probe(self.runner_with(output))
        self.assertEqual(evidence, probe.ProbeEvidence("error", False, "oversized_output"))

    def test_missing_program_is_error(self) -> None:
        def missing(*_args: object, **_kwargs: object):
            raise FileNotFoundError

        self.assertEqual(
            probe.run_probe(missing),
            probe.ProbeEvidence("error", False, "program_missing"),
        )


class UfwStateWriterTests(unittest.TestCase):
    def state(self, observed: int = 100) -> dict[str, object]:
        return probe.build_state(
            probe.ProbeEvidence("active", True, "verified_runtime_active"),
            "enabled",
            observed,
        )

    def test_atomic_write_replaces_complete_file_and_leaves_no_temporary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory) / "bhola-pulse"
            runtime.mkdir(mode=0o755)
            target = runtime / "ufw-status.json"
            target.write_text("old", encoding="utf-8")
            old_inode = target.stat().st_ino

            probe.atomic_write_state(self.state(), target, trusted_uid=os.geteuid())

            self.assertNotEqual(target.stat().st_ino, old_inode)
            self.assertEqual(json.loads(target.read_text(encoding="ascii")), self.state())
            self.assertEqual(list(runtime.glob(".ufw-status.*")), [])
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o644)

    def test_state_json_is_minimal_private_and_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory) / "bhola-pulse"
            runtime.mkdir(mode=0o755)
            target = runtime / "ufw-status.json"
            probe.atomic_write_state(self.state(), target, trusted_uid=os.geteuid())
            content = target.read_text(encoding="ascii")

        self.assertLessEqual(len(content.encode("ascii")), probe.MAX_STATE_BYTES)
        self.assertEqual(
            set(json.loads(content)),
            {
                "schema_version",
                "observed_at_epoch",
                "config",
                "runtime",
                "verified",
                "source",
                "detail",
            },
        )
        for forbidden in ("ruleset", "stderr", "stdout", "address", "port", "interface", "hostname"):
            self.assertNotIn(forbidden, content.lower())

    def test_rejects_writable_runtime_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory) / "bhola-pulse"
            runtime.mkdir(mode=0o777)
            runtime.chmod(0o777)
            with self.assertRaises(OSError):
                probe.atomic_write_state(
                    self.state(),
                    runtime / "ufw-status.json",
                    trusted_uid=os.geteuid(),
                )

    def test_probe_accepts_no_arguments(self) -> None:
        self.assertEqual(probe.main(["bhola-pulse-ufw-probe", "unexpected"]), 2)


if __name__ == "__main__":
    unittest.main()
