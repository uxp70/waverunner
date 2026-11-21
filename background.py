'''Input that does not need the game window to be focused.

The foreground path moves the real cursor with pydirectinput, so the game has
to be the active window. This module posts the same clicks and keys into a
window's message queue instead: the real cursor never moves, the real keyboard
is never touched, and you can keep working in another program while the
routine runs.

Measured limits, so nobody is surprised:
  * Keys and clicks posted with PostMessageW do arrive at Roblox's window.
  * A game that turns its camera from raw mouse input (Roblox, Minecraft with
    rawMouseInput:true) will not turn its view from posted messages. The view
    stays where it is. Tower defence play does not need the camera.
  * Keep the window visible. A minimised window still accepts messages, but
    the game may stop drawing and throttle itself.
'''
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101

BUTTONS = {
    'left': (WM_LBUTTONDOWN, WM_LBUTTONUP, 0x0001),
    'right': (WM_RBUTTONDOWN, WM_RBUTTONUP, 0x0002),
    'middle': (WM_MBUTTONDOWN, WM_MBUTTONUP, 0x0010),
}

CWP_SKIPINVISIBLE = 0x0001
CWP_SKIPDISABLED = 0x0002
CWP_SKIPTRANSPARENT = 0x0004

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

EXTENDED_KEYS = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x90}
NAMED_KEYS = {
    'space': 0x20, 'enter': 0x0D, 'return': 0x0D, 'tab': 0x09, 'shift': 0x10,
    'ctrl': 0x11, 'control': 0x11, 'alt': 0x12, 'esc': 0x1B, 'escape': 0x1B,
    'backspace': 0x08, 'delete': 0x2E, 'insert': 0x2D, 'home': 0x24, 'end': 0x23,
    'pageup': 0x21, 'pagedown': 0x22, 'up': 0x26, 'down': 0x28, 'left': 0x25,
    'right': 0x27, 'capslock': 0x14, 'numlock': 0x90,
}
for _n in range(1, 13):
    NAMED_KEYS['f{}'.format(_n)] = 0x6F + _n

user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.ChildWindowFromPointEx.argtypes = [wintypes.HWND, wintypes.POINT, wintypes.UINT]
user32.ChildWindowFromPointEx.restype = wintypes.HWND
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.ClientToScreen.restype = wintypes.BOOL
user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.ScreenToClient.restype = wintypes.BOOL
user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
user32.MapVirtualKeyW.restype = wintypes.UINT
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetClientRect.restype = wintypes.BOOL
kernel32.SetThreadExecutionState.argtypes = [ctypes.c_ulong]
kernel32.SetThreadExecutionState.restype = ctypes.c_ulong


def _point(x, y) -> int:
    '''Pack a client point the way mouse messages expect it.'''
    return ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)


def post(hwnd, message, wparam=0, lparam=0) -> bool:
    '''Queue one message for the window. False when Windows refuses it.'''
    if not hwnd:
        return False
    try:
        return bool(user32.PostMessageW(hwnd, message, wparam, lparam))
    except Exception:
        return False


def child_at(hwnd, x, y):
    '''The deepest visible child window at a point - where input really lands.'''
    point = wintypes.POINT(int(x), int(y))
    current = hwnd
    for _ in range(8):
        try:
            child = user32.ChildWindowFromPointEx(
                current, point,
                CWP_SKIPINVISIBLE | CWP_SKIPDISABLED | CWP_SKIPTRANSPARENT)
        except Exception:
            break
        if not child or child == current:
            break
        current = child
    return current


def target_window(hwnd):
    '''The window to post keys to: the render surface in the middle of the client area.'''
    rect = wintypes.RECT()
    try:
        if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return hwnd
    except Exception:
        return hwnd
    return child_at(hwnd, max(1, rect.right // 2), max(1, rect.bottom // 2)) or hwnd


def _child_point(top, child, x, y):
    '''Translate a top-level client point into the child's own client point.'''
    if not child or child == top:
        return int(x), int(y)
    point = wintypes.POINT(int(x), int(y))
    try:
        if not user32.ClientToScreen(top, ctypes.byref(point)):
            return int(x), int(y)
        if not user32.ScreenToClient(child, ctypes.byref(point)):
            return int(x), int(y)
    except Exception:
        return int(x), int(y)
    return point.x, point.y


def click(top, x, y, button='left', double=False, hold=0.03) -> bool:
    '''Post a click at a client point of the docked window.'''
    down, up, flag = BUTTONS.get(str(button or 'left').lower(), BUTTONS['left'])
    child = child_at(top, x, y)
    cx, cy = _child_point(top, child, x, y)
    where = _point(cx, cy)
    post(child, WM_MOUSEMOVE, 0, where)
    clicks = 2 if double else 1
    ok = True
    for _ in range(clicks):
        ok = post(child, down, flag, where) and ok
        time.sleep(max(0.0, float(hold)))
        ok = post(child, up, 0, where) and ok
        if clicks > 1:
            time.sleep(0.07)
    return ok


def move(top, x, y) -> bool:
    '''Post a pointer move without touching the real cursor.'''
    child = child_at(top, x, y)
    cx, cy = _child_point(top, child, x, y)
    return post(child, WM_MOUSEMOVE, 0, _point(cx, cy))


def virtual_key(name) -> int:
    '''Windows virtual key code for a routine key name, or 0.'''
    text = str(name or '').strip()
    if not text:
        return 0
    low = text.lower()
    if low in NAMED_KEYS:
        return NAMED_KEYS[low]
    if len(text) == 1:
        if text == ' ':
            return 0x20
        if text.isalnum():
            return ord(text.upper())
    return 0


def _key_lparam(vk, released=False) -> int:
    scan = 0
    try:
        scan = user32.MapVirtualKeyW(vk, 0) & 0xFF
    except Exception:
        pass
    value = 1 | (scan << 16)
    if vk in EXTENDED_KEYS:
        value |= 1 << 24
    if released:
        value |= (1 << 30) | (1 << 31)
    return value


def key(hwnd, name, hold=0.05) -> bool:
    '''Post a key down/up pair. Roblox keeps the key held between the two.'''
    vk = virtual_key(name)
    if not vk:
        return False
    sent = post(hwnd, WM_KEYDOWN, vk, _key_lparam(vk))
    time.sleep(max(0.0, float(hold)))
    sent = post(hwnd, WM_KEYUP, vk, _key_lparam(vk, released=True)) and sent
    return sent


def keep_awake(display=False) -> bool:
    '''Stop Windows from sleeping or locking the session mid-run.'''
    flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED
    if display:
        flags |= ES_DISPLAY_REQUIRED
    try:
        return bool(kernel32.SetThreadExecutionState(flags))
    except Exception:
        return False


def allow_sleep() -> None:
    try:
        kernel32.SetThreadExecutionState(ES_CONTINUOUS)
    except Exception:
        pass
