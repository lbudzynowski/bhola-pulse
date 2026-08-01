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
    white = 0xffffff,
    text = 0xe2e8f0,
    muted = 0x94a3b8,
    shadow = 0x020617,
    grid = 0x475569,
    cyan = 0x22d3ee,
    cyan_light = 0x67e8f9,
    purple = 0xa78bfa,
    purple_light = 0xc4b5fd,
    green = 0x34d399,
    green_light = 0x6ee7b7,
    yellow = 0xfacc15,
    amber = 0xfbbf24,
    orange = 0xfb923c,
    red = 0xef4444,
    gray = 0x64748b,
}

local cpu_history = {}
local read_history = {}
local write_history = {}
local download_history = {}
local upload_history = {}
local history_size = 48
local last_epoch = -1
local ticker_index = 1
local ticker_x = layout.width
local ticker_text = ""
local last_ticker_time = nil

local polish_weekdays = {
    "niedziela",
    "poniedziałek",
    "wtorek",
    "środa",
    "czwartek",
    "piątek",
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
    "września",
    "października",
    "listopada",
    "grudnia",
}

local function rgba(hex, alpha)
    local red = math.floor(hex / 0x10000) % 0x100
    local green = math.floor(hex / 0x100) % 0x100
    local blue = hex % 0x100
    return red / 255, green / 255, blue / 255, alpha
end

local function set_source(cr, hex, alpha)
    cairo_set_source_rgba(cr, rgba(hex, alpha))
end

local function text_width(text, size)
    local value = tostring(text)
    local length = #value
    if utf8 ~= nil and utf8.len ~= nil then
        length = utf8.len(value) or length
    end
    return length * size * 0.6
end

local function draw_text(cr, x, y, text, size, color, alpha, alignment, bold)
    local value = tostring(text)
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
    set_source(cr, colors.shadow, 0.68 * alpha)
    cairo_move_to(cr, x + 1.5, y + 1.5)
    cairo_show_text(cr, value)
    set_source(cr, color, alpha)
    cairo_move_to(cr, x, y)
    cairo_show_text(cr, value)
end

local function draw_line(cr, x1, y1, x2, y2, width, color, alpha)
    cairo_set_line_width(cr, width + 2)
    set_source(cr, colors.shadow, 0.48 * alpha)
    cairo_move_to(cr, x1, y1 + 1)
    cairo_line_to(cr, x2, y2 + 1)
    cairo_stroke(cr)
    cairo_set_line_width(cr, width)
    set_source(cr, color, alpha)
    cairo_move_to(cr, x1, y1)
    cairo_line_to(cr, x2, y2)
    cairo_stroke(cr)
end

local function push(history, value)
    table.insert(history, value or 0)
    while #history > history_size do
        table.remove(history, 1)
    end
end

function render.update(metrics)
    local epoch = metrics.updated_at_epoch or 0
    if epoch ~= last_epoch then
        push(cpu_history, metrics.cpu_percent)
        push(read_history, metrics.disk_read_bytes_per_second)
        push(write_history, metrics.disk_write_bytes_per_second)
        push(download_history, metrics.network_download_bytes_per_second)
        push(upload_history, metrics.network_upload_bytes_per_second)
        last_epoch = epoch
    end
end

local function format_temperature(value)
    if value == nil then
        return "N/A"
    end
    return string.format("%.1f°C", value)
end

local function interpolate_color(first, second, ratio)
    local function channel(hex, shift)
        return math.floor(hex / shift) % 0x100
    end
    local red = channel(first, 0x10000) + (channel(second, 0x10000) - channel(first, 0x10000)) * ratio
    local green = channel(first, 0x100) + (channel(second, 0x100) - channel(first, 0x100)) * ratio
    local blue = channel(first, 1) + (channel(second, 1) - channel(first, 1)) * ratio
    return math.floor(red + 0.5) * 0x10000 + math.floor(green + 0.5) * 0x100 + math.floor(blue + 0.5)
end

local function temperature_color(value)
    if value == nil then
        return colors.gray
    end
    local stops = {
        {45, colors.cyan_light},
        {65, colors.green},
        {75, colors.yellow},
        {85, colors.orange},
        {95, colors.red},
    }
    if value <= stops[1][1] then
        return stops[1][2]
    end
    for index = 2, #stops do
        if value <= stops[index][1] then
            local previous = stops[index - 1]
            local current = stops[index]
            local ratio = (value - previous[1]) / (current[1] - previous[1])
            return interpolate_color(previous[2], current[2], ratio)
        end
    end
    return colors.red
end

local function alarm_alpha(value, animation_time, alpha)
    if value ~= nil and value >= 85 then
        return alpha * (0.82 + 0.18 * (0.5 + 0.5 * math.sin(animation_time * 0.7)))
    end
    return alpha
end

local function draw_ring(cr, x, y, radius, value, alpha)
    cairo_set_line_width(cr, 11)
    set_source(cr, colors.shadow, 0.5 * alpha)
    cairo_arc(cr, x, y, radius, 0, 2 * math.pi)
    cairo_stroke(cr)
    cairo_set_line_width(cr, 8)
    set_source(cr, colors.grid, 0.58 * alpha)
    cairo_arc(cr, x, y, radius, 0, 2 * math.pi)
    cairo_stroke(cr)
    cairo_set_line_width(cr, 8)
    set_source(cr, colors.cyan, alpha)
    local start_angle = -math.pi / 2
    local end_angle = start_angle + 2 * math.pi * math.max(0, math.min(100, value or 0)) / 100
    cairo_arc(cr, x, y, radius, start_angle, end_angle)
    cairo_stroke(cr)
end

local function graph_max(history_a, history_b)
    local maximum = 1
    for _, value in ipairs(history_a) do
        maximum = math.max(maximum, value)
    end
    if history_b ~= nil then
        for _, value in ipairs(history_b) do
            maximum = math.max(maximum, value)
        end
    end
    return maximum
end

local function draw_history(cr, history, x, y, width, height, maximum, color, alpha)
    if #history < 2 then
        return
    end
    for pass = 1, 2 do
        cairo_set_line_width(cr, pass == 1 and 5 or 2.5)
        set_source(cr, pass == 1 and colors.shadow or color, pass == 1 and 0.55 * alpha or alpha)
        for index, value in ipairs(history) do
            local point_x = x + width * (index - 1) / (history_size - 1)
            local point_y = y + height * (1 - math.min(maximum, math.max(0, value)) / maximum)
            if index == 1 then
                cairo_move_to(cr, point_x, point_y)
            else
                cairo_line_to(cr, point_x, point_y)
            end
        end
        cairo_stroke(cr)
    end
end

local function draw_graph_grid(cr, x, y, width, height, alpha)
    for row = 0, 2 do
        local line_y = y + height * row / 2
        draw_line(cr, x, line_y, x + width, line_y, 1, colors.grid, 0.55 * alpha)
    end
end

local function format_rate(bytes)
    local value = bytes or 0
    if value >= 1048576 then
        return string.format("%.1f MB/s", value / 1048576)
    elseif value >= 1024 then
        return string.format("%.0f KB/s", value / 1024)
    end
    return string.format("%.0f B/s", value)
end

local function format_uptime(seconds)
    local total = math.max(0, math.floor(seconds or 0))
    local days = math.floor(total / 86400)
    local hours = math.floor((total % 86400) / 3600)
    local minutes = math.floor((total % 3600) / 60)
    if days > 0 then
        return string.format("%dd %02dh", days, hours)
    end
    return string.format("%02dh %02dm", hours, minutes)
end

local function section_header(cr, y, title, subtitle, alpha, metrics)
    draw_text(cr, 24, y + 21, title, 14, colors.cyan_light, alpha, "left", true)
    draw_text(cr, 336, y + 21, subtitle, 9, colors.muted, alpha, "right", false)
    local live_color = metrics.cache_fresh and colors.green or colors.red
    draw_text(cr, 336, y + 36, metrics.cache_fresh and "● LIVE" or "● STALE", 8, live_color, alpha, "right", true)
end

local function draw_system_pulse(cr, origin_y, metrics, alpha, animation_time)
    section_header(cr, origin_y, "SYSTEM PULSE", "01 / CORE", alpha, metrics)
    local clock = os.date("%H:%M:%S")
    local date = os.date("*t")
    local polish_date = string.format(
        "%s · %02d %s",
        polish_weekdays[date.wday],
        date.day,
        polish_months[date.month]
    )
    draw_text(cr, 180, origin_y + 57, clock, 28, colors.white, alpha, "center", true)
    draw_text(cr, 180, origin_y + 76, polish_date, 10, colors.text, alpha, "center", false)

    draw_ring(cr, 60, origin_y + 118, 29, metrics.cpu_percent, alpha)
    draw_text(cr, 60, origin_y + 116, string.format("%.0f", metrics.cpu_percent or 0), 16, colors.white, alpha, "center", true)
    draw_text(cr, 60, origin_y + 131, "% CPU", 8, colors.cyan_light, alpha, "center", true)

    local graph_x, graph_y, graph_width, graph_height = 103, origin_y + 91, 229, 56
    draw_graph_grid(cr, graph_x, graph_y, graph_width, graph_height, alpha)
    draw_history(cr, cpu_history, graph_x, graph_y, graph_width, graph_height, 100, colors.purple, alpha)
    local scanner_period = 24
    local scanner_x = graph_x + (animation_time % scanner_period) * graph_width / scanner_period
    set_source(cr, colors.shadow, 0.62 * alpha)
    cairo_arc(cr, scanner_x, origin_y + 119, 5, 0, 2 * math.pi)
    cairo_fill(cr)
    set_source(cr, colors.green, alpha)
    cairo_arc(cr, scanner_x, origin_y + 119, 3, 0, 2 * math.pi)
    cairo_fill(cr)
    draw_line(cr, graph_x, origin_y + 154, graph_x + graph_width * (metrics.cpu_percent or 0) / 100, origin_y + 154, 3, colors.cyan, alpha)

    draw_text(cr, 28, origin_y + 171, "CPU", 9, colors.cyan_light, alpha, "left", true)
    draw_text(cr, 28, origin_y + 188, string.format("%.1f%%", metrics.cpu_percent or 0), 13, colors.white, alpha, "left", true)
    draw_text(cr, 124, origin_y + 171, "RAM", 9, colors.green_light, alpha, "left", true)
    draw_text(cr, 124, origin_y + 188, string.format("%.1f%%", metrics.memory_percent or 0), 13, colors.white, alpha, "left", true)
    draw_text(cr, 220, origin_y + 171, "LOAD 1/5/15", 9, colors.purple_light, alpha, "left", true)
    draw_text(
        cr,
        220,
        origin_y + 188,
        string.format("%.1f %.1f %.1f", metrics.load_1 or 0, metrics.load_5 or 0, metrics.load_15 or 0),
        10,
        colors.white,
        alpha,
        "left",
        true
    )

    local cpu_alpha = alarm_alpha(metrics.temperature_cpu_c, animation_time, alpha)
    draw_text(cr, 28, origin_y + 207, "CPU TEMP", 8, colors.muted, alpha, "left", true)
    draw_text(cr, 28, origin_y + 225, format_temperature(metrics.temperature_cpu_c), 11, temperature_color(metrics.temperature_cpu_c), cpu_alpha, "left", true)
    draw_text(cr, 142, origin_y + 207, "GPU TEMP", 8, colors.muted, alpha, "left", true)
    draw_text(cr, 142, origin_y + 225, format_temperature(metrics.temperature_gpu_c), 11, temperature_color(metrics.temperature_gpu_c), alarm_alpha(metrics.temperature_gpu_c, animation_time, alpha), "left", true)
    draw_text(cr, 252, origin_y + 207, "NVME TEMP", 8, colors.muted, alpha, "left", true)
    draw_text(cr, 252, origin_y + 225, format_temperature(metrics.temperature_nvme_c), 11, temperature_color(metrics.temperature_nvme_c), alarm_alpha(metrics.temperature_nvme_c, animation_time, alpha), "left", true)
end

local function draw_activity(cr, origin_y, metrics, alpha, animation_time)
    section_header(cr, origin_y, "SYSTEM ACTIVITY", "02 / FLOW", alpha, metrics)
    draw_text(cr, 28, origin_y + 50, "DISK READ", 9, colors.cyan_light, alpha, "left", true)
    draw_text(cr, 28, origin_y + 73, format_rate(metrics.disk_read_bytes_per_second), 17, colors.white, alpha, "left", true)
    draw_text(cr, 190, origin_y + 50, "DISK WRITE", 9, colors.purple_light, alpha, "left", true)
    draw_text(cr, 190, origin_y + 73, format_rate(metrics.disk_write_bytes_per_second), 17, colors.white, alpha, "left", true)
    draw_text(cr, 28, origin_y + 97, "PROCESSES", 9, colors.green_light, alpha, "left", true)
    draw_text(cr, 28, origin_y + 121, string.format("%d", metrics.process_count or 0), 21, colors.white, alpha, "left", true)
    draw_text(cr, 190, origin_y + 97, "UPTIME", 9, colors.amber, alpha, "left", true)
    draw_text(cr, 190, origin_y + 121, format_uptime(metrics.uptime_seconds), 17, colors.white, alpha, "left", true)
    draw_text(cr, 28, origin_y + 143, "TOP ACTIVE · EST.", 8, colors.muted, alpha, "left", true)
    draw_text(cr, 28, origin_y + 161, metrics.top_process_name or "unknown", 12, colors.text, alpha, "left", true)
    draw_text(cr, 332, origin_y + 161, string.format("%.1f%%", metrics.top_process_cpu_percent or 0), 12, colors.green_light, alpha, "right", true)

    local x, y, width, height = 28, origin_y + 174, 304, 50
    draw_graph_grid(cr, x, y, width, height, alpha)
    local maximum = graph_max(read_history, write_history)
    draw_history(cr, read_history, x, y, width, height, maximum, colors.cyan, alpha)
    draw_history(cr, write_history, x, y, width, height, maximum, colors.purple, alpha)
    local radar_period = 24
    local radar_x = x + (animation_time % radar_period) * width / radar_period
    draw_line(cr, radar_x, y, radar_x, y + height, 1, colors.green, 0.75 * alpha)
end

local function status_color(state)
    if state == "ok" then
        return colors.green
    elseif state == "degraded" or state == "partial" then
        return colors.yellow
    elseif state == "error" then
        return colors.red
    end
    return colors.gray
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

local function draw_status(cr, x, y, label, state, alpha, animation_time)
    local color = status_color(state)
    local pulse = 0.5 + 0.5 * math.sin(animation_time * 0.56 + x * 0.01 + y * 0.02)
    local radius = 5 + 0.7 * pulse
    set_source(cr, colors.shadow, 0.65 * alpha)
    cairo_arc(cr, x + 1, y + 1, radius + 1.5, 0, 2 * math.pi)
    cairo_fill(cr)
    set_source(cr, color, alpha * (0.72 + 0.28 * pulse))
    cairo_arc(cr, x, y, radius, 0, 2 * math.pi)
    cairo_fill(cr)
    draw_text(cr, x + 15, y - 1, label, 10, colors.text, alpha, "left", true)
    draw_text(cr, x + 15, y + 13, status_label(state), 8, color, alpha, "left", true)
end

local function draw_status_grid(cr, origin_y, metrics, alpha, animation_time)
    section_header(cr, origin_y, "STATUS GRID", "03 / LOCAL", alpha, metrics)
    draw_status(cr, 34, origin_y + 62, "UFW", metrics.service_ufw, alpha, animation_time)
    draw_status(cr, 196, origin_y + 62, "FORTIVPN", metrics.service_fortivpn, alpha, animation_time)
    draw_status(cr, 34, origin_y + 116, "NUMBERPAD", metrics.service_numberpad, alpha, animation_time)
    draw_status(cr, 196, origin_y + 116, "NTFY", metrics.service_ntfy, alpha, animation_time)
    draw_status(cr, 34, origin_y + 170, "LOCAL MONITORS", metrics.service_monitors, alpha, animation_time)

    local update_state = metrics.updates_status == "ok" and "ok" or "unknown"
    draw_status(cr, 196, origin_y + 170, "UPDATES", update_state, alpha, animation_time)
    local power_color = metrics.power_source == "unknown" and colors.gray or colors.amber
    draw_text(cr, 28, origin_y + 207, "POWER", 8, colors.muted, alpha, "left", true)
    draw_text(cr, 28, origin_y + 226, string.upper(metrics.power_source or "unknown"), 13, power_color, alpha, "left", true)
    draw_text(cr, 190, origin_y + 207, "BATTERY", 8, colors.muted, alpha, "left", true)
    local battery = metrics.battery_percent == nil and "N/A" or string.format("%.0f%%", metrics.battery_percent)
    draw_text(cr, 190, origin_y + 226, battery, 13, colors.text, alpha, "left", true)
end

local function value_or_na(value, format)
    if value == nil then
        return "N/A"
    end
    return string.format(format, value)
end

local function draw_compact_status(cr, x, y, label, state, alpha, animation_time)
    local color = status_color(state)
    local pulse = 0.5 + 0.5 * math.sin(animation_time * 0.56 + x * 0.015 + y * 0.02)
    set_source(cr, colors.shadow, 0.62 * alpha)
    cairo_arc(cr, x + 1, y + 1, 5.5, 0, 2 * math.pi)
    cairo_fill(cr)
    set_source(cr, color, alpha * (0.74 + 0.26 * pulse))
    cairo_arc(cr, x, y, 3.7 + 0.5 * pulse, 0, 2 * math.pi)
    cairo_fill(cr)
    draw_text(cr, x + 10, y - 1, label, 8, colors.text, alpha, "left", true)
    draw_text(cr, x + 10, y + 11, status_label(state), 7, color, alpha, "left", true)
end

local function draw_network_services(cr, origin_y, metrics, alpha, animation_time)
    section_header(cr, origin_y, "NETWORK & SERVICES", "04 / LINK", alpha, metrics)

    local internet_color = status_color(metrics.network_internet_status)
    draw_text(cr, 28, origin_y + 50, "INTERNET", 9, colors.cyan_light, alpha, "left", true)
    draw_text(cr, 28, origin_y + 75, status_label(metrics.network_internet_status), 19, internet_color, alpha, "left", true)
    draw_text(cr, 214, origin_y + 50, "PING", 8, colors.muted, alpha, "left", true)
    draw_text(cr, 214, origin_y + 72, value_or_na(metrics.network_latency_ms, "%.0f ms"), 12, colors.white, alpha, "left", true)
    draw_text(cr, 290, origin_y + 50, "LOSS", 8, colors.muted, alpha, "left", true)
    draw_text(cr, 290, origin_y + 72, value_or_na(metrics.network_packet_loss_percent, "%.0f%%"), 12, colors.white, alpha, "left", true)

    local route_summary = status_label(metrics.network_route_status) .. "/" .. string.upper(metrics.network_connection_type or "unknown")
    draw_text(cr, 28, origin_y + 95, "PUBLIC IP · " .. (metrics.network_public_ip_masked or "N/A") .. " · ROUTE " .. route_summary, 8, colors.muted, alpha, "left", true)
    draw_compact_status(cr, 34, origin_y + 116, "DNS", metrics.network_dns_status, alpha, animation_time)
    draw_compact_status(cr, 136, origin_y + 116, "HTTPS", metrics.network_https_status, alpha, animation_time)
    draw_compact_status(cr, 244, origin_y + 116, "GATEWAY", metrics.network_gateway_status, alpha, animation_time)

    draw_text(cr, 28, origin_y + 147, "DOWNLOAD", 8, colors.cyan_light, alpha, "left", true)
    draw_text(cr, 28, origin_y + 168, format_rate(metrics.network_download_bytes_per_second), 13, colors.white, alpha, "left", true)
    draw_text(cr, 190, origin_y + 147, "UPLOAD", 8, colors.purple_light, alpha, "left", true)
    draw_text(cr, 190, origin_y + 168, format_rate(metrics.network_upload_bytes_per_second), 13, colors.white, alpha, "left", true)

    local x, y, width, height = 28, origin_y + 180, 304, 43
    draw_graph_grid(cr, x, y, width, height, alpha)
    local maximum = graph_max(download_history, upload_history)
    draw_history(cr, download_history, x, y, width, height, maximum, colors.cyan, alpha)
    draw_history(cr, upload_history, x, y, width, height, maximum, colors.purple, alpha)

    draw_compact_status(cr, 34, origin_y + 239, "VPN", metrics.service_fortivpn, alpha, animation_time)
    draw_compact_status(cr, 136, origin_y + 239, "UFW", metrics.service_ufw, alpha, animation_time)
    draw_compact_status(cr, 238, origin_y + 239, "PAD", metrics.service_numberpad, alpha, animation_time)
    draw_compact_status(cr, 34, origin_y + 263, "NTFY", metrics.service_ntfy, alpha, animation_time)
    draw_compact_status(cr, 172, origin_y + 263, "MONITORS", metrics.service_monitors, alpha, animation_time)
end

local function draw_at(cr, x, y, draw_function, metrics, animation_time)
    cairo_save(cr)
    cairo_translate(cr, x, y)
    draw_function(cr, 0, metrics, 1, animation_time)
    cairo_restore(cr)
end

function render.draw_dashboard(cr, metrics, animation_time)
    draw_at(cr, layout.left_x, layout.top_y, draw_system_pulse, metrics, animation_time)
    draw_at(cr, layout.left_x, layout.bottom_y, draw_status_grid, metrics, animation_time)
    draw_at(cr, layout.right_x, layout.top_y, draw_activity, metrics, animation_time)
    draw_at(cr, layout.right_x, layout.bottom_y, draw_network_services, metrics, animation_time)
    draw_line(cr, 370, 12, 370, 516, 1, colors.grid, 0.45)
    draw_line(cr, 20, 240, 350, 240, 1, colors.grid, 0.5)
    draw_line(cr, 400, 240, 740, 240, 1, colors.grid, 0.5)
end

local function ticker_messages(metrics)
    local service_summary = string.format(
        "UFW %s · NUMBERPAD %s · NTFY %s",
        status_label(metrics.service_ufw),
        status_label(metrics.service_numberpad),
        status_label(metrics.service_ntfy)
    )
    local network_summary = string.format(
        "INTERNET %s · PING %s · LOSS %s",
        status_label(metrics.network_internet_status),
        value_or_na(metrics.network_latency_ms, "%.0f ms"),
        value_or_na(metrics.network_packet_loss_percent, "%.0f%%")
    )
    return {
        "CPU TEMP " .. format_temperature(metrics.temperature_cpu_c) .. " · GPU " .. format_temperature(metrics.temperature_gpu_c),
        "UPTIME " .. format_uptime(metrics.uptime_seconds) .. " · LOAD " .. string.format("%.2f", metrics.load_1 or 0),
        "DISK R " .. format_rate(metrics.disk_read_bytes_per_second) .. " · W " .. format_rate(metrics.disk_write_bytes_per_second),
        service_summary,
        network_summary,
        "ROUTE " .. status_label(metrics.network_route_status) .. " · GATEWAY " .. status_label(metrics.network_gateway_status),
        "DNS " .. status_label(metrics.network_dns_status) .. " · HTTPS " .. status_label(metrics.network_https_status) .. " · VPN " .. status_label(metrics.service_fortivpn),
        "NET ↓ " .. format_rate(metrics.network_download_bytes_per_second) .. " · ↑ " .. format_rate(metrics.network_upload_bytes_per_second),
        "POWER " .. string.upper(metrics.power_source or "unknown") .. " · BATTERY " .. (metrics.battery_percent == nil and "N/A" or string.format("%.0f%%", metrics.battery_percent)),
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
    ticker_x = ticker_x - 9 * delta_time
    if ticker_x + text_width(ticker_text, 9) < 20 then
        ticker_index = ticker_index % #messages + 1
        ticker_text = messages[ticker_index]
        ticker_x = layout.width
    end

    draw_line(cr, 20, layout.ticker_y, 740, layout.ticker_y, 1, colors.grid, 0.55 * alpha)
    cairo_save(cr)
    cairo_rectangle(cr, 20, layout.ticker_y + 6, 720, 24)
    cairo_clip(cr)
    draw_text(cr, ticker_x, layout.ticker_baseline_y, ticker_text, 9, colors.text, alpha, "left", true)
    cairo_restore(cr)
end

return render
