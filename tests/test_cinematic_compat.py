from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CombinedCinematicCairoCompatibilityTests(unittest.TestCase):
    def test_cinematic_wired_to_compatibility_adapter(self) -> None:
        pulse = (ROOT / "conky/bhola_pulse.lua").read_text(encoding="utf-8")
        self.assertIn('local surfaces = require("conky.bhola_surface")', pulse)
        self.assertIn("surfaces.acquire(conky_window, conky_surface)", pulse)
        self.assertIn('cinematic = "conky.bhola_render_cinematic"', pulse)
        self.assertNotIn("cairo_xlib_surface_create(", pulse)
        self.assertIn("if owned_surface then", pulse)

    def test_cinematic_geometry_and_x11_config_are_not_regressed(self) -> None:
        config = (ROOT / "conky/bhola-pulse.conf").read_text(encoding="utf-8")
        self.assertIn("local cinematic_height = 720", config)
        self.assertIn("if style == 'cinematic' then", config)
        self.assertNotIn("out_to_x = true", config)
        self.assertNotIn("out_to_wayland = false", config)

    def test_all_style_cli_paths_and_version_covered(self) -> None:
        launcher = (ROOT / "packaging/bhola-pulse").read_text(encoding="utf-8")
        styles = (ROOT / "src/bhola_style.py").read_text(encoding="utf-8")
        self.assertIn("modern|nerd|cinematic", launcher)
        self.assertIn('VALID_STYLES = ("modern", "nerd", "cinematic")', styles)
        self.assertEqual((ROOT / "VERSION").read_text().strip(), "0.1.5")


if __name__ == "__main__":
    unittest.main()
