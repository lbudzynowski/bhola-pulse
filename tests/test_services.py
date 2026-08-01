from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from src.bhola_services import ServiceCollector


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
    def test_realistic_local_signals_have_honest_confidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc = root / "proc"
            etc = root / "etc"
            proc.mkdir()
            (etc / "ufw").mkdir(parents=True)
            (etc / "ufw/ufw.conf").write_text("ENABLED=yes\n", encoding="utf-8")
            for pid, command in (
                ("100", b"python3\0/private/asus_touchpad.py\0"),
                ("101", b"python3\0/private/openfortivpn_indicator_full.py\0"),
            ):
                entry = proc / pid
                entry.mkdir()
                (entry / "comm").write_text("python3\n", encoding="utf-8")
                (entry / "cmdline").write_bytes(command)

            def runner(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
                if args[:3] == ["nft", "list", "ruleset"]:
                    return subprocess.CompletedProcess(args, 1, "", "permission denied")
                return subprocess.CompletedProcess(args, 0, UNIT_OUTPUT, "")

            values = ServiceCollector(
                proc,
                etc,
                runner=runner,
                wall_time=lambda: 100.0,
            ).collect(tunnel_present=False)
            self.assertEqual(values["service_ufw"], "degraded")
            self.assertEqual(values["service_ufw_runtime"], "unconfirmed")
            self.assertEqual(values["service_fortivpn"], "off")
            self.assertEqual(values["service_fortivpn_detail"], "indicator_idle")
            self.assertEqual(values["service_numberpad"], "ok")
            self.assertEqual(values["service_ntfy"], "ok")
            self.assertEqual(values["service_monitors"], "unknown")
            serialized = json.dumps(values)
            self.assertNotIn("/private", serialized)
            self.assertNotIn("asus_touchpad.py", serialized)

    def test_missing_sources_never_raise_and_return_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc = root / "proc"
            proc.mkdir()

            def timeout(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
                raise subprocess.TimeoutExpired(["systemctl"], 2.0)

            values = ServiceCollector(proc, root / "etc", runner=timeout).collect(False)
            for name in ("ufw", "fortivpn", "numberpad", "ntfy", "monitors"):
                self.assertEqual(values[f"service_{name}"], "unknown")


if __name__ == "__main__":
    unittest.main()
