require "cairo"

local nerd = require("conky.bhola_render_nerd")

local render = {}

local width = 760
local height = 720
local trace_top = 526
local trace_height = 188
local trace_limit = 12
local trace_line_step = 12
local trace_sample_seconds = 1

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
    {key = "service_numberpad", category = "SVC", label = "numberpad"},
    {key = "service_ntfy", category = "SVC", label = "ntfy"},
    {key = "service_monitors", category = "SVC", label = "local-mon"},
}

local events = {}
local previous = {}
local initialized = false
local last_epoch = -1
local last_trace_sample_epoch = 0
local trace_sample_slot = 0
local previous_cpu_thermal_band = nil

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

    local units = {"B/s", "KB/s", "MB/s", "GB/s"}
    local scaled = math.max(0, value)
    local unit_index = 1
    while scaled >= 1024 and unit_index < #units do
        scaled = scaled / 1024
        unit_index = unit_index + 1
    end

    if unit_index == 1 then
        return string.format("%.0f %s", scaled, units[unit_index])
    end
    return string.format("%.1f %s", scaled, units[unit_index])
end

local function event_time(epoch)
    if type(epoch) ~= "number" or epoch <= 0 then
        return "--:--:--"
    end
    return os.date("%H:%M:%S", epoch)
end

local function push_event(category, message, epoch)
    events[#events + 1] = {
        category = category,
        message = message,
        time = event_time(epoch),
    }
    while #events > trace_limit do
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

local function bootstrap(metrics, epoch)
    push_event("PULSE", "cinematic telemetry linked", epoch)
    push_event(
        "NET",
        "internet=" .. status(metrics.network_internet_status)
            .. " dns=" .. status(metrics.network_dns_status)
            .. " https=" .. status(metrics.network_https_status),
        epoch
    )
    push_event(
        "SVC",
        "ufw=" .. status(metrics.service_ufw)
            .. " vpn=" .. status(metrics.service_fortivpn)
            .. " ntfy=" .. status(metrics.service_ntfy),
        epoch
    )
    push_event(
        "SYS",
        "power=" .. status(metrics.power_source)
            .. " cpu-temp=" .. cpu_thermal_band(metrics.temperature_cpu_c),
        epoch
    )
    snapshot(metrics)
    initialized = true
    last_trace_sample_epoch = epoch
end

local function emit_trace_sample(metrics, epoch)
    trace_sample_slot = (trace_sample_slot % 4) + 1

    if trace_sample_slot == 1 then
        push_event(
            "PULSE",
            "heartbeat cpu=" .. number_or_na(metrics.cpu_percent, "%.1f%%")
                .. " ram=" .. number_or_na(metrics.memory_percent, "%.1f%%")
                .. " load=" .. number_or_na(metrics.load_1, "%.2f"),
            epoch
        )
    elseif trace_sample_slot == 2 then
        push_event(
            "NET",
            "rx=" .. format_rate(metrics.network_download_bytes_per_second)
                .. " tx=" .. format_rate(metrics.network_upload_bytes_per_second)
                .. " ping=" .. number_or_na(metrics.network_latency_ms, "%.0fms")
                .. " internet=" .. status(metrics.network_internet_status),
            epoch
        )
    elseif trace_sample_slot == 3 then
        push_event(
            "SYS",
            "disk-r=" .. format_rate(metrics.disk_read_bytes_per_second)
                .. " disk-w=" .. format_rate(metrics.disk_write_bytes_per_second)
                .. " proc=" .. number_or_na(metrics.process_count, "%.0f")
                .. " temp=" .. number_or_na(metrics.temperature_cpu_c, "%.0fC"),
            epoch
        )
    else
        push_event(
            "SVC",
            "ufw=" .. status(metrics.service_ufw)
                .. " vpn=" .. status(metrics.service_fortivpn)
                .. " ntfy=" .. status(metrics.service_ntfy)
                .. " local-mon=" .. status(metrics.service_monitors),
            epoch
        )
    end
end

local function collect_changes(metrics, epoch)
    for _, field in ipairs(tracked_fields) do
        local current = metrics[field.key]
        local before = previous[field.key]
        if tostring(current) ~= tostring(before) then
            push_event(
                field.category,
                field.label .. " " .. status(before) .. " -> " .. status(current),
                epoch
            )
            previous[field.key] = current
        end
    end

    local thermal = cpu_thermal_band(metrics.temperature_cpu_c)
    if thermal ~= previous_cpu_thermal_band then
        push_event(
            "SYS",
            "cpu thermal " .. status(previous_cpu_thermal_band) .. " -> " .. status(thermal),
            epoch
        )
        previous_cpu_thermal_band = thermal
    end

    if epoch > 0 and epoch - last_trace_sample_epoch >= trace_sample_seconds then
        emit_trace_sample(metrics, epoch)
        last_trace_sample_epoch = epoch
    end
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

local function draw_glitch(cr, animation_time)
    local phase = animation_time % 13.0
    if phase >= 0.16 then
        return
    end

    local y = 70 + math.floor((animation_time * 37) % 390)
    set_source(cr, colors.magenta, 0.13)
    cairo_rectangle(cr, 0, y, width, 4)
    cairo_fill(cr)
    set_source(cr, colors.cyan, 0.11)
    cairo_rectangle(cr, 0, y + 7, width, 2)
    cairo_fill(cr)
    draw_text(cr, 608, y - 3, "SYNC//OFFSET", 7, colors.magenta, true, 0.72)
end

local boot_lines = {
    "BHOLA BIOS ................. LINK",
    "MEMORY MAP ................. OK",
    "NETWORK PROBES ............. ARMED",
    "SERVICE GRID ............... SYNC",
    "NERD CINEMATIC ............. ONLINE",
}

local function draw_boot_sequence(cr, animation_time)
    local duration = 4.6
    if animation_time >= duration then
        return
    end

    set_source(cr, colors.black, 0.90)
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

local function draw_live_trace(cr, animation_time)
    set_source(cr, colors.black, 0.80)
    cairo_rectangle(cr, 8, trace_top, width - 16, trace_height)
    cairo_fill(cr)

    set_source(cr, colors.cyan, 0.38)
    cairo_set_line_width(cr, 1)
    cairo_rectangle(cr, 8.5, trace_top + 0.5, width - 17, trace_height - 1)
    cairo_stroke(cr)

    draw_text(cr, 18, trace_top + 13, "LIVE TRACE // REAL CACHE STREAM // 12 LINES", 7, colors.cyan, true, 0.92)
    local cursor_alpha = 0.30 + 0.70 * math.abs(math.sin(animation_time * 5.5))
    draw_text(cr, 680, trace_top + 13, "STREAM > _", 7, colors.green, true, cursor_alpha)

    local count = #events
    local first_index = math.max(1, count - trace_limit + 1)
    local visible_count = math.max(1, count - first_index + 1)
    local y = trace_top + 31

    for index = first_index, count do
        local event = events[index]
        if event ~= nil then
            local rank = index - first_index + 1
            local fade = 0.30 + 0.70 * (rank / visible_count)
            local color = category_colors[event.category] or colors.white
            local marker = index == count and ">" or " "
            draw_text(cr, 18, y, marker, 7, color, true, fade)
            draw_text(cr, 30, y, event.time .. " [" .. event.category .. "]", 7, color, true, fade)
            draw_text(cr, 132, y, event.message, 7, colors.white, false, fade * 0.96)
            y = y + trace_line_step
        end
    end
end

function render.update(metrics)
    nerd.update(metrics)

    local epoch = metrics.updated_at_epoch or 0
    if epoch == last_epoch or epoch <= 0 then
        return
    end
    last_epoch = epoch

    if not initialized then
        bootstrap(metrics, epoch)
        return
    end
    collect_changes(metrics, epoch)
end

function render.draw_dashboard(cr, metrics, animation_time)
    nerd.draw_dashboard(cr, metrics, animation_time)
    draw_hud(cr)
    draw_glitch(cr, animation_time)
    draw_boot_sequence(cr, animation_time)
    draw_scanlines(cr, 0, trace_top - 1)
end

function render.draw_ticker(cr, metrics, alpha, animation_time)
    draw_live_trace(cr, animation_time)
    draw_scanlines(cr, trace_top, height)
end

return render
