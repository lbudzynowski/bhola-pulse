local render = {}

render.layout = {
    width = 760,
    height = 570,
    left_x = 0,
    right_x = 380,
    top_y = 0,
    bottom_y = 250,
    ticker_y = 530,
    ticker_baseline_y = 555,
}

local layout = render.layout

local colors = {
    white = 0xf8fafc,
    green = 0x4ade80,
    cyan = 0x22d3ee,
    amber = 0xfbbf24,
    red = 0xf87171,
    magenta = 0xe879f9,
    gray = 0x94a3b8,
    dark = 0x020617,
}

local last_epoch = -1
local ticker_index = 1
local ticker_x = layout.width
local ticker_text = ""
local last_ticker_time = nil

local vertical_equalizer_columns = 8
local vertical_equalizer_levels = 5
local vertical_equalizer_columns_per_group = 4
local vertical_equalizer_column_step = 29
local vertical_equalizer_row_step = 11
local vertical_equalizer_baseline = string.rep("-", 38)
local meter_modes = {"now", "fast", "slow", "peak"}
local meter_fast_alpha = 0.55
local meter_slow_alpha = 0.18
local meter_peak_hold_updates = 2
local meter_peak_decay = 0.88
local meter_reference_decay = 0.90

local function new_signal_state()
    return {now = 0, fast = 0, slow = 0, peak = 0, peak_hold = 0, initialized = false}
end

local disk_meter = {
    first = new_signal_state(),
    second = new_signal_state(),
    levels = {},
    reference = 1,
}
local network_meter = {
    first = new_signal_state(),
    second = new_signal_state(),
    levels = {},
    reference = 1,
}

local polish_weekdays = {
    "niedziela",
    "poniedzialek",
    "wtorek",
    "sroda",
    "czwartek",
    "piatek",
    "sobota",
}

local polish_months = {
    "stycznia",
    "lutego",
    "marca",
    "kwietnia",
    "maja",
    "czerwca",
    "lipca",
    "sierpnia",
    "wrzesnia",
    "pazdziernika",
    "listopada",
    "grudnia",
}

local function rgba(hex, alpha)
    local red = math.floor(hex / 0x10000) % 0x100
    local green = math.floor(hex / 0x100) % 0x100
    local blue = hex % 0x100
    return red / 255, green / 255, blue / 255, alpha
end

local function set_source(cr, color, alpha)
    cairo_set_source_rgba(cr, rgba(color, alpha))
end

local function text_width(text, size)
    return #tostring(text) * size * 0.61
end

local function draw_text(cr, x, y, text, size, color, alignment, bold, alpha)
    local value = tostring(text)
    local opacity = alpha or 1
    local width = text_width(value, size)
    if alignment == "center" then
        x = x - width / 2
    elseif alignment == "right" then
        x = x - width
    end
    cairo_select_font_face(
        cr,
        "DejaVu Sans Mono",
        CAIRO_FONT_SLANT_NORMAL,
        bold and CAIRO_FONT_WEIGHT_BOLD or CAIRO_FONT_WEIGHT_NORMAL
    )
    cairo_set_font_size(cr, size)
    set_source(cr, colors.dark, 0.82 * opacity)
    cairo_move_to(cr, x + 1, y + 1)
    cairo_show_text(cr, value)
    set_source(cr, color, opacity)
    cairo_move_to(cr, x, y)
    cairo_show_text(cr, value)
end

local function meter_level(value, reference)
    if value <= 0 or reference <= 0 then
        return 0
    end
    local scaled = math.ceil(value / reference * vertical_equalizer_levels)
    return math.max(1, math.min(vertical_equalizer_levels, scaled))
end

local function update_signal_state(state, raw_value)
    local value = math.max(0, raw_value or 0)
    if not state.initialized then
        state.now = value
        state.fast = value
        state.slow = value
        state.peak = value
        state.peak_hold = meter_peak_hold_updates
        state.initialized = true
        return
    end

    state.now = value
    state.fast = state.fast + meter_fast_alpha * (value - state.fast)
    state.slow = state.slow + meter_slow_alpha * (value - state.slow)
    if value >= state.peak then
        state.peak = value
        state.peak_hold = meter_peak_hold_updates
    elseif state.peak_hold > 0 then
        state.peak_hold = state.peak_hold - 1
    else
        state.peak = math.max(value, state.peak * meter_peak_decay)
    end
end

local function signal_maximum(state)
    return math.max(state.now, state.fast, state.slow, state.peak)
end

local function update_stationary_meter(meter, first_value, second_value)
    update_signal_state(meter.first, first_value)
    update_signal_state(meter.second, second_value)
    local current_maximum = math.max(signal_maximum(meter.first), signal_maximum(meter.second))
    if current_maximum >= meter.reference then
        meter.reference = math.max(1, current_maximum)
    else
        meter.reference = math.max(1, current_maximum, meter.reference * meter_reference_decay)
    end

    for group = 1, 2 do
        local state = group == 1 and meter.first or meter.second
        for mode_index, mode in ipairs(meter_modes) do
            local column = (group - 1) * vertical_equalizer_columns_per_group + mode_index
            meter.levels[column] = meter_level(state[mode], meter.reference)
        end
    end
end

function render.update(metrics)
    local epoch = metrics.updated_at_epoch or 0
    if epoch == last_epoch then
        return
    end
    update_stationary_meter(
        disk_meter,
        metrics.disk_read_bytes_per_second,
        metrics.disk_write_bytes_per_second
    )
    update_stationary_meter(
        network_meter,
        metrics.network_download_bytes_per_second,
        metrics.network_upload_bytes_per_second
    )
    last_epoch = epoch
end

local function clamp_percent(value)
    return math.max(0, math.min(100, value or 0))
end

local function bar(value, width)
    local filled = math.floor(clamp_percent(value) * width / 100 + 0.5)
    return "[" .. string.rep("#", filled) .. string.rep(".", width - filled) .. "]"
end

local ascii_needle_positions = 9
local ascii_needle_frames = {
    {top = "\\        ", middle = "  \\      "},
    {top = " \\       ", middle = "   \\     "},
    {top = "  \\      ", middle = "   \\     "},
    {top = "   \\     ", middle = "    \\    "},
    {top = "    |    ", middle = "    |    "},
    {top = "     /   ", middle = "    /    "},
    {top = "      /  ", middle = "     /   "},
    {top = "       / ", middle = "     /   "},
    {top = "        /", middle = "      /  "},
}

local function ascii_needle_frame(value, maximum)
    if value == nil then
        return {top = "         ", middle = "    ?    "}
    end
    local ratio = math.max(0, math.min(1, value / math.max(1, maximum)))
    local position = math.floor(ratio * (ascii_needle_positions - 1) + 0.5) + 1
    return ascii_needle_frames[position]
end

local function format_vu_value(value, unit)
    if value == nil then
        return "?"
    end
    return string.format("%.0f%s", value, unit)
end

local function draw_ascii_vu(cr, x, top_y, label, value, maximum, unit, color)
    local frame = ascii_needle_frame(value, maximum)
    draw_text(cr, x, top_y, label, 9, color, "center", true)
    draw_text(cr, x, top_y + 12, "0  50 100", 7, colors.gray, "center", false)
    draw_text(cr, x, top_y + 23, ".---|---.", 8, colors.white, "center", true)
    draw_text(cr, x, top_y + 35, frame.top, 9, color, "center", true)
    draw_text(cr, x, top_y + 46, frame.middle, 9, color, "center", true)
    draw_text(cr, x, top_y + 57, "    o    ", 9, colors.gray, "center", true)
    draw_text(cr, x, top_y + 72, format_vu_value(value, unit), 8, color, "center", true)
end

local function draw_vertical_equalizer(cr, x, top_y, meter, labels)
    for level = vertical_equalizer_levels, 1, -1 do
        local y = top_y + (vertical_equalizer_levels - level) * vertical_equalizer_row_step
        for column = 1, vertical_equalizer_columns do
            if (meter.levels[column] or 0) >= level then
                local color = column <= vertical_equalizer_columns_per_group and colors.cyan or colors.magenta
                draw_text(
                    cr,
                    x + (column - 1) * vertical_equalizer_column_step,
                    y,
                    "---",
                    10,
                    color,
                    "left",
                    true
                )
            end
        end
    end
    local baseline_y = top_y + vertical_equalizer_levels * vertical_equalizer_row_step
    draw_text(cr, x, baseline_y, vertical_equalizer_baseline, 10, colors.gray, "left", true)
    draw_text(cr, x, baseline_y + 16, labels, 12, colors.gray, "left", true)
end

local function spinner(animation_time)
    local frames = {"|", "/", "-", "\\"}
    return frames[math.floor(animation_time * 4) % #frames + 1]
end

local function temperature_color(value)
    if value == nil then
        return colors.gray
    elseif value >= 85 then
        return colors.red
    elseif value >= 75 then
        return colors.amber
    elseif value >= 65 then
        return colors.green
    end
    return colors.cyan
end

local function format_temperature(value)
    if value == nil then
        return "N/A"
    end
    return string.format("%.1fC", value)
end

local function format_rate(value)
    local bytes = value or 0
    if bytes >= 1048576 then
        return string.format("%.1f MB/s", bytes / 1048576)
    elseif bytes >= 1024 then
        return string.format("%.0f KB/s", bytes / 1024)
    end
    return string.format("%.0f B/s", bytes)
end

local function format_uptime(value)
    local total = math.max(0, math.floor(value or 0))
    local days = math.floor(total / 86400)
    local hours = math.floor((total % 86400) / 3600)
    local minutes = math.floor((total % 3600) / 60)
    if days > 0 then
        return string.format("%dd/%02dh", days, hours)
    end
    return string.format("%02dh/%02dm", hours, minutes)
end

local function value_or_na(value, format)
    if value == nil then
        return "N/A"
    end
    return string.format(format, value)
end

local function status_label(state)
    if state == "ok" then
        return "ACTIVE"
    elseif state == "degraded" or state == "partial" then
        return "DEGRADED"
    elseif state == "error" then
        return "ERROR"
    elseif state == "off" then
        return "OFF"
    end
    return "UNKNOWN"
end

local function status_color(state)
    if state == "ok" then
        return colors.green
    elseif state == "degraded" or state == "partial" then
        return colors.amber
    elseif state == "error" then
        return colors.red
    elseif state == "off" then
        return colors.gray
    end
    return colors.gray
end

local function status_marker(state, animation_time, phase)
    local pulse = math.floor(animation_time * 2 + phase) % 2 == 0
    if state == "ok" then
        return pulse and "*" or "+"
    elseif state == "degraded" or state == "partial" then
        return pulse and ":" or "*"
    elseif state == "error" then
        return pulse and "#" or "*"
    elseif state == "off" then
        return "."
    end
    return "_"
end

local function section_header(cr, title, code, metrics, animation_time)
    draw_text(cr, 20, 20, "[" .. code .. "] " .. title, 13, colors.cyan, "left", true)
    draw_text(cr, 340, 20, string.rep("-", 12), 9, colors.gray, "right", false)
    local live = metrics.cache_fresh and "LIVE" or "STALE"
    local color = metrics.cache_fresh and colors.green or colors.red
    draw_text(cr, 340, 36, "<" .. spinner(animation_time) .. " " .. live .. ">", 8, color, "right", true)
end

local function draw_system_pulse(cr, metrics, animation_time)
    section_header(cr, "SYSTEM PULSE", "01", metrics, animation_time)
    local date = os.date("*t")
    local date_text = string.format(
        "%s / %02d %s / %04d",
        polish_weekdays[date.wday],
        date.day,
        polish_months[date.month],
        date.year
    )
    draw_text(cr, 20, 62, os.date("%H:%M:%S"), 26, colors.white, "left", true)
    draw_text(cr, 20, 81, date_text, 9, colors.gray, "left", false)

    draw_text(cr, 20, 106, "CPU " .. bar(metrics.cpu_percent, 20), 10, colors.cyan, "left", true)
    draw_text(cr, 340, 106, string.format("%5.1f%%", metrics.cpu_percent or 0), 11, colors.white, "right", true)
    draw_text(cr, 20, 131, "RAM " .. bar(metrics.memory_percent, 20), 10, colors.green, "left", true)
    draw_text(cr, 340, 131, string.format("%5.1f%%", metrics.memory_percent or 0), 11, colors.white, "right", true)
    draw_ascii_vu(cr, 60, 144, "CPU", metrics.cpu_percent, 100, "%", colors.cyan)
    draw_ascii_vu(cr, 180, 144, "RAM", metrics.memory_percent, 100, "%", colors.green)
    draw_ascii_vu(
        cr,
        300,
        144,
        "NVM",
        metrics.temperature_nvme_c,
        100,
        "C",
        temperature_color(metrics.temperature_nvme_c)
    )
    local compact_status = string.format(
        "LOAD %.2f/%.2f/%.2f  CPU %s  GPU %s",
        metrics.load_1 or 0,
        metrics.load_5 or 0,
        metrics.load_15 or 0,
        format_temperature(metrics.temperature_cpu_c),
        format_temperature(metrics.temperature_gpu_c)
    )
    draw_text(cr, 20, 239, compact_status, 7, colors.white, "left", true)
end

local function draw_status_item(cr, x, y, label, state, animation_time, phase)
    local marker = status_marker(state, animation_time, phase)
    local color = status_color(state)
    draw_text(cr, x, y, "[" .. marker .. "] " .. label, 10, colors.white, "left", true)
    draw_text(cr, x, y + 15, "    " .. status_label(state), 8, color, "left", true)
end

local function draw_status_grid(cr, metrics, animation_time)
    section_header(cr, "STATUS GRID", "03", metrics, animation_time)
    draw_status_item(cr, 20, 67, "UFW", metrics.service_ufw, animation_time, 0)
    draw_status_item(cr, 190, 67, "FORTIVPN", metrics.service_fortivpn, animation_time, 1)
    draw_status_item(cr, 20, 119, "NUMBERPAD", metrics.service_numberpad, animation_time, 2)
    draw_status_item(cr, 190, 119, "NTFY", metrics.service_ntfy, animation_time, 3)
    draw_status_item(cr, 20, 171, "LOCAL MON", metrics.service_monitors, animation_time, 4)
    local updates = metrics.updates_status == "ok" and "ok" or "unknown"
    draw_status_item(cr, 190, 171, "UPDATES", updates, animation_time, 5)
    local battery = metrics.battery_percent == nil and "N/A" or string.format("%.0f%%", metrics.battery_percent)
    draw_text(cr, 20, 224, "POWER [" .. string.upper(metrics.power_source or "unknown") .. "]", 10, colors.amber, "left", true)
    draw_text(cr, 190, 224, "BATTERY [" .. battery .. "]", 10, colors.green, "left", true)
end

local function draw_activity(cr, metrics, animation_time)
    section_header(cr, "SYSTEM ACTIVITY", "02", metrics, animation_time)
    draw_text(cr, 20, 57, "DISK READ", 8, colors.cyan, "left", true)
    draw_text(cr, 20, 77, format_rate(metrics.disk_read_bytes_per_second), 16, colors.white, "left", true)
    draw_text(cr, 190, 57, "DISK WRITE", 8, colors.magenta, "left", true)
    draw_text(cr, 190, 77, format_rate(metrics.disk_write_bytes_per_second), 16, colors.white, "left", true)
    draw_text(cr, 20, 104, "PROCESSES", 8, colors.green, "left", true)
    draw_text(cr, 20, 126, string.format("%d", metrics.process_count or 0), 19, colors.white, "left", true)
    draw_text(cr, 190, 104, "UPTIME", 8, colors.amber, "left", true)
    draw_text(cr, 190, 126, format_uptime(metrics.uptime_seconds), 16, colors.white, "left", true)
    draw_text(cr, 20, 145, "TOP <" .. (metrics.top_process_name or "unknown") .. ">", 9, colors.gray, "left", true)
    draw_text(cr, 340, 145, string.format("%.1f%% EST", metrics.top_process_cpu_percent or 0), 9, colors.green, "right", true)
    draw_text(cr, 62, 160, "READ", 8, colors.cyan, "center", true)
    draw_text(cr, 236, 160, "WRITE", 8, colors.magenta, "center", true)
    draw_vertical_equalizer(
        cr,
        62,
        170,
        disk_meter,
        "N   F   S   P   N   F   S   P"
    )
end

local function draw_inline_status(cr, x, y, label, state, animation_time, phase)
    local marker = status_marker(state, animation_time, phase)
    draw_text(cr, x, y, "[" .. marker .. "]" .. label, 8, status_color(state), "left", true)
end

local function draw_network_services(cr, metrics, animation_time)
    section_header(cr, "NETWORK & SERVICES", "04", metrics, animation_time)
    draw_text(cr, 20, 61, "INTERNET <" .. status_label(metrics.network_internet_status) .. ">", 14, status_color(metrics.network_internet_status), "left", true)
    draw_text(cr, 230, 58, "PING " .. value_or_na(metrics.network_latency_ms, "%.0fms"), 9, colors.white, "left", true)
    draw_text(cr, 230, 76, "LOSS " .. value_or_na(metrics.network_packet_loss_percent, "%.0f%%"), 9, colors.white, "left", true)
    local route = status_label(metrics.network_route_status) .. "/" .. string.upper(metrics.network_connection_type or "unknown")
    draw_text(cr, 20, 91, "PUBLIC " .. (metrics.network_public_ip_masked or "N/A") .. " / ROUTE " .. route, 8, colors.gray, "left", false)
    draw_inline_status(cr, 20, 108, "DNS", metrics.network_dns_status, animation_time, 0)
    draw_inline_status(cr, 120, 108, "HTTPS", metrics.network_https_status, animation_time, 1)
    draw_inline_status(cr, 235, 108, "GATEWAY", metrics.network_gateway_status, animation_time, 2)
    draw_inline_status(cr, 20, 128, "VPN", metrics.service_fortivpn, animation_time, 3)
    draw_inline_status(cr, 120, 128, "UFW", metrics.service_ufw, animation_time, 4)
    draw_inline_status(cr, 220, 128, "PAD", metrics.service_numberpad, animation_time, 5)
    draw_inline_status(cr, 20, 148, "NTFY", metrics.service_ntfy, animation_time, 6)
    draw_inline_status(cr, 160, 148, "MONITORS", metrics.service_monitors, animation_time, 7)
    draw_text(cr, 20, 168, "RX " .. format_rate(metrics.network_download_bytes_per_second), 9, colors.cyan, "left", true)
    draw_text(cr, 190, 168, "TX " .. format_rate(metrics.network_upload_bytes_per_second), 9, colors.magenta, "left", true)
    draw_text(cr, 62, 182, "RX", 8, colors.cyan, "center", true)
    draw_text(cr, 236, 182, "TX", 8, colors.magenta, "center", true)
    draw_vertical_equalizer(
        cr,
        62,
        188,
        network_meter,
        "N   F   S   P   N   F   S   P"
    )
end

local function draw_at(cr, x, y, draw_function, metrics, animation_time)
    cairo_save(cr)
    cairo_translate(cr, x, y)
    draw_function(cr, metrics, animation_time)
    cairo_restore(cr)
end

local function draw_vertical_separator(cr)
    for y = 15, 510, 15 do
        draw_text(cr, 370, y, "|", 9, colors.gray, "center", false, 0.65)
    end
end

function render.draw_dashboard(cr, metrics, animation_time)
    draw_at(cr, layout.left_x, layout.top_y, draw_system_pulse, metrics, animation_time)
    draw_at(cr, layout.left_x, layout.bottom_y, draw_status_grid, metrics, animation_time)
    draw_at(cr, layout.right_x, layout.top_y, draw_activity, metrics, animation_time)
    draw_at(cr, layout.right_x, layout.bottom_y, draw_network_services, metrics, animation_time)
    draw_vertical_separator(cr)
    draw_text(cr, 20, 246, string.rep("-", 45), 8, colors.gray, "left", false)
    draw_text(cr, 400, 246, string.rep("-", 45), 8, colors.gray, "left", false)
end

local function ticker_messages(metrics)
    return {
        "CPU TEMP " .. format_temperature(metrics.temperature_cpu_c) .. " / GPU " .. format_temperature(metrics.temperature_gpu_c),
        "UPTIME " .. format_uptime(metrics.uptime_seconds) .. " / LOAD " .. string.format("%.2f", metrics.load_1 or 0),
        "DISK R " .. format_rate(metrics.disk_read_bytes_per_second) .. " / W " .. format_rate(metrics.disk_write_bytes_per_second),
        "INTERNET " .. status_label(metrics.network_internet_status) .. " / PING " .. value_or_na(metrics.network_latency_ms, "%.0fms"),
        "DNS " .. status_label(metrics.network_dns_status) .. " / HTTPS " .. status_label(metrics.network_https_status),
        "NET RX " .. format_rate(metrics.network_download_bytes_per_second) .. " / TX " .. format_rate(metrics.network_upload_bytes_per_second),
        "UFW " .. status_label(metrics.service_ufw) .. " / VPN " .. status_label(metrics.service_fortivpn) .. " / NTFY " .. status_label(metrics.service_ntfy),
    }
end

function render.draw_ticker(cr, metrics, alpha, animation_time)
    local messages = ticker_messages(metrics)
    if ticker_text == "" then
        ticker_text = messages[ticker_index]
    end
    local delta_time = 0
    if last_ticker_time ~= nil then
        delta_time = math.max(0, math.min(0.5, animation_time - last_ticker_time))
    end
    last_ticker_time = animation_time
    ticker_x = ticker_x - 14 * delta_time
    if ticker_x + text_width(ticker_text, 9) < 20 then
        ticker_index = ticker_index % #messages + 1
        ticker_text = messages[ticker_index]
        ticker_x = layout.width
    end

    draw_text(cr, 20, layout.ticker_y, string.rep("=", 147), 8, colors.green, "left", false, 0.8 * alpha)
    cairo_save(cr)
    cairo_rectangle(cr, 20, layout.ticker_y + 5, 720, 28)
    cairo_clip(cr)
    draw_text(cr, ticker_x, layout.ticker_baseline_y, ">> " .. ticker_text .. " <<", 9, colors.green, "left", true, alpha)
    cairo_restore(cr)
end

return render
