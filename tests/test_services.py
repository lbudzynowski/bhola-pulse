from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from src.bhola_services import ServiceCollector, UFW_STATE_MAX_BYTES


UNIT_OUTPUT = """Id=asus_touchpad_numpad.service
LoadState=loaded
ActiveState=active
SubState=running
UnitFileState=enabled

Id=ntfy-flush.service
LoadState=loaded
ActiveState=inactive
SubState=dead
UnitFileState=static

Id=ntfy-flush.timer
LoadState=loaded
ActiveState=active
SubState=waiting
UnitFileState=enabled
"""


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.proc = self.root / "proc"
        self.etc = self.root / "etc"
        self.runtime = self.root / "run" / "bhola-pulse"
        self.proc.mkdir()
        (self.etc / "ufw").mkdir(parents=True)
        self.runtime.mkdir(parents=True, mode=0o755)
        self.state_path = self.runtime / "ufw-status.json"
        self.now = 1_800_000_000
        self.commands: list[list[str]] = []

    def runner(self, args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        self.commands.append(args)
        if args and args[0].endswith("nft"):
            return subprocess.CompletedProcess(args, 1, "", "permission denied")
        return subprocess.CompletedProcess(args, 0, UNIT_OUTPUT, "")

    def set_config(self, value: str = "yes") -> None:
        (self.etc / "ufw" / "ufw.conf").write_text(
            f"ENABLED={value}\n", encoding="utf-8"
        )

    def state(
        self,
        *,
        runtime: str = "active",
        verified: bool = True,
        detail: str = "verified_runtime_active",
        observed: int | None = None,
        config: str = "enabled",
        schema_version: int = 1,
    ) -> dict[str, object]:
        return {
            "schema_version": schema_version,
            "observed_at_epoch": self.now if observed is None else observed,
            "config": config,
            "runtime": runtime,
            "verified": verified,
            "source": "nftables",
            "detail": detail,
        }

    def write_state(self, **changes: object) -> None:
        value = self.state()
        value.update(changes)
        self.state_path.write_text(json.dumps(value), encoding="utf-8")
        self.state_path.chmod(0o644)

    def collect(self, *, trusted_uid: int | None = None) -> dict[str, object]:
        return ServiceCollector(
            self.proc,
            self.etc,
            runner=self.runner,
            wall_time=lambda: float(self.now),
            ufw_state_path=self.state_path,
            ufw_trusted_uid=os.geteuid() if trusted_uid is None else trusted_uid,
        ).collect(tunnel_present=False)

    def assert_unknown_not_degraded(self, values: dict[str, object], detail: str) -> None:
        self.assertEqual(values["service_ufw"], "unknown")
        self.assertNotEqual(values["service_ufw"], "degraded")
        self.assertEqual(values["service_ufw_runtime"], "unconfirmed")
        self.assertEqual(values["service_ufw_detail"], detail)

    def test_fresh_verified_active_is_ok(self) -> None:
        self.set_config()
        self.write_state()
        values = self.collect()
        self.assertEqual(values["service_ufw"], "ok")
        self.assertEqual(values["service_ufw_runtime"], "active")
        self.assertEqual(values["service_ufw_confidence"], "high")
        self.assertEqual(values["service_ufw_detail"], "verified_runtime_active")

    def test_fresh_verified_inactive_is_degraded_with_high_confidence(self) -> None:
        self.set_config()
        self.write_state(
            runtime="inactive",
            verified=True,
            detail="verified_runtime_inactive",
        )
        values = self.collect()
        self.assertEqual(values["service_ufw"], "degraded")
        self.assertEqual(values["service_ufw_runtime"], "inactive")
        self.assertEqual(values["service_ufw_confidence"], "high")
        self.assertEqual(values["service_ufw_detail"], "verified_runtime_inactive")

    def test_config_disabled_is_off_without_probe(self) -> None:
        self.set_config("no")
        values = self.collect()
        self.assertEqual(values["service_ufw"], "off")
        self.assertEqual(values["service_ufw_confidence"], "high")
        self.assertEqual(values["service_ufw_detail"], "config_disabled")

    def test_missing_file_is_unknown(self) -> None:
        self.set_config()
        self.assert_unknown_not_degraded(self.collect(), "probe_missing")

    def test_stale_file_is_unknown(self) -> None:
        self.set_config()
        self.write_state(observed_at_epoch=self.now - 121)
        self.assert_unknown_not_degraded(self.collect(), "probe_stale")

    def test_symlink_is_rejected(self) -> None:
        self.set_config()
        target = self.runtime / "real.json"
        target.write_text(json.dumps(self.state()), encoding="utf-8")
        self.state_path.symlink_to(target)
        self.assert_unknown_not_degraded(self.collect(), "probe_invalid")

    def test_non_regular_file_is_rejected(self) -> None:
        self.set_config()
        self.state_path.mkdir()
        self.assert_unknown_not_degraded(self.collect(), "probe_invalid")

    def test_group_or_world_writable_file_is_rejected(self) -> None:
        self.set_config()
        for mode in (0o664, 0o646):
            with self.subTest(mode=oct(mode)):
                self.write_state()
                self.state_path.chmod(mode)
                self.assert_unknown_not_degraded(self.collect(), "probe_invalid")

    def test_oversized_file_is_rejected(self) -> None:
        self.set_config()
        self.state_path.write_bytes(b"x" * (UFW_STATE_MAX_BYTES + 1))
        self.assert_unknown_not_degraded(self.collect(), "probe_invalid")

    def test_wrong_owner_or_untrusted_parent_is_rejected(self) -> None:
        self.set_config()
        self.write_state()
        self.assert_unknown_not_degraded(
            self.collect(trusted_uid=os.geteuid() + 1), "probe_invalid"
        )
        self.runtime.chmod(0o777)
        self.assert_unknown_not_degraded(self.collect(), "probe_invalid")

    def test_wrong_schema_version_is_rejected(self) -> None:
        self.set_config()
        self.write_state(schema_version=2)
        self.assert_unknown_not_degraded(self.collect(), "probe_invalid")

    def test_invalid_enums_are_rejected(self) -> None:
        self.set_config()
        for field, value in (("config", "maybe"), ("runtime", "healthy"), ("detail", "raw-detail")):
            with self.subTest(field=field):
                self.write_state(**{field: value})
                self.assert_unknown_not_degraded(self.collect(), "probe_invalid")

    def test_future_timestamp_is_rejected(self) -> None:
        self.set_config()
        self.write_state(observed_at_epoch=self.now + 6)
        self.assert_unknown_not_degraded(self.collect(), "probe_invalid")

    def test_partial_write_is_rejected(self) -> None:
        self.set_config()
        self.state_path.write_text('{"schema_version":1', encoding="utf-8")
        self.assert_unknown_not_degraded(self.collect(), "probe_invalid")

    def test_probe_error_is_unknown(self) -> None:
        self.set_config()
        self.write_state(runtime="error", verified=False, detail="timeout")
        values = self.collect()
        self.assertEqual(values["service_ufw"], "unknown")
        self.assertEqual(values["service_ufw_runtime"], "error")
        self.assertEqual(values["service_ufw_detail"], "probe_error")

    def test_permission_denied_never_means_degraded(self) -> None:
        self.set_config()
        values = self.collect()
        self.assert_unknown_not_degraded(values, "probe_missing")
        self.assertFalse(any(command and command[0].endswith("nft") for command in self.commands))

    def test_realistic_non_ufw_signals_keep_honest_confidence_and_privacy(self) -> None:
        self.set_config()
        self.write_state()
        for pid, command in (
            ("100", b"python3\0/private/asus_touchpad.py\0"),
            ("101", b"python3\0/private/openfortivpn_indicator_full.py\0"),
        ):
            entry = self.proc / pid
            entry.mkdir()
            (entry / "comm").write_text("python3\n", encoding="utf-8")
            (entry / "cmdline").write_bytes(command)

        values = self.collect()
        self.assertEqual(values["service_fortivpn"], "off")
        self.assertEqual(values["service_numberpad"], "ok")
        self.assertEqual(values["service_ntfy"], "ok")
        self.assertEqual(values["service_monitors"], "unknown")
        serialized = json.dumps(values)
        self.assertNotIn("/private", serialized)
        self.assertNotIn("asus_touchpad.py", serialized)

    def test_missing_sources_never_raise_and_return_unknown(self) -> None:
        missing_etc = self.root / "missing-etc"

        def timeout(*_args: object, **_kwargs: object):
            raise subprocess.TimeoutExpired(["systemctl"], 2.0)

        values = ServiceCollector(
            self.proc,
            missing_etc,
            runner=timeout,
            ufw_state_path=self.root / "missing-run" / "ufw-status.json",
        ).collect(False)
        for name in ("ufw", "fortivpn", "numberpad", "ntfy", "monitors"):
            self.assertEqual(values[f"service_{name}"], "unknown")


if __name__ == "__main__":
    unittest.main()
