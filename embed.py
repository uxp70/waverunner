'''Put the game window inside the app window.

SetParent makes the game a child of a Tk frame, so it renders inside
WaveRunner and resizes with the frame. Detaching restores the original parent
and window styles, so the game goes back to being an ordinary window.
'''
from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32

GWL_STYLE = -16
WS_CHILD = 0x40000000
WS_POPUP = 0x80000000
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_SYSMENU = 0x00080000
SWP_FRAMECHANGED = 0x0020
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010

user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.restype = ctypes.c_long
user32.GetParent.restype = wintypes.HWND

# hwnd -> (original parent, original style), so detach can undo everything.
_saved = {}


def _style(hwnd) -> int:
    return int(user32.GetWindowLongW(hwnd, GWL_STYLE))


def _set_style(hwnd, style: int) -> None:
    user32.SetWindowLongW(hwnd, GWL_STYLE, style)
    user32.SetWindowPos(hwnd, None, 0, 0, 0, 0,
                        SWP_FRAMECHANGED | SWP_NOZORDER | SWP_NOACTIVATE)


def embedded(hwnd) -> bool:
    return bool(hwnd) and hwnd in _saved


def attach(hwnd, host) -> bool:
    '''Make hwnd a child of host. False when it is already attached to it.'''
    if not hwnd or not host:
        return False
    if hwnd in _saved:
        return True
    parent = user32.GetParent(hwnd)
    style = _style(hwnd)
    _saved[hwnd] = (parent, style)
    user32.SetParent(hwnd, host)
    frame_bits = WS_POPUP | WS_CAPTION | WS_THICKFRAME
    frame_bits |= WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU
    _set_style(hwnd, (style & ~frame_bits) | WS_CHILD)
    return True


def detach(hwnd) -> None:
    '''Give the window back to the desktop with the styles it started with.'''
    saved = _saved.pop(hwnd, None)
    if not saved:
        return
    parent, style = saved
    user32.SetParent(hwnd, parent)
    _set_style(hwnd, style)


def move(hwnd, x: int, y: int, width: int, height: int) -> None:
    user32.MoveWindow(hwnd, int(x), int(y), max(1, int(width)), max(1, int(height)), True)
