from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "packaging" / "bhola-pulse"


class InstalledLauncherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.base = Path(self.temporary_directory.name)
        self.home = self.base / "home"
        self.config_home = self.base / "config"
        self.state_home = self.base / "state"
        self.app_root = self.base / "app"
        scripts = self.app_root / "scripts"
        scripts.mkdir(parents=True)
        self.home.mkdir()
        (self.app_root / "VERSION").write_text("0.1.0\n", encoding="utf-8")
        runtime = scripts / "run-dev.sh"
        runtime.write_text(
            "#!/usr/bin/env bash\n"
            "printf 'style=%s\\n' \"${BHOLA_STYLE:-unset}\"\n"
            "printf 'state=%s\\n' \"${BHOLA_STATE_FILE:-unset}\"\n"
            "printf 'args=%s\\n' \"$*\"\n",
            encoding="utf-8",
        )
        runtime.chmod(runtime.stat().st_mode | stat.S_IXUSR)
        self.environment = os.environ.copy()
        self.environment.update(
            {
                "HOME": str(self.home),
                "XDG_CONFIG_HOME": str(self.config_home),
                "XDG_STATE_HOME": str(self.state_home),
                "BHOLA_PULSE_LIBDIR": str(self.app_root),
            }
        )
        self.environment.pop("BHOLA_STYLE", None)
        self.environment.pop("BHOLA_STATE_FILE", None)

    def run_launcher(
        self, *arguments: str, environment: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(LAUNCHER), *arguments],
            cwd=ROOT,
            env=self.environment if environment is None else environment,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_style_can_be_saved_shown_and_reset(self) -> None:
        saved = self.run_launcher("config", "set", "nerd")
        self.assertEqual(saved.returncode, 0, saved.stderr)
        self.assertIn("Saved Bhola Pulse style: nerd", saved.stdout)
        style_file = self.config_home / "bhola-pulse" / "style"
        self.assertEqual(style_file.read_text(encoding="utf-8"), "nerd\n")
        self.assertEqual(stat.S_IMODE(style_file.stat().st_mode), 0o600)

        shown = self.run_launcher("config", "show")
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertIn("style=nerd", shown.stdout)
        self.assertIn(str(style_file), shown.stdout)

        reset = self.run_launcher("config", "reset")
        self.assertEqual(reset.returncode, 0, reset.stderr)
        self.assertFalse(style_file.exists())
        default = self.run_launcher("config", "show")
        self.assertEqual(default.stdout, "style=modern source=default\n")

    def test_cinematic_style_can_be_saved_and_reaches_runtime(self) -> None:
        saved = self.run_launcher("config", "set", "cinematic")
        self.assertEqual(saved.returncode, 0, saved.stderr)
        self.assertIn("Saved Bhola Pulse style: cinematic", saved.stdout)

        result = self.run_launcher("--check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("style=cinematic\n", result.stdout)

    def test_saved_style_and_xdg_state_reach_runtime(self) -> None:
        self.assertEqual(self.run_launcher("config", "nerd").returncode, 0)
        result = self.run_launcher("--check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("style=nerd\n", result.stdout)
        self.assertIn(
            f"state={self.state_home / 'bhola-pulse' / 'dashboard.json'}\n",
            result.stdout,
        )
        self.assertIn("args=--check\n", result.stdout)

    def test_environment_overrides_saved_style(self) -> None:
        self.assertEqual(self.run_launcher("config", "set", "nerd").returncode, 0)
        environment = self.environment.copy()
        environment["BHOLA_STYLE"] = "modern"
        result = self.run_launcher(environment=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("style=modern\n", result.stdout)

    def test_invalid_style_is_rejected_without_changing_config(self) -> None:
        result = self.run_launcher("config", "set", "retro")
        self.assertEqual(result.returncode, 2)
        self.assertIn("expected modern, nerd, or cinematic", result.stderr)
        self.assertFalse((self.config_home / "bhola-pulse" / "style").exists())

    def test_version_comes_from_installed_payload(self) -> None:
        result = self.run_launcher("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "Bhola Pulse 0.1.0\n")


if __name__ == "__main__":
    unittest.main()
