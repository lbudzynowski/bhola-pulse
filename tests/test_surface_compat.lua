-- lua5.3 tests/test_surface_compat.lua; no Conky display required.
package.path = "./?.lua;./?/init.lua;" .. package.path
local surface = require("conky.bhola_surface")
local native = {id = "native"}
local xlib = {id = "xlib"}
local calls = 0
local window = {display = 1, drawable = 2, visual = 3, width = 950, height = 713}

-- New 1.23+ API wins and is borrowed, even if an Xlib constructor exists.
cairo_xlib_surface_create = function() error("should not use xlib") end
local got, owned, err = surface.acquire(window, function() return native end)
assert(got == native and owned == false and err == nil)

-- Temporary lack of native output does not cause an unsafe Xlib fallback.
got, owned, err = surface.acquire(window, function() return nil end)
assert(got == nil and owned == false and err == nil)

-- On Conky 1.22.x a separate module registers the legacy constructor.
cairo_xlib_surface_create = nil
package.preload["cairo_xlib"] = function()
    cairo_xlib_surface_create = function(d, dr, v, w, h)
        assert(d == 1 and dr == 2 and v == 3 and w == 950 and h == 713)
        calls = calls + 1
        return xlib
    end
    return true
end
package.loaded["cairo_xlib"] = nil
got, owned, err = surface.acquire(window, nil)
assert(got == xlib and owned == true and err == nil and calls == 1)

-- Subsequent frames use the already loaded constructor.
got, owned, err = surface.acquire(window, nil)
assert(got == xlib and owned == true and err == nil and calls == 2)

-- Do not hand partial X11 window state to a native C binding.
got, owned, err = surface.acquire({display = 1, width = 950, height = 713}, nil)
assert(got == nil and owned == false and err ~= nil and calls == 2)

-- Without a viable module, return a diagnostic and do not throw every frame.
package.loaded["conky.bhola_surface"] = nil
surface = require("conky.bhola_surface")
package.preload["cairo_xlib"] = function() error("missing binding") end
package.loaded["cairo_xlib"] = nil
cairo_xlib_surface_create = nil
got, owned, err = surface.acquire(window, nil)
assert(got == nil and owned == false and err:find("cairo_xlib"))

print("Conky Cairo surface compatibility: 6 tests passed")
