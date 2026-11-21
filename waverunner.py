#!/usr/bin/env python3
'''
WaveRunner - docks a game window to a fixed rectangle and replays a routine of
mouse clicks and key presses against it.

Two input modes
  Background  the default. Clicks and keys are posted into the game window, so
              the real cursor never moves, the real keyboard is untouched and
              you can keep using your PC while the routine runs.
  Foreground  moves the real cursor with pydirectinput; the game has to be the
              active window.

Hotkeys
  F8  start / stop      F9  stop now      F7  record the cursor as a click step

Setup
  Python 3.10+ on Windows:  pip install -r requirements.txt
  Build an exe:  pyinstaller --onefile --noconsole --name WaveRunner waverunner.py

Updates
  Every launch asks the release tagged 'latest' whether a newer build exists
  (updater.py). A private repository needs a read-only token in
  update_token.txt beside the exe or in WAVERUNNER_TOKEN.

Routine file: routine.json, a JSON list of steps.
  {'do': 'click', 'at': [0.42, 0.55]}    values <= 1.0 are a fraction of the client area
  {'do': 'click', 'at': [540, 320]}      larger values are raw pixels from the client corner
  {'do': 'double', 'at': [0.5, 0.5]}
  {'do': 'move', 'at': [0.5, 0.5]}
  {'do': 'key', 'key': '1', 'hold': 0.05}
  {'do': 'wait', 's': 0.8}
'''
from __future__ import annotations

import ctypes
import json
import queue
import random
import threading
import time
import tkinter as tk
from ctypes import wintypes
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import background
import updater

try:
    import pydirectinput
except ImportError as exc:
    raise SystemExit('missing dependency: pip install pydirectinput') from exc

try:
    import keyboard
except ImportError as exc:
    raise SystemExit('missing dependency: pip install keyboard') from exc


APP_VERSION = '1.2.0'

CONFIG = {
    'window_title': 'Roblox',
    'dock': {'x': 40, 'y': 40, 'w': 1280, 'h': 760, 'always_on_top': False},
    'hotkeys': {'toggle': 'f8', 'capture': 'f7', 'stop': 'f9'},
    'input_mode': 'background',
    'send_to_back': True,
    'keep_awake': True,
    'loop': True,
    'loop_gap_s': 1.5,
    'require_focus': True,
    'step_pause_s': 0.03,
    'jitter': {'click_px': 2, 'wait_s': 0.04},
    'check_updates': True,
}

ROUTINE_PATH = updater.app_dir() / 'routine.json'

user32 = ctypes.windll.user32

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
HWND_TOP = ctypes.c_void_p(0)
HWND_BOTTOM = ctypes.c_void_p(1)
HWND_TOPMOST = ctypes.c_void_p(-1)

user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, wintypes.UINT,
]
user32.SetWindowPos.restype = wintypes.BOOL


def enable_dpi_awareness() -> None:
    '''Keep reported coordinates aligned with the pixels the mouse really uses.'''
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def list_windows():
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _callback(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                found.append((hwnd, buf.value))
        return True

    user32.EnumWindows(_callback, 0)
    return found


def find_window(title_part: str, exclude: str = ''):
    want = title_part.lower()
    skip = exclude.lower()
    for hwnd, title in list_windows():
        low = title.lower()
        if want in low and (not skip or skip not in low):
            return hwnd
    return None


def client_geometry(hwnd):
    '''(screen_x, screen_y, width, height) of the window client area.'''
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    origin = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(origin))
    return origin.x, origin.y, rect.right, rect.bottom


def cursor_pos():
    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def is_foreground(hwnd) -> bool:
    return user32.GetForegroundWindow() == hwnd


class Engine:
    def __init__(self, log) -> None:
        self.log = log
        self.hwnd = None
        self.bg_target = None
        self.routine = []
        self.thread = None
        self.stop_event = threading.Event()
        pydirectinput.PAUSE = 0.02
        pydirectinput.FAILSAFE = False

    @staticmethod
    def mode() -> str:
        return 'background' if CONFIG['input_mode'] == 'background' else 'foreground'

    def dock(self) -> bool:
        self.hwnd = find_window(CONFIG['window_title'], exclude='WaveRunner')
        if not self.hwnd:
            self.log('No window matching ' + repr(CONFIG['window_title']) + '. Start the game first.')
            return False
        box = CONFIG['dock']
        flags = SWP_NOZORDER | SWP_SHOWWINDOW | SWP_NOACTIVATE
        user32.SetWindowPos(
            self.hwnd, HWND_TOP, box['x'], box['y'], box['w'], box['h'], flags,
        )
        if box['always_on_top']:
            user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        if self.mode() == 'background':
            if CONFIG['send_to_back']:
                user32.SetWindowPos(self.hwnd, HWND_BOTTOM, 0, 0, 0, 0,
                                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
            self.bg_target = background.target_window(self.hwnd)
            self.log('Docked to {w}x{h} at ({x}, {y}) - background mode, your desktop stays yours.'.format(
                w=box['w'], h=box['h'], x=box['x'], y=box['y']))
            return True
        try:
            user32.SetForegroundWindow(self.hwnd)
        except Exception:
            pass
        self.log('Docked to {w}x{h} at ({x}, {y}) - foreground mode.'.format(
            w=box['w'], h=box['h'], x=box['x'], y=box['y']))
        return True

    def load(self, path=None) -> None:
        path = path or ROUTINE_PATH
        if not path.exists():
            self.routine = []
            return
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as exc:
            self.log('Could not read {}: {}'.format(path.name, exc))
            return
        if isinstance(data, list):
            self.routine = [s for s in data if isinstance(s, dict) and 'do' in s]
            self.log('Loaded {} steps from {}.'.format(len(self.routine), path.name))
        else:
            self.log('{} should contain a JSON list of steps.'.format(path.name))

    def save(self, path=None, silent: bool = False) -> None:
        path = path or ROUTINE_PATH
        try:
            path.write_text(json.dumps(self.routine, indent=2), encoding='utf-8')
            if not silent:
                self.log('Saved {} steps to {}.'.format(len(self.routine), path.name))
        except OSError as exc:
            self.log('Could not save: {}'.format(exc))

    def capture(self) -> None:
        if not self.hwnd:
            self.log('Dock the window first, then record.')
            return
        ox, oy, w, h = client_geometry(self.hwnd)
        if w <= 0 or h <= 0:
            self.log('Window has no client area - re-dock it.')
            return
        x, y = cursor_pos()
        fx = round((x - ox) / w, 4)
        fy = round((y - oy) / h, 4)
        self.routine.append({'do': 'click', 'at': [fx, fy], 'button': 'left'})
        self.log('Step {}: click at ({:.3f}, {:.3f}) = px ({}, {})'.format(
            len(self.routine), fx, fy, x - ox, y - oy))
        self.save(silent=True)

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        if not self.routine:
            self.log('Routine is empty - press F7 on each spot while the game is focused.')
            return
        if not self.hwnd or not user32.IsWindow(self.hwnd):
            if not self.dock():
                return
        if self.mode() == 'background':
            self.bg_target = background.target_window(self.hwnd)
            if not self.bg_target:
                self.log('Could not find the game input surface - dock again.')
                return
        self.stop_event.clear()
        if CONFIG['keep_awake']:
            background.keep_awake()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        self.log('Running {} steps{} in {} mode.'.format(
            len(self.routine), ' on loop' if CONFIG['loop'] else '', self.mode()))

    def stop(self) -> None:
        self.stop_event.set()

    def toggle(self) -> None:
        if self.thread and self.thread.is_alive():
            self.stop()
        else:
            self.start()

    def _loop(self) -> None:
        try:
            while not self.stop_event.is_set():
                if not self._run_once():
                    break
                if not CONFIG['loop']:
                    break
                self._sleep(CONFIG['loop_gap_s'])
        finally:
            if CONFIG['keep_awake']:
                background.allow_sleep()
        self.log('Stopped.')

    def _run_once(self) -> bool:
        for index, step in enumerate(self.routine, start=1):
            if self.stop_event.is_set():
                return False
            if self.mode() == 'foreground' and CONFIG['require_focus'] and self._corner_panic():
                self.log('Cursor hit the corner - emergency stop.')
                return False
            if (self.mode() == 'foreground' and CONFIG['require_focus']
                    and self.hwnd and not is_foreground(self.hwnd)):
                self.log('Game is not the active window - pausing.')
                return False
            try:
                self._exec(step)
            except Exception as exc:
                self.log('Step {} failed: {}'.format(index, exc))
                return False
            time.sleep(CONFIG['step_pause_s'])
        return True

    def _exec(self, step) -> None:
        kind = step.get('do')

        if kind in ('click', 'double', 'move'):
            x, y = self._client_point(step.get('at', (0.5, 0.5)))
            if self.mode() == 'background':
                if kind == 'move':
                    background.move(self.hwnd, x, y)
                elif not background.click(self.hwnd, x, y, step.get('button', 'left'),
                                          double=(kind == 'double')):
                    raise RuntimeError('the game refused the click')
                return
            sx, sy = self._to_screen(x, y)
            if kind == 'move':
                pydirectinput.moveTo(sx, sy)
            else:
                clicks = 2 if kind == 'double' else 1
                pydirectinput.click(sx, sy, clicks=clicks, interval=0.08,
                                    button=step.get('button', 'left'))
            return

        if kind == 'key':
            name = str(step.get('key', ''))
            hold = float(step.get('hold', 0.05))
            if not name:
                return
            if self.mode() == 'background':
                target = self.bg_target or background.target_window(self.hwnd)
                self.bg_target = target
                if not background.key(target, name, hold):
                    raise RuntimeError('unknown key ' + repr(name))
                return
            pydirectinput.keyDown(name)
            self._sleep(hold)
            pydirectinput.keyUp(name)
            return

        if kind == 'wait':
            self._sleep(float(step.get('s', 0.5)))
            return

        raise ValueError('unknown step type ' + repr(kind))

    def _client_point(self, at):
        '''Routine coordinates as pixels inside the client area, jittered.'''
        _ox, _oy, w, h = client_geometry(self.hwnd)
        fx = float(at[0])
        fy = float(at[1])
        x = fx * w if fx <= 1.0 else fx
        y = fy * h if fy <= 1.0 else fy
        j = CONFIG['jitter']['click_px']
        if j:
            x += random.uniform(-j, j)
            y += random.uniform(-j, j)
        x = int(round(max(0, min(max(0, w - 1), x))))
        y = int(round(max(0, min(max(0, h - 1), y))))
        return x, y

    def _to_screen(self, x, y):
        ox, oy, _w, _h = client_geometry(self.hwnd)
        return ox + x, oy + y

    def _sleep(self, seconds: float) -> None:
        j = CONFIG['jitter']['wait_s']
        self.stop_event.wait(max(0.0, seconds + random.uniform(-j, j)))

    @staticmethod
    def _corner_panic() -> bool:
        x, y = cursor_pos()
        return x <= 2 and y <= 2


class App:
    def __init__(self, root, engine) -> None:
        self.root = root
        self.engine = engine
        self.events = queue.Queue()
        engine.log = self.log_async

        root.title('WaveRunner')
        root.geometry('680x520')
        root.minsize(580, 420)

        bar = ttk.Frame(root, padding=(10, 10, 10, 4))
        bar.pack(fill='x')
        ttk.Button(bar, text='Dock game', command=self.dock).pack(side='left')
        ttk.Button(bar, text='Start (F8)', command=self.toggle).pack(side='left', padx=6)
        ttk.Button(bar, text='Stop (F9)', command=self.stop).pack(side='left')
        ttk.Button(bar, text='Record click (F7)', command=self.capture).pack(side='left', padx=6)

        bar2 = ttk.Frame(root, padding=(10, 0, 10, 6))
        bar2.pack(fill='x')
        ttk.Button(bar2, text='Load routine', command=self.load).pack(side='left')
        ttk.Button(bar2, text='Save routine', command=self.save).pack(side='left', padx=6)
        ttk.Button(bar2, text='Clear', command=self.clear).pack(side='left')
        self.status = ttk.Label(bar2, text='idle')
        self.status.pack(side='right')

        bar3 = ttk.Frame(root, padding=(10, 0, 10, 8))
        bar3.pack(fill='x')
        ttk.Label(bar3, text='Input:').pack(side='left')
        self.mode_var = tk.StringVar(value=CONFIG['input_mode'])
        ttk.Radiobutton(bar3, text='Background - keep using your PC', value='background',
                        variable=self.mode_var, command=self.set_mode).pack(side='left', padx=4)
        ttk.Radiobutton(bar3, text='Foreground - moves the real cursor', value='foreground',
                        variable=self.mode_var, command=self.set_mode).pack(side='left', padx=4)

        body = ttk.Frame(root, padding=(10, 0, 10, 10))
        body.pack(fill='both', expand=True)
        self.log_box = tk.Text(body, height=14, wrap='word', state='disabled',
                               font=('Consolas', 9))
        scroll = ttk.Scrollbar(body, command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=scroll.set)
        self.log_box.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')

        self._bind_hotkeys()
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(60, self._pump)

        engine.load()
        self.log('Ready. Target window: ' + repr(CONFIG['window_title']) + '.')
        self.log('Background mode: leave the game window visible (not minimised) and use your PC as usual.')
        root.after(800, self.check_updates)

    def _bind_hotkeys(self) -> None:
        keys = CONFIG['hotkeys']
        try:
            keyboard.add_hotkey(keys['toggle'], lambda: self.events.put(('toggle', None)))
            keyboard.add_hotkey(keys['capture'], lambda: self.events.put(('capture', None)))
            keyboard.add_hotkey(keys['stop'], lambda: self.events.put(('stop', None)))
        except Exception as exc:
            self.log('Global hotkeys unavailable ({}); use the buttons.'.format(exc))

    def set_mode(self) -> None:
        CONFIG['input_mode'] = self.mode_var.get()
        if CONFIG['input_mode'] == 'background':
            self.log('Background input: clicks and keys go straight to the game window; '
                     'the cursor and keyboard stay yours.')
        else:
            self.log('Foreground input: the real cursor moves and the game takes focus.')

    def _pump(self) -> None:
        while True:
            try:
                name, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if name == 'toggle':
                self.toggle()
            elif name == 'capture':
                self.capture()
            elif name == 'stop':
                self.stop()
            elif name == 'log':
                self._append(payload)
            elif name == 'update':
                self.offer_update(payload)
            elif name == 'restart':
                self._append('Updated to WaveRunner {} - restarting.'.format(payload))
                self.root.after(400, self.close)
        self._refresh_status()
        self.root.after(60, self._pump)

    def check_updates(self) -> None:
        if CONFIG['check_updates']:
            threading.Thread(target=self._check_updates, daemon=True).start()

    def _check_updates(self) -> None:
        try:
            info = updater.check(APP_VERSION)
        except Exception as exc:
            self.log_async('Update check skipped: {}'.format(exc))
            return
        if not info:
            self.log_async('WaveRunner {} is the newest build.'.format(APP_VERSION))
            return
        self.events.put(('update', info))

    def offer_update(self, info) -> None:
        answer = messagebox.askyesno(
            'Update available',
            'WaveRunner {} is available (this copy is {}).\n\n'
            'Download it and restart now?'.format(info['version'], APP_VERSION),
            parent=self.root,
        )
        if not answer:
            self.log('Update {} left for later.'.format(info['version']))
            return
        self.log('Downloading WaveRunner {}...'.format(info['version']))
        threading.Thread(target=self._download_update, args=(info,), daemon=True).start()

    def _download_update(self, info) -> None:
        target = updater.app_dir() / 'WaveRunner.new.exe'
        try:
            staged = updater.download(info['asset_url'], target)
        except Exception as exc:
            self.log_async('Update failed: {}'.format(exc))
            return
        if updater.install(staged):
            self.events.put(('restart', info['version']))
        else:
            self.log_async('Saved {} - run it to update.'.format(staged.name))

    def dock(self) -> None:
        self.engine.dock()

    def toggle(self) -> None:
        self.engine.toggle()

    def stop(self) -> None:
        self.engine.stop()

    def capture(self) -> None:
        self.engine.capture()

    def load(self) -> None:
        path = filedialog.askopenfilename(
            title='Load routine',
            initialdir=str(ROUTINE_PATH.parent),
            filetypes=[('JSON', '*.json'), ('All files', '*.*')],
        )
        if path:
            self.engine.load(Path(path))

    def save(self) -> None:
        path = filedialog.asksaveasfilename(
            title='Save routine',
            initialdir=str(ROUTINE_PATH.parent),
            initialfile=ROUTINE_PATH.name,
            defaultextension='.json',
            filetypes=[('JSON', '*.json')],
        )
        if path:
            self.engine.save(Path(path))

    def clear(self) -> None:
        count = len(self.engine.routine)
        if count and not messagebox.askyesno('Clear routine', 'Delete all {} steps?'.format(count)):
            return
        self.engine.routine = []
        self.engine.save(silent=True)
        self.log('Routine cleared.')

    def log_async(self, message: str) -> None:
        self.events.put(('log', message))

    def _append(self, message: str) -> None:
        self.log_box.configure(state='normal')
        self.log_box.insert('end', message + '\n')
        self.log_box.see('end')
        self.log_box.configure(state='disabled')

    def _refresh_status(self) -> None:
        running = bool(self.engine.thread and self.engine.thread.is_alive())
        self.status.configure(text='{} - {} steps - {}'.format(
            'running' if running else 'idle', len(self.engine.routine),
            CONFIG['input_mode']))

    def close(self) -> None:
        self.engine.stop()
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        self.root.destroy()


def main() -> None:
    enable_dpi_awareness()
    root = tk.Tk()
    engine = Engine(log=lambda _message: None)
    App(root, engine)
    root.mainloop()


if __name__ == '__main__':
    main()
