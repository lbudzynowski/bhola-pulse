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

    def test_cinematic_has_requested_effects(self) -> None:
        cinematic = (ROOT / "conky/bhola_render_cinematic.lua").read_text(encoding="utf-8")
        for marker in (
            "LIVE TRACE // REAL CACHE STREAM // 12 LINES",
            "local function draw_boot_sequence",
            "local function draw_scanlines",
            "local function draw_glitch_burst",
            "local function draw_ascii_skull",
            "local skull_lines = {",
            "local glitch_slices = {",
            "local function draw_hud",
            "cinematic telemetry linked",
            "STREAM > _",
        ):
            self.assertIn(marker, cinematic)

    def test_glitch_re_renders_real_scene_slices_and_uses_original_ascii_skull(self) -> None:
        cinematic = (ROOT / "conky/bhola_render_cinematic.lua").read_text(encoding="utf-8")

        self.assertIn("local glitch_cycle_seconds = 11.7", cinematic)
        self.assertIn("local glitch_burst_seconds = 0.75", cinematic)
        self.assertIn("cairo_rectangle(cr, 0, y, width, h)", cinematic)
        self.assertIn("cairo_clip(cr)", cinematic)
        self.assertIn("cairo_translate(cr, dx, 0)", cinematic)
        self.assertIn("draw_scene(cr, metrics, animation_time)", cinematic)
        self.assertIn("cycle_index % 3 ~= 0", cinematic)
        self.assertIn("draw_text(cr, base_x + dx - 3", cinematic)
        self.assertIn("draw_text(cr, base_x + dx + 3", cinematic)
        self.assertIn("draw_text(cr, base_x + dx, y, line", cinematic)

        # The skull is source text in this repository, not an external image asset.
        self.assertNotIn(".png", cinematic.lower())
        self.assertNotIn(".jpg", cinematic.lower())
        self.assertNotIn(".svg", cinematic.lower())

    def test_boot_hides_live_trace_until_cinematic_is_online(self) -> None:
        cinematic = (ROOT / "conky/bhola_render_cinematic.lua").read_text(encoding="utf-8")

        self.assertIn("local boot_duration = 4.6", cinematic)
        boot_branch = cinematic.index("if animation_time < boot_duration then")
        live_scene = cinematic.index("draw_scene(cr, metrics, animation_time)", boot_branch)
        return_in_boot = cinematic.index("return", boot_branch)
        self.assertLess(return_in_boot, live_scene)
        self.assertIn("Cinematic owns the full 760x720 scene", cinematic)

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

    def test_live_trace_scrolls_twelve_real_cache_lines(self) -> None:
        cinematic = (ROOT / "conky/bhola_render_cinematic.lua").read_text(encoding="utf-8")

        self.assertIn("local trace_limit = 12", cinematic)
        self.assertIn("local trace_sample_seconds = 1", cinematic)
        self.assertIn("local function emit_trace_sample(metrics, epoch)", cinematic)
        self.assertIn("trace_sample_slot = (trace_sample_slot % 4) + 1", cinematic)
        self.assertIn("while #events > trace_limit do", cinematic)
        self.assertIn("table.remove(events, 1)", cinematic)
        self.assertIn("local first_index = math.max(1, count - trace_limit + 1)", cinematic)
        self.assertIn("local fade = 0.30 + 0.70 * (rank / visible_count)", cinematic)
        self.assertIn('local marker = index == count and ">" or " "', cinematic)

        for metric in (
            "cpu_percent",
            "memory_percent",
            "load_1",
            "network_download_bytes_per_second",
            "network_upload_bytes_per_second",
            "network_latency_ms",
            "disk_read_bytes_per_second",
            "disk_write_bytes_per_second",
            "process_count",
            "temperature_cpu_c",
            "service_monitors",
        ):
            self.assertIn(f"metrics.{metric}", cinematic)

    def test_cinematic_gets_extra_height_without_changing_other_styles(self) -> None:
        cinematic = (ROOT / "conky/bhola_render_cinematic.lua").read_text(encoding="utf-8")
        config = (ROOT / "conky/bhola-pulse.conf").read_text(encoding="utf-8")

        self.assertIn("local width = 760", cinematic)
        self.assertIn("local height = 720", cinematic)
        self.assertIn("local trace_top = 526", cinematic)
        self.assertIn("local trace_height = 188", cinematic)
        self.assertIn("local base_height = 570", config)
        self.assertIn("local cinematic_height = 720", config)
        self.assertIn("if style == 'cinematic' then", config)
        self.assertIn("base_height = cinematic_height", config)
        self.assertIn("own_window_transparent = true", config)
        self.assertIn("own_window_argb_value = 0", config)
        self.assertLessEqual((28 + 720) * 1.25, 1080)


if __name__ == "__main__":
    unittest.main()
