-- Conky 1.22.x exports Xlib Cairo constructors in a separate Lua module.
-- Conky 1.23+ offers an output-agnostic surface owned by Conky.
local M = {}
local tried_xlib = false

local function ensure_xlib()
    if type(cairo_xlib_surface_create) == "function" then
        return true
    end
    if not tried_xlib then
        tried_xlib = true
        pcall(require, "cairo_xlib")
    end
    return type(cairo_xlib_surface_create) == "function"
end

function M.acquire(window, native_surface)
    if type(native_surface) == "function" then
        -- Borrowed from Conky; valid only during the current draw cycle.
        return native_surface(), false, nil
    end
    if not ensure_xlib() then
        return nil, false,
            "Cairo Xlib unavailable: install Conky with cairo_xlib Lua bindings " ..
            "or use Conky 1.23+ with conky_surface()"
    end
    if window == nil or window.display == nil or window.drawable == nil or
        window.visual == nil or type(window.width) ~= "number" or
        type(window.height) ~= "number" or window.width <= 0 or window.height <= 0 then
        return nil, false, "X11 drawing window is not ready"
    end
    return cairo_xlib_surface_create(
        window.display, window.drawable, window.visual, window.width, window.height
    ), true, nil
end

return M
