require "cairo"

local nerd = require("conky.bhola_render_nerd")
local cinetty = require("conky.bhola_cinetty_panels")

local render = {}

local width = 760
local height = 720
local boot_duration = 4.6
local glitch_lead_seconds = 4.0
local glitch_cycle_seconds = 11.7
local glitch_burst_seconds = 1.6

local colors = {
    black = {0.01, 0.02, 0.03},
    cyan = {0.18, 0.96, 1.00},
    green = {0.28, 1.00, 0.48},
    magenta = {1.00, 0.22, 0.72},
    gray = {0.52, 0.62, 0.66},
    white = {0.91, 0.96, 0.98},
}

local function set_source(cr, color, alpha)
    cairo_set_source_rgba(cr, color[1], color[2], color[3], alpha or 1)
end

local function draw_text(cr, x, y, text, size, color, bold, alpha)
    cairo_select_font_face(
        cr,
        "DejaVu Sans Mono",
        CAIRO_FONT_SLANT_NORMAL,
        bold and CAIRO_FONT_WEIGHT_BOLD or CAIRO_FONT_WEIGHT_NORMAL
    )
    cairo_set_font_size(cr, size)
    set_source(cr, color, alpha or 1)
    cairo_move_to(cr, x, y)
    cairo_show_text(cr, text)
end

local function draw_hud(cr)
    set_source(cr, colors.cyan, 0.42)
    cairo_set_line_width(cr, 1)

    local inset = 5
    local arm = 16
    local points = {
        {inset, inset, inset + arm, inset, inset, inset + arm},
        {width - inset, inset, width - inset - arm, inset, width - inset, inset + arm},
        {inset, height - inset, inset + arm, height - inset, inset, height - inset - arm},
        {width - inset, height - inset, width - inset - arm, height - inset, width - inset, height - inset - arm},
    }

    for _, point in ipairs(points) do
        cairo_move_to(cr, point[1], point[2])
        cairo_line_to(cr, point[3], point[4])
        cairo_move_to(cr, point[1], point[2])
        cairo_line_to(cr, point[5], point[6])
    end
    cairo_stroke(cr)
end

local function draw_scanlines(cr, from_y, to_y)
    set_source(cr, colors.black, 0.09)
    local first = from_y or 0
    local last = to_y or height
    for y = first, last, 12 do
        cairo_rectangle(cr, 0, y, width, 1)
    end
    cairo_fill(cr)
end

local boot_lines = {
    "BHOLA BIOS ................. LINK",
    "MEMORY MAP ................. OK",
    "NETWORK PROBES ............. ARMED",
    "SERVICE GRID ............... SYNC",
    "NERD CINEMATIC ............. ONLINE",
}

local function draw_boot_sequence(cr, animation_time)
    if animation_time >= boot_duration then
        return
    end

    set_source(cr, colors.black, 0.94)
    cairo_rectangle(cr, 0, 0, width, height)
    cairo_fill(cr)

    local visible = math.min(#boot_lines, math.floor(animation_time / 0.72) + 1)
    draw_text(cr, 54, 96, "BHOLA PULSE // CINEMATIC BOOT", 17, colors.cyan, true, 1)
    draw_text(cr, 54, 119, "LOCAL TELEMETRY / READ-ONLY PRESENTATION LAYER", 8, colors.gray, false, 0.9)

    for index = 1, visible do
        local color = index == visible and colors.white or colors.green
        draw_text(cr, 72, 164 + (index - 1) * 38, boot_lines[index], 11, color, true, 1)
    end

    local cursor_alpha = 0.35 + 0.65 * math.abs(math.sin(animation_time * 7.5))
    draw_text(cr, 72, 382, "> _", 12, colors.cyan, true, cursor_alpha)
end

local function draw_scene(cr, metrics, animation_time)
    nerd.draw_dashboard(cr, metrics, animation_time)
    draw_hud(cr)
    cinetty.draw(cr, metrics, animation_time)
    draw_scanlines(cr, 0, height)
end

local glitch_slices = {
    {54, 17, -24},
    {111, 11, 16},
    {186, 25, -19},
    {278, 13, 28},
    {367, 19, -15},
    {462, 12, 22},
    {548, 23, -30},
    {641, 15, 18},
}

-- Selected reference #1 from the user's terminal-skull screenshot. Keep this
-- deliberately asymmetric side-profile art; do not "improve" it into a new skull.
local skull_lines = {
    [[       ,gS$$$Sk.]],
    [[     ,d$$$$$$$$$$k.]],
    [[   ,?^?$?°`   `?$$$$$L.]],
    [[  ,?    $SL._  ,d$iI$$$$L]],
    [[ j$Su:$$$$$$$$$?:iI$$$$Sb]],
    [[:?°?^4$$$$$"°?$$L:iI$$$I:]],
    [[:'    ' / `?$' .   `?Li$$$$I:]],
    [[ `      ,            `?ki$$I?]],
    [[   :.       $k _       `?Si?]],
    [[  .,_._     i$$%?-:i?']],
    [[  ?%uS%uo d$$?' .?º`]],
    [[  S$$$$$$$$$$$i]],
    [[ .?$$$$?]],
}

local function glitch_state(animation_time)
    local elapsed = animation_time - boot_duration - glitch_lead_seconds
    if elapsed < 0 then
        return false, 0, 0
    end

    local cycle_index = math.floor(elapsed / glitch_cycle_seconds)
    local phase = elapsed - cycle_index * glitch_cycle_seconds
    if phase >= glitch_burst_seconds then
        return false, phase, cycle_index
    end
    return true, phase, cycle_index
end

local function glitch_strength(phase)
    local normalized = math.max(0, math.min(1, phase / glitch_burst_seconds))
    return math.sin(normalized * math.pi)
end

local function draw_glitch_noise(cr, phase, strength)
    local seed = math.floor(phase * 1000)
    for index = 1, 9 do
        local y = 44 + ((seed * 17 + index * 83) % 635)
        local x = ((seed * 11 + index * 109) % 620)
        local w = 28 + ((seed + index * 37) % 118)
        local color = index % 2 == 0 and colors.cyan or colors.magenta
        set_source(cr, color, 0.10 + 0.24 * strength)
        cairo_rectangle(cr, x, y, w, 1 + (index % 3))
        cairo_fill(cr)
    end
end

local function draw_ascii_skull(cr, phase, cycle_index)
    if cycle_index % 3 ~= 0 then
        return
    end
    if phase < 0.30 or phase > 1.35 then
        return
    end

    local skull_phase = (phase - 0.30) / 1.05
    local envelope = math.sin(math.max(0, math.min(1, skull_phase)) * math.pi)
    local base_x = 220
    local base_y = 135
    local line_step = 20
    local frame_seed = math.floor(phase * 100)

    for index, line in ipairs(skull_lines) do
        local tear = ((index * 7 + frame_seed * 3) % 9) - 4
        local dx = tear * (1.2 + 2.8 * envelope)
        local y = base_y + (index - 1) * line_step
        local dropout = ((index * 13 + frame_seed) % 29) == 0
        if not dropout then
            draw_text(cr, base_x + dx - 3, y, line, 14, colors.cyan, true, 0.18 + 0.42 * envelope)
            draw_text(cr, base_x + dx + 3, y, line, 14, colors.magenta, true, 0.18 + 0.42 * envelope)
            draw_text(cr, base_x + dx, y, line, 14, colors.white, true, 0.40 + 0.55 * envelope)
        end
    end
end

local function draw_glitch_burst(cr, metrics, animation_time, phase, cycle_index)
    local strength = glitch_strength(phase)

    for index, slice in ipairs(glitch_slices) do
        local y = slice[1]
        local h = slice[2]
        local base_dx = slice[3]
        local wobble = (((cycle_index + index * 5) % 5) - 2) * 2
        local dx = (base_dx + wobble) * (0.35 + 0.65 * strength)

        cairo_save(cr)
        cairo_rectangle(cr, 0, y, width, h)
        cairo_clip(cr)
        set_source(cr, colors.black, 0.48 + 0.30 * strength)
        cairo_paint(cr)
        cairo_translate(cr, dx, 0)
        draw_scene(cr, metrics, animation_time)
        cairo_restore(cr)

        local edge_color = index % 2 == 0 and colors.cyan or colors.magenta
        set_source(cr, edge_color, 0.16 + 0.30 * strength)
        cairo_rectangle(cr, math.max(0, dx > 0 and 0 or width - 8), y, 8, math.max(1, h - 1))
        cairo_fill(cr)
    end

    draw_glitch_noise(cr, phase, strength)
    draw_ascii_skull(cr, phase, cycle_index)
end

function render.update(metrics)
    nerd.update(metrics)
    cinetty.update(metrics)
end

function render.draw_dashboard(cr, metrics, animation_time)
    if animation_time < boot_duration then
        nerd.draw_dashboard(cr, metrics, animation_time)
        draw_hud(cr)
        draw_boot_sequence(cr, animation_time)
        draw_scanlines(cr, 0, height)
        return
    end

    draw_scene(cr, metrics, animation_time)

    local active, phase, cycle_index = glitch_state(animation_time)
    if active then
        draw_glitch_burst(cr, metrics, animation_time, phase, cycle_index)
    end
end

function render.draw_ticker(cr, metrics, alpha, animation_time)
    -- Cinematic owns the full 760x720 scene; the CineTTY-inspired lower panels
    -- replace the ordinary NERD ticker and participate in glitch slicing.
end

return render
