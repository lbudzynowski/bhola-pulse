from __future__ import annotations

import configparser
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest

from src import bhola_ufw_probe


ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "packaging/systemd/bhola-pulse-ufw-probe.service"
TIMER = ROOT / "packaging/systemd/bhola-pulse-ufw-probe.timer"


def unit(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    with path.open(encoding="utf-8") as stream:
        parser.read_file(stream)
    return parser


class SystemdUnitTests(unittest.TestCase):
    def test_service_has_only_required_capability_and_host_netlink_view(self) -> None:
        service = unit(SERVICE)["Service"]
        self.assertEqual(service["Type"], "oneshot")
        self.assertEqual(
            service["ExecStart"],
            "/usr/lib/bhola-pulse/bhola-pulse-ufw-probe",
        )
        self.assertEqual(service["CapabilityBoundingSet"], "CAP_NET_ADMIN")
        self.assertEqual(service["RestrictAddressFamilies"], "AF_UNIX AF_NETLINK")
        self.assertNotIn("PrivateNetwork", service)
        self.assertEqual(service["ReadWritePaths"], "/run/bhola-pulse")

    def test_service_hardening_and_preserved_runtime_are_enabled(self) -> None:
        service = unit(SERVICE)["Service"]
        expected = {
            "NoNewPrivileges": "yes",
            "ProtectSystem": "strict",
            "ProtectHome": "yes",
            "PrivateTmp": "yes",
            "PrivateDevices": "yes",
            "ProtectKernelTunables": "yes",
            "ProtectKernelModules": "yes",
            "ProtectControlGroups": "yes",
            "ProtectKernelLogs": "yes",
            "LockPersonality": "yes",
            "MemoryDenyWriteExecute": "yes",
            "RestrictSUIDSGID": "yes",
            "RestrictRealtime": "yes",
            "RestrictNamespaces": "yes",
            "SystemCallArchitectures": "native",
            "RuntimeDirectory": "bhola-pulse",
            "RuntimeDirectoryMode": "0755",
            "RuntimeDirectoryPreserve": "yes",
        }
        for directive, value in expected.items():
            with self.subTest(directive=directive):
                self.assertEqual(service[directive], value)

    def test_timer_is_bounded_and_periodic(self) -> None:
        timer = unit(TIMER)["Timer"]
        self.assertEqual(timer["OnBootSec"], "15s")
        self.assertEqual(timer["OnUnitActiveSec"], "45s")
        self.assertEqual(timer["AccuracySec"], "5s")
        self.assertEqual(timer["RandomizedDelaySec"], "5s")
        self.assertEqual(timer["Unit"], "bhola-pulse-ufw-probe.service")
        self.assertEqual(unit(TIMER)["Install"]["WantedBy"], "timers.target")

    @unittest.skipUnless(shutil.which("systemd-analyze"), "systemd-analyze unavailable")
    def test_systemd_analyze_verify_in_isolated_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            units = root / "etc/systemd/system"
            executable = root / "usr/lib/bhola-pulse/bhola-pulse-ufw-probe"
            interpreter = root / "usr/bin/python3"
            units.mkdir(parents=True)
            executable.parent.mkdir(parents=True)
            interpreter.parent.mkdir(parents=True)
            shutil.copy2(SERVICE, units / SERVICE.name)
            shutil.copy2(TIMER, units / TIMER.name)
            for target in (
                "basic.target",
                "local-fs.target",
                "shutdown.target",
                "sysinit.target",
                "timers.target",
            ):
                (units / target).write_text(
                    f"[Unit]\nDescription=Isolated {target}\n", encoding="utf-8"
                )
            shutil.copy2(ROOT / "src/bhola_ufw_probe.py", executable)
            interpreter.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)
            interpreter.chmod(0o755)
            completed = subprocess.run(
                [
                    "systemd-analyze",
                    f"--root={root}",
                    "verify",
                    SERVICE.name,
                    TIMER.name,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)


class PackagingPolicyTests(unittest.TestCase):
    def test_nftables_is_required_because_probe_is_mandatory(self) -> None:
        binary_control = (ROOT / "packaging/debian/control.in").read_text(encoding="utf-8")
        source_control = (ROOT / "debian/control").read_text(encoding="utf-8")
        self.assertIn("Depends: python3 (>= 3.11), conky-all, x11-xserver-utils, libx11-6, nftables", binary_control)
        self.assertIn("\n nftables,\n", source_control)
        self.assertNotIn("Recommends: iputils-ping, nftables", binary_control)

    def test_debhelper_owns_systemd_lifecycle_without_handwritten_scripts(self) -> None:
        rules = (ROOT / "debian/rules").read_text(encoding="utf-8")
        self.assertIn("dh $@", rules)
        for name in ("postinst", "preinst", "prerm", "postrm"):
            self.assertFalse((ROOT / "debian" / name).exists())

    def test_install_payload_paths_and_modes_are_declared(self) -> None:
        rules = (ROOT / "debian/rules").read_text(encoding="utf-8")
        for path in (
            "usr/lib/bhola-pulse/bhola-pulse-ufw-probe",
            "lib/systemd/system",
            "bhola-pulse-ufw-probe.service",
            "bhola-pulse-ufw-probe.timer",
        ):
            self.assertIn(path, rules)
        self.assertEqual(
            stat.S_IMODE((ROOT / "src/bhola_ufw_probe.py").stat().st_mode),
            0o755,
        )
        self.assertEqual(stat.S_IMODE(SERVICE.stat().st_mode), 0o644)
        self.assertEqual(stat.S_IMODE(TIMER.stat().st_mode), 0o644)

    def test_runtime_has_no_privilege_escalation_or_mutating_nft_command(self) -> None:
        paths = [
            ROOT / "src/bhola_ufw_probe.py",
            ROOT / "src/bhola_services.py",
            SERVICE,
            TIMER,
            ROOT / "debian/rules",
            ROOT / "scripts/build-deb.sh",
        ]
        runtime_text = "\n".join(path.read_text(encoding="utf-8") for path in paths).lower()
        for forbidden in (
            "sudoers",
            "setcap",
            "pkexec",
            "polkit",
            "privateNetwork=yes".lower(),
            "nft add",
            "nft delete",
            "nft replace",
            "nft flush",
            "nft reset",
            "nft monitor",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, runtime_text)
        self.assertEqual(
            bhola_ufw_probe.NFT_COMMAND,
            ("/usr/sbin/nft", "--json", "list", "ruleset"),
        )


if __name__ == "__main__":
    unittest.main()
