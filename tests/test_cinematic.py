from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CinematicRendererTests(unittest.TestCase):
    def test_cinematic_is_separate_wrapper_over_nerd(self) -> None:
        pulse = (ROOT / "conky/bhola_pulse.lua").read_text(encoding="utf-8")
        cinematic = (ROOT / "conky/bhola_render_cinematic.lua").read_text(encoding="utf-8")
        nerd = (ROOT / "conky/bhola_render_nerd.lua").read_text(encoding="utf-8")

        self.assertIn('cinematic = "conky.bhola_render_cinematic"', pulse)
        self.assertIn('local nerd = require("conky.bhola_render_nerd")', cinematic)
        self.assertIn("nerd.update(metrics)", cinematic)
        self.assertIn("nerd.draw_dashboard(cr, metrics, animation_time)", cinematic)
        self.assertIn("function render.draw_ticker", cinematic)
        self.assertNotEqual(cinematic, nerd)

    def test_cinematic_has_requested_first_stage_effects(self) -> None:
        cinematic = (ROOT / "conky/bhola_render_cinematic.lua").read_text(encoding="utf-8")
        for marker in (
            "LIVE TRACE // REAL CACHE EVENTS",
            "local function draw_boot_sequence",
            "local function draw_scanlines",
            "local function draw_glitch",
            "local function draw_hud",
            "cinematic telemetry linked",
            "heartbeat / telemetry stream alive",
        ):
            self.assertIn(marker, cinematic)

    def test_live_trace_only_uses_real_existing_cache_categories(self) -> None:
        cinematic = (ROOT / "conky/bhola_render_cinematic.lua").read_text(encoding="utf-8")
        for category in ("PULSE", "SYS", "NET", "SVC"):
            self.assertIn(f'{category} = colors.', cinematic)
        for invented_category in ("GIT", "APT", "PPA"):
            self.assertNotIn(f'{invented_category} = colors.', cinematic)

        for field in (
            "provider_status",
            "power_source",
            "network_internet_status",
            "network_dns_status",
            "network_https_status",
            "service_ufw",
            "service_fortivpn",
            "service_ntfy",
        ):
            self.assertIn(f'key = "{field}"', cinematic)

    def test_cinematic_keeps_existing_panel_geometry(self) -> None:
        cinematic = (ROOT / "conky/bhola_render_cinematic.lua").read_text(encoding="utf-8")
        config = (ROOT / "conky/bhola-pulse.conf").read_text(encoding="utf-8")
        self.assertIn("local width = 760", cinematic)
        self.assertIn("local height = 570", cinematic)
        self.assertIn("local trace_top = 526", cinematic)
        self.assertIn("local trace_height = 40", cinematic)
        self.assertIn("local base_height = 570", config)


if __name__ == "__main__":
    unittest.main()
