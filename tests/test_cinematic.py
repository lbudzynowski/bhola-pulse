from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CinematicRendererTests(unittest.TestCase):
    def test_cinematic_is_separate_wrapper_over_nerd(self) -> None:
        pulse = (ROOT / "conky/bhola_pulse.lua").read_text(encoding="utf-8")
        cinematic = (ROOT / "conky/bhola_render_cinematic.lua").read_text(encoding="utf-8")
        panels = (ROOT / "conky/bhola_cinetty_panels.lua").read_text(encoding="utf-8")
        nerd = (ROOT / "conky/bhola_render_nerd.lua").read_text(encoding="utf-8")

        self.assertIn('cinematic = "conky.bhola_render_cinematic"', pulse)
        self.assertIn('local nerd = require("conky.bhola_render_nerd")', cinematic)
        self.assertIn('local cinetty = require("conky.bhola_cinetty_panels")', cinematic)
        self.assertIn("nerd.update(metrics)", cinematic)
        self.assertIn("cinetty.update(metrics)", cinematic)
        self.assertIn("nerd.draw_dashboard(cr, metrics, animation_time)", cinematic)
        self.assertIn("cinetty.draw(cr, metrics, animation_time)", cinematic)
        self.assertIn("function render.draw_ticker", cinematic)
        self.assertNotEqual(cinematic, nerd)
        self.assertTrue(panels)

    def test_cinematic_has_requested_effects(self) -> None:
        cinematic = (ROOT / "conky/bhola_render_cinematic.lua").read_text(encoding="utf-8")
        panels = (ROOT / "conky/bhola_cinetty_panels.lua").read_text(encoding="utf-8")

        for marker in (
            "local function draw_boot_sequence",
            "local function draw_scanlines",
            "local function draw_glitch_burst",
            "local function draw_ascii_skull",
            "local skull_lines = {",
            "local glitch_slices = {",
            "local function draw_hud",
        ):
            self.assertIn(marker, cinematic)

        for marker in (
            "SOURCE // src/bhola_provider.py",
            "REAL CACHE // EVENT STREAM",
            "AUTO-TYPE",
            "4 REC/S",
            "CACHE VALUES // TRANSITIONS PRIORITY",
            "local function draw_source_editor",
            "local function draw_event_stream",
        ):
            self.assertIn(marker, panels)

    def test_glitch_re_renders_real_scene_slices_and_uses_selected_ascii_skull(self) -> None:
        cinematic = (ROOT / "conky/bhola_render_cinematic.lua").read_text(encoding="utf-8")

        self.assertIn("local glitch_cycle_seconds = 11.7", cinematic)
        self.assertIn("local glitch_burst_seconds = 1.6", cinematic)
        self.assertIn("if phase < 0.30 or phase > 1.35 then", cinematic)
        self.assertIn("local skull_phase = (phase - 0.30) / 1.05", cinematic)
        self.assertIn("cairo_rectangle(cr, 0, y, width, h)", cinematic)
        self.assertIn("cairo_clip(cr)", cinematic)
        self.assertIn("cairo_translate(cr, dx, 0)", cinematic)
        self.assertIn("draw_scene(cr, metrics, animation_time)", cinematic)
        self.assertIn("cycle_index % 3 ~= 0", cinematic)
        self.assertIn("draw_text(cr, base_x + dx - 3", cinematic)
        self.assertIn("draw_text(cr, base_x + dx + 3", cinematic)
        self.assertIn("draw_text(cr, base_x + dx, y, line", cinematic)
        self.assertIn("Selected reference #1", cinematic)

        self.assertNotIn(".png", cinematic.lower())
        self.assertNotIn(".jpg", cinematic.lower())
        self.assertNotIn(".svg", cinematic.lower())

    def test_boot_hides_cinetty_panels_until_cinematic_is_online(self) -> None:
        cinematic = (ROOT / "conky/bhola_render_cinematic.lua").read_text(encoding="utf-8")

        self.assertIn("local boot_duration = 4.6", cinematic)
        boot_branch = cinematic.index("if animation_time < boot_duration then")
        live_scene = cinematic.index("draw_scene(cr, metrics, animation_time)", boot_branch)
        return_in_boot = cinematic.index("return", boot_branch)
        self.assertLess(return_in_boot, live_scene)
        self.assertIn("CineTTY-inspired lower panels", cinematic)

    def test_event_stream_only_uses_real_existing_cache_categories(self) -> None:
        panels = (ROOT / "conky/bhola_cinetty_panels.lua").read_text(encoding="utf-8")

        for category in ("PULSE", "SYS", "NET", "SVC"):
            self.assertIn(f'{category} = colors.', panels)
        for invented_category in ("GIT", "APT", "PPA", "IRQ", "NVME"):
            self.assertNotIn(f'{invented_category} = colors.', panels)

        for field in (
            "provider_status",
            "power_source",
            "network_internet_status",
            "network_dns_status",
            "network_https_status",
            "service_ufw",
            "service_fortivpn",
            "service_ntfy",
            "service_monitors",
        ):
            self.assertIn(f'key = "{field}"', panels)

    def test_event_stream_samples_real_cache_four_times_per_second(self) -> None:
        panels = (ROOT / "conky/bhola_cinetty_panels.lua").read_text(encoding="utf-8")

        self.assertIn("local stream_records_per_second = 4", panels)
        self.assertIn("local stream_buffer_limit = 48", panels)
        self.assertIn("local stream_visible_lines = 14", panels)
        self.assertIn("local function emit_visual_samples(metrics, animation_time)", panels)
        self.assertIn("math.floor(animation_time * stream_records_per_second)", panels)
        self.assertIn("while #events > stream_buffer_limit do", panels)
        self.assertIn("table.remove(events, 1)", panels)
        self.assertIn('kind = kind or "EVT"', panels)
        self.assertIn('"SMP"', panels)
        self.assertIn('"EVT"', panels)

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
            self.assertIn(f"metrics.{metric}", panels)

    def test_source_editor_autotypes_real_provider_excerpt_one_character_per_step(self) -> None:
        panels = (ROOT / "conky/bhola_cinetty_panels.lua").read_text(encoding="utf-8")
        provider = (ROOT / "src/bhola_provider.py").read_text(encoding="utf-8")

        for source_line in (
            "def create_scheduler(collectors: SystemCollectors, start: float) -> SourceScheduler:",
            '            "fast",',
            "            collectors.fast,",
            '            "network_activity",',
            "            collectors.network_activity,",
            '                "network_download_bytes_per_second": 0.0,',
            '                "disk_read_bytes_per_second": 0.0,',
        ):
            self.assertIn(source_line, provider)
            self.assertIn(source_line, panels)

        self.assertIn("local source_char_step_seconds = 0.30", panels)
        self.assertIn("local source_typed_chars = 0", panels)
        self.assertIn("local function advance_source_typing(animation_time)", panels)
        self.assertIn("if source_last_draw_time == animation_time then", panels)
        self.assertIn(
            "source_typed_chars = math.min(source_total_chars, source_typed_chars + 1)",
            panels,
        )
        self.assertIn("local function source_typing_state(animation_time)", panels)
        self.assertIn("local current_line, current_col = source_typing_state(animation_time)", panels)
        self.assertIn("visible_text = string.sub(full_line, 1, current_col)", panels)
        self.assertIn('string.rep(" ", current_col) .. "█"', panels)
        self.assertNotIn("current_col * 3.62", panels)
        self.assertNotIn("cairo_rectangle(cr, cursor_x", panels)
        self.assertNotIn("source_chars_per_second", panels)
        self.assertIn("READ-ONLY", panels)

    def test_cinematic_gets_extra_height_without_changing_other_styles(self) -> None:
        cinematic = (ROOT / "conky/bhola_render_cinematic.lua").read_text(encoding="utf-8")
        panels = (ROOT / "conky/bhola_cinetty_panels.lua").read_text(encoding="utf-8")
        config = (ROOT / "conky/bhola-pulse.conf").read_text(encoding="utf-8")

        self.assertIn("local width = 760", cinematic)
        self.assertIn("local height = 720", cinematic)
        self.assertIn("local lower_top = 526", panels)
        self.assertIn("local lower_height = 188", panels)
        self.assertIn("local editor_width = 364", panels)
        self.assertIn("local stream_x = 380", panels)
        self.assertIn("local stream_width = 372", panels)
        self.assertIn("local base_height = 570", config)
        self.assertIn("local cinematic_height = 720", config)
        self.assertIn("if style == 'cinematic' then", config)
        self.assertIn("base_height = cinematic_height", config)
        self.assertIn("own_window_transparent = true", config)
        self.assertIn("own_window_argb_value = 0", config)
        self.assertLessEqual((28 + 720) * 1.25, 1080)


if __name__ == "__main__":
    unittest.main()
