from __future__ import annotations

import os
import subprocess
import sys
import unittest

from src.bhola_style import resolve_style


class StyleSelectionTests(unittest.TestCase):
    def test_modern_is_default(self) -> None:
        self.assertEqual(resolve_style(environ={}), "modern")

    def test_cli_selects_nerd(self) -> None:
        self.assertEqual(resolve_style("nerd", {}), "nerd")

    def test_environment_selects_nerd(self) -> None:
        self.assertEqual(resolve_style(environ={"BHOLA_STYLE": "nerd"}), "nerd")

    def test_cli_takes_precedence_over_environment(self) -> None:
        self.assertEqual(resolve_style("modern", {"BHOLA_STYLE": "nerd"}), "modern")
        self.assertEqual(resolve_style("nerd", {"BHOLA_STYLE": "invalid"}), "nerd")

        environment = dict(os.environ)
        environment["BHOLA_STYLE"] = "nerd"
        result = subprocess.run(
            [sys.executable, "-m", "src.bhola_style", "--style", "modern"],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "modern")

    def test_invalid_style_is_rejected_with_nonzero_exit(self) -> None:
        with self.assertRaisesRegex(ValueError, "expected one of: modern, nerd"):
            resolve_style("future", {})

        environment = dict(os.environ)
        environment["BHOLA_STYLE"] = "future"
        result = subprocess.run(
            [sys.executable, "-m", "src.bhola_style"],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid dashboard style", result.stderr)


if __name__ == "__main__":
    unittest.main()
