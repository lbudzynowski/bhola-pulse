require "cairo"

local panel = {}

local lower_top = 526
local lower_height = 188
local editor_x = 8
local editor_width = 364
local stream_x = 380
local stream_width = 372
local editor_visible_lines = 14
local editor_line_step = 10
local stream_visible_lines = 14
local stream_line_step = 10
local stream_buffer_limit = 48
local stream_records_per_second = 4
local source_char_step_seconds = 0.02
local source_hold_seconds = 2.0

local colors = {
    black = {0.01, 0.02, 0.03},
    cyan = {0.18, 0.96, 1.00},
    green = {0.28, 1.00, 0.48},
    amber = {1.00, 0.78, 0.24},
    magenta = {1.00, 0.22, 0.72},
    gray = {0.52, 0.62, 0.66},
    white = {0.91, 0.96, 0.98},
}

local category_colors = {
    PULSE = colors.cyan,
    SYS = colors.amber,
    NET = colors.green,
    SVC = colors.magenta,
}

local tracked_fields = {
    {key = "provider_status", category = "PULSE", label = "provider"},
    {key = "power_source", category = "SYS", label = "power"},
    {key = "battery_state", category = "SYS", label = "battery"},
    {key = "network_route_status", category = "NET", label = "route"},
    {key = "network_gateway_status", category = "NET", label = "gateway"},
    {key = "network_internet_status", category = "NET", label = "internet"},
    {key = "network_dns_status", category = "NET", label = "dns"},
    {key = "network_https_status", category = "NET", label = "https"},
    {key = "service_ufw", category = "SVC", label = "ufw"},
    {key = "service_fortivpn", category = "SVC", label = "vpn"},
    {key = "service_ntfy", category = "SVC", label = "ntfy"},
    {key = "service_monitors", category = "SVC", label = "local-mon"},
}

-- Exact contiguous excerpt from src/bhola_provider.py, lines 130 through EOF.
-- It is presentation source text only: the panel never executes or mutates it.
local source_line_base = 130
local source_lines = require("conky.bhola_source_excerpt")

local source_total_chars = 0
for _, line in ipairs(source_lines) do
    source_total_chars = source_total_chars + #line + 1
end

local events = {}
local previous = {}
local initialized = false
local last_epoch = -1
local event_sequence = 0
local last_visual_slot = -1
local previous_cpu_thermal_band = nil
local source_typed_chars = 0
local source_last_step_time = nil
local source_last_draw_time = nil
local source_hold_started_at = nil

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

local function status(value)
    if value == nil or value == "" then
        return "UNKNOWN"
    end
    return string.upper(tostring(value))
end

local function number_or_na(value, format)
    if type(value) ~= "number" then
        return "N/A"
    end
    return string.format(format, value)
end

local function format_rate(value)
    if type(value) ~= "number" then
        return "N/A"
    end

    local units = {"B", "K", "M", "G"}
    local scaled = math.max(0, value)
    local unit_index = 1
    while scaled >= 1024 and unit_index < #units do
        scaled = scaled / 1024
        unit_index = unit_index + 1
    end

    if unit_index == 1 then
        return string.format("%.0f%s", scaled, units[unit_index])
    end
    return string.format("%.1f%s", scaled, units[unit_index])
end

local function event_time(epoch)
    if type(epoch) ~= "number" or epoch <= 0 then
        return "--:--:--"
    end
    return os.date("%H:%M:%S", epoch)
end

local function push_event(category, message, epoch, kind)
    event_sequence = event_sequence + 1
    events[#events + 1] = {
        sequence = event_sequence,
        category = category,
        message = message,
        time = event_time(epoch),
        kind = kind or "EVT",
    }
    while #events > stream_buffer_limit do
        table.remove(events, 1)
    end
end

local function cpu_thermal_band(value)
    if type(value) ~= "number" then
        return "unknown"
    elseif value >= 85 then
        return "alarm"
    elseif value >= 75 then
        return "warm"
    end
    return "nominal"
end

local function snapshot(metrics)
    for _, field in ipairs(tracked_fields) do
        previous[field.key] = metrics[field.key]
    end
    previous_cpu_thermal_band = cpu_thermal_band(metrics.temperature_cpu_c)
end

local function emit_sample(metrics, epoch, slot)
    if slot == 1 then
        push_event(
            "PULSE",
            "cpu=" .. number_or_na(metrics.cpu_percent, "%.1f%%")
                .. " ram=" .. number_or_na(metrics.memory_percent, "%.1f%%")
                .. " load=" .. number_or_na(metrics.load_1, "%.2f"),
            epoch,
            "SMP"
        )
    elseif slot == 2 then
        push_event(
            "NET",
            "rx=" .. format_rate(metrics.network_download_bytes_per_second)
                .. " tx=" .. format_rate(metrics.network_upload_bytes_per_second)
                .. " ping=" .. number_or_na(metrics.network_latency_ms, "%.0fms")
                .. " inet=" .. status(metrics.network_internet_status),
            epoch,
            "SMP"
        )
    elseif slot == 3 then
        push_event(
            "SYS",
            "rd=" .. format_rate(metrics.disk_read_bytes_per_second)
                .. " wr=" .. format_rate(metrics.disk_write_bytes_per_second)
                .. " p=" .. number_or_na(metrics.process_count, "%.0f")
                .. " t=" .. number_or_na(metrics.temperature_cpu_c, "%.0fC"),
            epoch,
            "SMP"
        )
    else
        push_event(
            "SVC",
            "ufw=" .. status(metrics.service_ufw)
                .. " vpn=" .. status(metrics.service_fortivpn)
                .. " ntfy=" .. status(metrics.service_ntfy)
                .. " mon=" .. status(metrics.service_monitors),
            epoch,
            "SMP"
        )
    end
end

local function emit_visual_samples(metrics, animation_time)
    local current_slot = math.floor(animation_time * stream_records_per_second)
    if last_visual_slot < 0 then
        last_visual_slot = current_slot - 1
    end
    if current_slot <= last_visual_slot then
        return
    end

    local first_slot = math.max(last_visual_slot + 1, current_slot - stream_records_per_second + 1)
    for sample_index = first_slot, current_slot do
        emit_sample(metrics, metrics.updated_at_epoch or 0, (sample_index % 4) + 1)
    end
    last_visual_slot = current_slot
end

function panel.update(metrics)
    local epoch = metrics.updated_at_epoch or 0
    if epoch <= 0 or epoch == last_epoch then
        return
    end
    last_epoch = epoch

    if not initialized then
        snapshot(metrics)
        push_event("PULSE", "telemetry linked", epoch, "EVT")
        initialized = true
        return
    end

    for _, field in ipairs(tracked_fields) do
        local current = metrics[field.key]
        local before = previous[field.key]
        if tostring(current) ~= tostring(before) then
            push_event(
                field.category,
                field.label .. " " .. status(before) .. " -> " .. status(current),
                epoch,
                "EVT"
            )
            previous[field.key] = current
        end
    end

    local thermal = cpu_thermal_band(metrics.temperature_cpu_c)
    if thermal ~= previous_cpu_thermal_band then
        push_event(
            "SYS",
            "thermal " .. status(previous_cpu_thermal_band) .. " -> " .. status(thermal),
            epoch,
            "EVT"
        )
        previous_cpu_thermal_band = thermal
    end
end

local function draw_panel_frame(cr, x, width_value)
    set_source(cr, colors.black, 0.82)
    cairo_rectangle(cr, x, lower_top, width_value, lower_height)
    cairo_fill(cr)

    set_source(cr, colors.cyan, 0.36)
    cairo_set_line_width(cr, 1)
    cairo_rectangle(cr, x + 0.5, lower_top + 0.5, width_value - 1, lower_height - 1)
    cairo_stroke(cr)
end

local function source_line_color(line)
    local stripped = string.match(line, "^%s*(.*)$") or line
    if string.match(stripped, "^def ") then
        return colors.cyan
    elseif string.find(line, "ScheduledSource", 1, true) then
        return colors.amber
    elseif string.find(line, '"', 1, true) then
        return colors.green
    elseif string.find(line, "True", 1, true) or string.find(line, "None", 1, true) then
        return colors.magenta
    end
    return colors.white
end

local function advance_source_typing(animation_time)
    -- draw_scene() can be called repeatedly with the same animation timestamp
    -- during glitch slicing. Advance at most once for a rendered timestamp and
    -- at most one character per visible step so the cursor never jumps words.
    if source_last_draw_time == animation_time then
        return
    end
    source_last_draw_time = animation_time

    if source_typed_chars >= source_total_chars then
        if source_hold_started_at == nil then
            source_hold_started_at = animation_time
            return
        end
        if animation_time - source_hold_started_at >= source_hold_seconds then
            source_typed_chars = 0
            source_last_step_time = animation_time
            source_hold_started_at = nil
        end
        return
    end

    source_hold_started_at = nil
    if source_last_step_time == nil then
        source_last_step_time = animation_time
        return
    end

    if animation_time - source_last_step_time >= source_char_step_seconds then
        source_typed_chars = math.min(source_total_chars, source_typed_chars + 1)
        source_last_step_time = animation_time
    end
end

local function source_typing_state(animation_time)
    advance_source_typing(animation_time)

    local remaining = source_typed_chars
    local current_line = 1
    local current_col = 0

    for index, line in ipairs(source_lines) do
        local line_cost = #line + 1
        if remaining >= line_cost then
            remaining = remaining - line_cost
            current_line = math.min(#source_lines, index + 1)
            current_col = 0
        else
            current_line = index
            current_col = math.min(#line, remaining)
            break
        end
    end

    if source_typed_chars >= source_total_chars then
        current_line = #source_lines
        current_col = #source_lines[#source_lines]
    end

    return current_line, current_col
end

local function draw_source_editor(cr, animation_time)
    draw_panel_frame(cr, editor_x, editor_width)
    draw_text(cr, editor_x + 8, lower_top + 13, "SOURCE // src/bhola_provider.py", 6.2, colors.cyan, true, 0.96)
    draw_text(cr, editor_x + editor_width - 62, lower_top + 13, "AUTO-TYPE", 5.8, colors.green, true, 0.92)

    local current_line, current_col = source_typing_state(animation_time)
    local first_line = math.max(1, current_line - editor_visible_lines + 1)
    local last_line = math.min(#source_lines, first_line + editor_visible_lines - 1)
    local code_y = lower_top + 29
    local code_x = editor_x + 37

    cairo_save(cr)
    cairo_rectangle(cr, editor_x + 2, lower_top + 18, editor_width - 4, lower_height - 36)
    cairo_clip(cr)

    for index = first_line, last_line do
        if index <= current_line then
            local full_line = source_lines[index]
            local visible_text = full_line
            if index == current_line then
                -- Never render any character to the right of the cursor.
                visible_text = string.sub(full_line, 1, current_col)
            end
            local y = code_y + (index - first_line) * editor_line_step
            draw_text(cr, editor_x + 8, y, string.format("%03d", source_line_base + index - 1), 5.6, colors.gray, false, 0.62)
            draw_text(cr, editor_x + 28, y, "│", 5.6, colors.gray, false, 0.34)
            draw_text(cr, code_x, y, visible_text, 6.0, source_line_color(full_line), false, 0.94)
        end
    end

    local cursor_row = current_line - first_line
    if cursor_row >= 0 and cursor_row < editor_visible_lines then
        local cursor_y = code_y + cursor_row * editor_line_step
        local cursor_alpha = 0.30 + 0.70 * math.abs(math.sin(animation_time * 8.0))
        -- Use the same monospace text layout as the source itself. Spaces are
        -- invisible; the block therefore lands exactly in the next character
        -- cell after visible_text, with no hand-tuned pixel approximation.
        draw_text(
            cr,
            code_x,
            cursor_y,
            string.rep(" ", current_col) .. "█",
            6.0,
            colors.green,
            false,
            cursor_alpha
        )
    end
    cairo_restore(cr)

    draw_text(
        cr,
        editor_x + 8,
        lower_top + lower_height - 7,
        string.format("Ln %03d  Col %02d  READ-ONLY", source_line_base + current_line - 1, current_col + 1),
        5.5,
        colors.gray,
        false,
        0.74
    )
end

local function draw_event_stream(cr, metrics, animation_time)
    emit_visual_samples(metrics, animation_time)
    draw_panel_frame(cr, stream_x, stream_width)
    draw_text(cr, stream_x + 8, lower_top + 13, "REAL CACHE // EVENT STREAM", 6.2, colors.cyan, true, 0.96)
    draw_text(cr, stream_x + stream_width - 53, lower_top + 13, "4 REC/S", 5.8, colors.green, true, 0.92)

    local count = #events
    local first_index = math.max(1, count - stream_visible_lines + 1)
    local visible_count = math.max(1, count - first_index + 1)
    local y = lower_top + 29

    cairo_save(cr)
    cairo_rectangle(cr, stream_x + 2, lower_top + 18, stream_width - 4, lower_height - 36)
    cairo_clip(cr)

    for index = first_index, count do
        local event = events[index]
        local rank = index - first_index + 1
        local fade = 0.24 + 0.76 * (rank / visible_count)
        local color = category_colors[event.category] or colors.white
        local marker = index == count and ">" or " "
        draw_text(cr, stream_x + 6, y, marker, 5.6, color, true, fade)
        draw_text(cr, stream_x + 14, y, string.format("%04d", event.sequence % 10000), 5.5, colors.gray, false, fade * 0.72)
        draw_text(cr, stream_x + 39, y, event.time, 5.5, colors.gray, false, fade * 0.78)
        draw_text(cr, stream_x + 88, y, event.kind, 5.5, event.kind == "EVT" and colors.magenta or colors.gray, true, fade)
        draw_text(cr, stream_x + 111, y, event.category, 5.5, color, true, fade)
        draw_text(cr, stream_x + 140, y, event.message, 5.6, colors.white, false, fade * 0.96)
        y = y + stream_line_step
    end
    cairo_restore(cr)

    local pulse_alpha = 0.34 + 0.66 * math.abs(math.sin(animation_time * 6.5))
    draw_text(cr, stream_x + 8, lower_top + lower_height - 7, "CACHE VALUES // TRANSITIONS PRIORITY", 5.5, colors.gray, false, 0.74)
    draw_text(cr, stream_x + stream_width - 16, lower_top + lower_height - 7, "_", 6.0, colors.green, true, pulse_alpha)
end

function panel.draw(cr, metrics, animation_time)
    draw_source_editor(cr, animation_time)
    draw_event_stream(cr, metrics, animation_time)
end

return panel