local data = {}

local defaults = {
    provider_status = "unknown",
    updated_at_epoch = 0,
    cpu_percent = 0,
    memory_percent = 0,
    load_1 = 0,
    load_5 = 0,
    load_15 = 0,
    uptime_seconds = 0,
    temperature_cpu_c = nil,
    temperature_gpu_c = nil,
    temperature_nvme_c = nil,
    disk_read_bytes_per_second = 0,
    disk_write_bytes_per_second = 0,
    process_count = 0,
    top_process_name = "unknown",
    top_process_cpu_percent = 0,
    power_source = "unknown",
    battery_percent = nil,
    battery_state = "unknown",
    service_ufw = "unknown",
    service_fortivpn = "unknown",
    service_numberpad = "unknown",
    service_ntfy = "unknown",
    service_monitors = "unknown",
    network_download_bytes_per_second = 0,
    network_upload_bytes_per_second = 0,
    network_route_status = "unknown",
    network_connection_type = "unknown",
    network_gateway_status = "unknown",
    network_internet_status = "unknown",
    network_latency_ms = nil,
    network_packet_loss_percent = nil,
    network_dns_status = "unknown",
    network_dns_latency_ms = nil,
    network_https_status = "unknown",
    network_public_ip_status = "unknown",
    network_public_ip_masked = "N/A",
    updates_count = nil,
    updates_status = "unknown",
}

local numeric_keys = {
    "updated_at_epoch",
    "cpu_percent",
    "memory_percent",
    "load_1",
    "load_5",
    "load_15",
    "uptime_seconds",
    "temperature_cpu_c",
    "temperature_gpu_c",
    "temperature_nvme_c",
    "disk_read_bytes_per_second",
    "disk_write_bytes_per_second",
    "process_count",
    "top_process_cpu_percent",
    "battery_percent",
    "network_download_bytes_per_second",
    "network_upload_bytes_per_second",
    "network_latency_ms",
    "network_packet_loss_percent",
    "network_dns_latency_ms",
    "updates_count",
}

local string_keys = {
    "provider_status",
    "top_process_name",
    "power_source",
    "battery_state",
    "service_ufw",
    "service_fortivpn",
    "service_numberpad",
    "service_ntfy",
    "service_monitors",
    "network_route_status",
    "network_connection_type",
    "network_gateway_status",
    "network_internet_status",
    "network_dns_status",
    "network_https_status",
    "network_public_ip_status",
    "network_public_ip_masked",
    "updates_status",
}

local last_valid = nil
local read_counter = 0

local function clone_defaults()
    local result = {}
    for key, value in pairs(defaults) do
        result[key] = value
    end
    return result
end

local function read_file(path)
    local handle = io.open(path, "r")
    if handle == nil then
        return nil
    end
    local content = handle:read("*a")
    handle:close()
    return content
end

local function number_value(content, key)
    local raw = content:match('"' .. key .. '"%s*:%s*([^,%}%s]+)')
    if raw == nil or raw == "null" then
        return nil
    end
    return tonumber(raw)
end

local function string_value(content, key)
    return content:match('"' .. key .. '"%s*:%s*"([^"]*)"')
end

function data.read(path)
    read_counter = read_counter + 1
    if last_valid == nil or read_counter % 5 == 1 then
        local content = read_file(path)
        if content ~= nil and number_value(content, "schema_version") == 3 then
            local parsed = clone_defaults()
            for _, key in ipairs(numeric_keys) do
                parsed[key] = number_value(content, key)
            end
            for _, key in ipairs(string_keys) do
                parsed[key] = string_value(content, key) or defaults[key]
            end
            last_valid = parsed
        end
    end

    local result = last_valid or clone_defaults()
    result.cache_age_seconds = math.max(0, os.time() - (result.updated_at_epoch or 0))
    result.cache_fresh = result.updated_at_epoch > 0 and result.cache_age_seconds <= 3
    return result
end

return data
