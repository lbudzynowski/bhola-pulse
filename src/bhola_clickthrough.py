"""Apply and verify an empty XShape input region for the Conky window."""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import os
import time


Window = ctypes.c_ulong


class XRectangle(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_short),
        ("y", ctypes.c_short),
        ("width", ctypes.c_ushort),
        ("height", ctypes.c_ushort),
    ]


def _load_libraries() -> tuple[ctypes.CDLL, ctypes.CDLL]:
    x11_path = ctypes.util.find_library("X11")
    xext_path = ctypes.util.find_library("Xext")
    if not x11_path or not xext_path:
        raise RuntimeError("X11/Xext libraries are unavailable")
    x11 = ctypes.CDLL(x11_path)
    xext = ctypes.CDLL(xext_path)

    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x11.XDefaultRootWindow.restype = Window
    x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x11.XInternAtom.restype = ctypes.c_ulong
    x11.XQueryTree.argtypes = [
        ctypes.c_void_p,
        Window,
        ctypes.POINTER(Window),
        ctypes.POINTER(Window),
        ctypes.POINTER(ctypes.POINTER(Window)),
        ctypes.POINTER(ctypes.c_uint),
    ]
    x11.XQueryTree.restype = ctypes.c_int
    x11.XFetchName.argtypes = [ctypes.c_void_p, Window, ctypes.POINTER(ctypes.c_char_p)]
    x11.XFetchName.restype = ctypes.c_int
    x11.XGetWindowProperty.argtypes = [
        ctypes.c_void_p,
        Window,
        ctypes.c_ulong,
        ctypes.c_long,
        ctypes.c_long,
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
    ]
    x11.XGetWindowProperty.restype = ctypes.c_int
    x11.XFree.argtypes = [ctypes.c_void_p]
    x11.XFlush.argtypes = [ctypes.c_void_p]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]

    xext.XShapeCombineRectangles.argtypes = [
        ctypes.c_void_p,
        Window,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.POINTER(XRectangle),
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
    ]
    xext.XShapeGetRectangles.argtypes = [
        ctypes.c_void_p,
        Window,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_int),
    ]
    xext.XShapeGetRectangles.restype = ctypes.POINTER(XRectangle)
    return x11, xext


def _window_pid(x11: ctypes.CDLL, display: int, window: int, pid_atom: int) -> int | None:
    actual_type = ctypes.c_ulong()
    actual_format = ctypes.c_int()
    item_count = ctypes.c_ulong()
    bytes_after = ctypes.c_ulong()
    data = ctypes.POINTER(ctypes.c_ubyte)()
    status = x11.XGetWindowProperty(
        display,
        window,
        pid_atom,
        0,
        1,
        False,
        6,  # XA_CARDINAL
        ctypes.byref(actual_type),
        ctypes.byref(actual_format),
        ctypes.byref(item_count),
        ctypes.byref(bytes_after),
        ctypes.byref(data),
    )
    if status != 0 or not data or actual_format.value != 32 or item_count.value < 1:
        if data:
            x11.XFree(data)
        return None
    try:
        return int(ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))[0])
    finally:
        x11.XFree(data)


def _children(x11: ctypes.CDLL, display: int, window: int) -> list[int]:
    root = Window()
    parent = Window()
    children = ctypes.POINTER(Window)()
    count = ctypes.c_uint()
    if not x11.XQueryTree(
        display,
        window,
        ctypes.byref(root),
        ctypes.byref(parent),
        ctypes.byref(children),
        ctypes.byref(count),
    ):
        return []
    try:
        return [int(children[index]) for index in range(count.value)] if children else []
    finally:
        if children:
            x11.XFree(children)


def _window_name(x11: ctypes.CDLL, display: int, window: int) -> str | None:
    value = ctypes.c_char_p()
    if not x11.XFetchName(display, window, ctypes.byref(value)) or not value:
        return None
    try:
        return value.value.decode("utf-8", errors="replace") if value.value else None
    finally:
        x11.XFree(value)


def _find_windows(x11: ctypes.CDLL, display: int, pid: int | None, name: str) -> list[int]:
    root = int(x11.XDefaultRootWindow(display))
    pid_atom = int(x11.XInternAtom(display, b"_NET_WM_PID", False))
    pending = _children(x11, display, root)
    matches = []
    checked = 0
    while pending and checked < 4096:
        window = pending.pop()
        checked += 1
        window_pid = _window_pid(x11, display, window, pid_atom)
        if (pid is not None and window_pid == pid) or _window_name(x11, display, window) == name:
            matches.append(window)
        pending.extend(_children(x11, display, window))
    return matches


def apply_click_through(pid: int | None, name: str, wait_seconds: float = 5.0) -> bool:
    x11, xext = _load_libraries()
    display = x11.XOpenDisplay(None)
    if not display:
        return False
    try:
        deadline = time.monotonic() + wait_seconds
        windows = []
        while len(windows) != 1 and time.monotonic() < deadline:
            windows = _find_windows(x11, display, pid, name)
            if len(windows) != 1:
                time.sleep(0.1)
        if len(windows) != 1:
            return False
        window = windows[0]

        xext.XShapeCombineRectangles(
            display,
            window,
            2,  # ShapeInput
            0,
            0,
            None,
            0,
            0,  # ShapeSet
            0,  # Unsorted
        )
        x11.XFlush(display)
        count = ctypes.c_int()
        ordering = ctypes.c_int()
        rectangles = xext.XShapeGetRectangles(
            display,
            window,
            2,
            ctypes.byref(count),
            ctypes.byref(ordering),
        )
        if rectangles:
            x11.XFree(rectangles)
        return count.value == 0
    finally:
        x11.XCloseDisplay(display)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--name", default="conky (Bhola)")
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.check:
        _load_libraries()
        print("XShape click-through helper check passed.")
        return 0
    if args.pid == os.getpid():
        return 2
    if not apply_click_through(args.pid, args.name):
        print("Could not apply verified click-through to the Conky window.")
        return 1
    print("Verified empty input region for click-through.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
