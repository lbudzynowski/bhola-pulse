require "cairo"

local data = require("conky.bhola_data")
local style = os.getenv("BHOLA_STYLE") or "modern"
local state_file = os.getenv("BHOLA_STATE_FILE") or "state/dashboard.json"
local renderer_modules = {
    modern = "conky.bhola_render",
    nerd = "conky.bhola_render_nerd",
}
if renderer_modules[style] == nil then
    error("invalid BHOLA_STYLE: " .. style)
end
local render = require(renderer_modules[style])

local frame = 0
local update_interval = tonumber(os.getenv("BHOLA_UPDATE_INTERVAL")) or 0.15
local default_scale = 1.25
local scale = tonumber(os.getenv("BHOLA_SCALE")) or default_scale
scale = math.max(1.0, math.min(1.5, scale))

local function configure_font_rendering(cr)
    local options = cairo_font_options_create()
    cairo_font_options_set_antialias(options, CAIRO_ANTIALIAS_GRAY)
    cairo_font_options_set_hint_style(options, CAIRO_HINT_STYLE_FULL)
    cairo_font_options_set_hint_metrics(options, CAIRO_HINT_METRICS_ON)
    cairo_set_font_options(cr, options)
    cairo_font_options_destroy(options)
end

function conky_draw_bhola()
    if conky_window == nil then
        return
    end

    frame = frame + 1
    local metrics = data.read(state_file)
    render.update(metrics)

    local surface = cairo_xlib_surface_create(
        conky_window.display,
        conky_window.drawable,
        conky_window.visual,
        conky_window.width,
        conky_window.height
    )
    local cr = cairo_create(surface)
    cairo_scale(cr, scale, scale)
    configure_font_rendering(cr)

    local elapsed = (frame - 1) * update_interval
    render.draw_dashboard(cr, metrics, elapsed)
    render.draw_ticker(cr, metrics, 1, elapsed)

    cairo_destroy(cr)
    cairo_surface_destroy(surface)
end
