from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


def lua_number(content: str, key: str) -> float:
    match = re.search(
        rf"^\s*(?:local\s+)?{re.escape(key)}\s*=\s*([0-9.]+),?\s*$",
        content,
        re.MULTILINE,
    )
    if not match:
        raise AssertionError(f"missing Lua numeric key: {key}")
    return float(match.group(1))


class TwoColumnLayoutTests(unittest.TestCase):
    def test_panel_geometry_fits_full_hd_and_matches_renderer(self) -> None:
        config = (ROOT / "conky/bhola-pulse.conf").read_text(encoding="utf-8")
        renderer = (ROOT / "conky/bhola_render.lua").read_text(encoding="utf-8")
        pulse = (ROOT / "conky/bhola_pulse.lua").read_text(encoding="utf-8")
        base_width = lua_number(config, "base_width")
        base_height = lua_number(config, "base_height")
        base_gap = lua_number(config, "base_gap")
        default_scale = lua_number(config, "default_scale")
        self.assertEqual(base_width, lua_number(renderer, "width"))
        self.assertEqual(base_height, lua_number(renderer, "height"))
        self.assertEqual((base_width, base_height), (760, 570))
        self.assertEqual(default_scale, 1.25)
        self.assertLessEqual((base_gap + base_height) * default_scale, 1080)
        self.assertIn("BHOLA_UPDATE_INTERVAL", config)
        self.assertIn("BHOLA_WINDOW_TITLE", config)
        self.assertIn("BHOLA_SCALE", config)
        self.assertIn("panel_width = math.floor(base_width * scale + 0.5)", config)
        self.assertIn("panel_height = math.floor(base_height * scale + 0.5)", config)
        self.assertIn("cairo_scale(cr, scale, scale)", pulse)
        for content in (config, pulse):
            self.assertIn("math.max(1.0, math.min(1.5, scale))", content)

    def test_cairo_font_rendering_uses_full_hinting(self) -> None:
        pulse = (ROOT / "conky/bhola_pulse.lua").read_text(encoding="utf-8")
        self.assertIn("cairo_font_options_create()", pulse)
        self.assertIn("CAIRO_ANTIALIAS_GRAY", pulse)
        self.assertIn("CAIRO_HINT_STYLE_FULL", pulse)
        self.assertIn("CAIRO_HINT_METRICS_ON", pulse)
        self.assertIn("cairo_set_font_options(cr, options)", pulse)
        self.assertIn("cairo_font_options_destroy(options)", pulse)
        self.assertLess(
            pulse.index("configure_font_rendering(cr)"),
            pulse.index("render.draw_dashboard(cr, metrics, elapsed)"),
        )

    def test_all_sections_are_static_in_required_order(self) -> None:
        pulse = (ROOT / "conky/bhola_pulse.lua").read_text(encoding="utf-8")
        renderer = (ROOT / "conky/bhola_render.lua").read_text(encoding="utf-8")
        self.assertIn("render.draw_dashboard(cr, metrics, elapsed)", pulse)
        for removed in ("scene_duration", "fade_duration", "current_scene", "next_scene", "draw_scene"):
            self.assertNotIn(removed, pulse)

        dashboard = renderer.split("function render.draw_dashboard", 1)[1]
        expected_calls = [
            "layout.left_x, layout.top_y, draw_system_pulse",
            "layout.left_x, layout.bottom_y, draw_status_grid",
            "layout.right_x, layout.top_y, draw_activity",
            "layout.right_x, layout.bottom_y, draw_network_services",
        ]
        for call in expected_calls:
            self.assertIn(call, dashboard)

    def test_modern_remains_default_and_nerd_is_separate(self) -> None:
        pulse = (ROOT / "conky/bhola_pulse.lua").read_text(encoding="utf-8")
        modern = (ROOT / "conky/bhola_render.lua").read_text(encoding="utf-8")
        nerd = (ROOT / "conky/bhola_render_nerd.lua").read_text(encoding="utf-8")

        self.assertIn('os.getenv("BHOLA_STYLE") or "modern"', pulse)
        self.assertIn('modern = "conky.bhola_render"', pulse)
        self.assertIn('nerd = "conky.bhola_render_nerd"', pulse)
        self.assertIn('error("invalid BHOLA_STYLE: " .. style)', pulse)
        self.assertIn("function render.draw_dashboard", modern)
        self.assertIn("function render.draw_ticker", modern)
        self.assertNotEqual(modern, nerd)

    def test_nerd_has_four_sections_ticker_and_ascii_widgets(self) -> None:
        nerd = (ROOT / "conky/bhola_render_nerd.lua").read_text(encoding="utf-8")
        for section in (
            "SYSTEM PULSE",
            "STATUS GRID",
            "SYSTEM ACTIVITY",
            "NETWORK & SERVICES",
        ):
            self.assertIn(section, nerd)
        for widget in (
            "local function bar(",
            "local function draw_ascii_vu(",
            "local function draw_vertical_equalizer(",
            "local function spinner(",
            "local function status_marker(",
            "function render.draw_ticker",
        ):
            self.assertIn(widget, nerd)
        for modern_primitive in ("cairo_arc", "cairo_line_to", "cairo_pattern", "cairo_polygon"):
            self.assertNotIn(modern_primitive, nerd)
        self.assertIn('string.rep("#"', nerd)
        self.assertIn('string.rep("="', nerd)

    def test_nerd_equalizers_are_stationary_eight_column_ascii_meters(self) -> None:
        nerd = (ROOT / "conky/bhola_render_nerd.lua").read_text(encoding="utf-8")
        self.assertIn("local vertical_equalizer_columns = 8", nerd)
        levels = lua_number(nerd, "vertical_equalizer_levels")
        self.assertGreaterEqual(levels, 5)
        self.assertIn("local vertical_equalizer_columns_per_group = 4", nerd)
        self.assertNotIn("meter_gains", nerd)
        self.assertIn('local meter_modes = {"now", "fast", "slow", "peak"}', nerd)
        self.assertIn("first = new_signal_state()", nerd)
        self.assertIn("second = new_signal_state()", nerd)
        self.assertIn("local function update_signal_state(", nerd)
        self.assertIn("local function update_stationary_meter(", nerd)
        self.assertIn("local function draw_vertical_equalizer(", nerd)
        self.assertIn('"---"', nerd)
        self.assertIn('vertical_equalizer_baseline = string.rep("-"', nerd)
        self.assertEqual(nerd.count('"N   F   S   P   N   F   S   P"'), 2)
        self.assertIn('draw_text(cr, 62, 160, "READ"', nerd)
        self.assertIn('draw_text(cr, 236, 160, "WRITE"', nerd)
        self.assertIn('draw_text(cr, 62, 182, "RX"', nerd)
        self.assertIn('draw_text(cr, 236, 182, "TX"', nerd)
        self.assertIn("metrics.disk_read_bytes_per_second", nerd)
        self.assertIn("metrics.disk_write_bytes_per_second", nerd)
        self.assertIn("metrics.network_download_bytes_per_second", nerd)
        self.assertIn("metrics.network_upload_bytes_per_second", nerd)
        fast_alpha = lua_number(nerd, "meter_fast_alpha")
        slow_alpha = lua_number(nerd, "meter_slow_alpha")
        self.assertGreater(fast_alpha, slow_alpha)
        self.assertIn("state.fast = state.fast + meter_fast_alpha * (value - state.fast)", nerd)
        self.assertIn("state.slow = state.slow + meter_slow_alpha * (value - state.slow)", nerd)
        self.assertIn("state.peak_hold = meter_peak_hold_updates", nerd)
        self.assertIn("state.peak_hold = state.peak_hold - 1", nerd)
        self.assertIn("state.peak = math.max(value, state.peak * meter_peak_decay)", nerd)
        self.assertIn("meter.levels[column] = meter_level(state[mode], meter.reference)", nerd)
        self.assertIn("x + (column - 1) * vertical_equalizer_column_step", nerd)
        for removed_history in (
            "cpu_history",
            "read_history",
            "write_history",
            "download_history",
            "upload_history",
            "recent_samples",
            "vertical_equalizer_values",
        ):
            self.assertNotIn(removed_history, nerd)
        bank = nerd.split("local function draw_vertical_equalizer", 1)[1].split(
            "local function spinner", 1
        )[0]
        self.assertNotIn("cairo_rectangle", bank)
        self.assertNotIn('draw_text(cr, x, y, "."', bank)

    def test_nerd_system_pulse_has_large_cpu_ram_and_nvme_ascii_vu_meters(self) -> None:
        nerd = (ROOT / "conky/bhola_render_nerd.lua").read_text(encoding="utf-8")
        pulse = nerd.split("local function draw_system_pulse", 1)[1].split(
            "local function draw_status_item", 1
        )[0]
        positions = int(lua_number(nerd, "ascii_needle_positions"))
        self.assertGreaterEqual(positions, 7)
        frames = nerd.split("local ascii_needle_frames", 1)[1].split(
            "local function ascii_needle_frame", 1
        )[0]
        self.assertEqual(frames.count("{top ="), positions)
        self.assertIn("\\\\", frames)
        self.assertIn("/", frames)
        self.assertIn("|", frames)
        self.assertIn('"    o    "', nerd)
        self.assertIn('"0  50 100"', nerd)
        self.assertIn('".---|---."', nerd)
        self.assertIn('draw_ascii_vu(cr, 60, 144, "CPU", metrics.cpu_percent, 100, "%"', pulse)
        self.assertIn('draw_ascii_vu(cr, 180, 144, "RAM", metrics.memory_percent, 100, "%"', pulse)
        self.assertIn('"NVM",\n        metrics.temperature_nvme_c,\n        100,', pulse)
        self.assertNotIn("needle_meter", nerd)
        self.assertNotIn('"OSC <"', pulse)
        self.assertNotIn('"SCN "', pulse)

    def test_nerd_removes_old_disk_and_network_line_equalizers(self) -> None:
        nerd = (ROOT / "conky/bhola_render_nerd.lua").read_text(encoding="utf-8")
        for removed in (
            '"R <" .. equalizer(read_history',
            '"W <" .. equalizer(write_history',
            '"RX <" .. equalizer(download_history',
            '"TX <" .. equalizer(upload_history',
        ):
            self.assertNotIn(removed, nerd)
        for modern_primitive in ("cairo_arc", "cairo_line_to", "cairo_pattern", "cairo_polygon"):
            self.assertNotIn(modern_primitive, nerd)

    def test_modern_renderer_has_no_vertical_equalizer_changes(self) -> None:
        modern = (ROOT / "conky/bhola_render.lua").read_text(encoding="utf-8")
        self.assertNotIn("vertical_equalizer", modern)
        self.assertNotIn("R   R   R   R   W   W   W   W", modern)

    def test_section_content_and_ticker_stay_inside_panel(self) -> None:
        renderer = (ROOT / "conky/bhola_render.lua").read_text(encoding="utf-8")
        left_x = lua_number(renderer, "left_x")
        right_x = lua_number(renderer, "right_x")
        bottom_y = lua_number(renderer, "bottom_y")
        ticker_y = lua_number(renderer, "ticker_y")
        ticker_baseline = lua_number(renderer, "ticker_baseline_y")
        width = lua_number(renderer, "width")
        height = lua_number(renderer, "height")
        self.assertEqual(left_x, 0)
        self.assertEqual(right_x, width / 2)
        self.assertLess(bottom_y + 274, ticker_y)
        self.assertLess(ticker_y, ticker_baseline)
        self.assertLess(ticker_baseline, height)

    def test_launcher_and_runtime_enforce_click_through_and_monitor_scales(self) -> None:
        launcher = (ROOT / "scripts/run-dev.sh").read_text(encoding="utf-8")
        runtime = (ROOT / "src/bhola_runtime.py").read_text(encoding="utf-8")
        helper = (ROOT / "src/bhola_clickthrough.py").read_text(encoding="utf-8")

        self.assertIn("src.bhola_clickthrough --check", launcher)
        self.assertIn("src.bhola_runtime --check", launcher)
        self.assertIn(
            'python3 -m src.bhola_runtime --state-file "$state_file" --style "$dashboard_style"',
            launcher,
        )
        self.assertIn('dashboard_style=$(python3 -m src.bhola_style', launcher)
        self.assertIn('"src.bhola_clickthrough"', runtime)
        self.assertIn('"--pid"', runtime)
        self.assertIn('"--name"', runtime)
        self.assertIn('f"--xinerama-head={launch.index}"', runtime)
        self.assertIn('variable_name = f"BHOLA_SCALE_HEAD_{index}"', runtime)
        self.assertIn('"BHOLA_SCALE": launch.scale', runtime)
        self.assertIn('"BHOLA_STYLE": style', runtime)
        self.assertIn("discoverer=discover_monitor_snapshot", runtime)
        self.assertIn("required_observations: int = 2", runtime)
        self.assertIn("ShapeInput", helper)
        self.assertIn("count.value == 0", helper)


if __name__ == "__main__":
    unittest.main()
