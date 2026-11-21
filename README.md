# WaveRunner

A small Windows helper that docks a game window to a fixed rectangle and replays a routine of
mouse clicks and key presses that you record yourself. Nothing is hardcoded to one game or one
screen size - you place the steps.

It runs in the background: clicks and keys are posted into the game window, so the cursor and
keyboard stay yours and you can keep using the PC while a routine runs.

## Download the exe

Grab `WaveRunner.exe` from the [Releases](../../releases) page. You do not need Python to run it.

The exe is built by GitHub Actions on a `windows-latest` runner straight from `waverunner.py`
(`.github/workflows/build-exe.yml`), so the download always matches this source - no local build
step, no local toolchain.

Windows SmartScreen will warn about an unsigned exe from a small project. Use *More info* then
*Run anyway*, or build it yourself from source if you would rather.

## Background mode (default)

Waking the macro and then sitting in it was the old limit. The window still has to exist on this
PC - the game itself cannot run anywhere else - but the macro no longer needs to own your desktop.

| | Background | Foreground |
| --- | --- | --- |
| Real cursor moves | no | yes |
| Game needs focus | no | yes |
| You can use other apps | yes | no |
| How input is sent | `PostMessageW` into the window | `SendInput` via pydirectinput |

How it works: `background.py` finds the render window inside the game (the deepest visible child
under the client area), posts `WM_MOUSEMOVE`, `WM_LBUTTONDOWN`/`WM_LBUTTONUP` and
`WM_KEYDOWN`/`WM_KEYUP` to it with client-area coordinates, and translates between the docked
window's coordinates and that child's. It also calls `SetThreadExecutionState`, so Windows does
not sleep or lock the session while a routine is running. `Send to back` is on, so the game window
sits behind your work instead of in front of it.

What it will not do, measured rather than guessed:

- **Camera rotation.** Games that read raw mouse motion - Roblox included - do not turn their
  view from synthetic messages. Walking, clicking, tower placement, upgrades and key abilities
  all work; turning the camera with the mouse does not. Tower defence play does not need it.
- **Minimised windows.** Messages still queue for a minimised window, but the game may stop
  drawing and throttle itself. Leave the window visible, just behind your other windows.
- **Games that read key state directly.** Roblox handles posted key messages; a game that polls
  `GetAsyncKeyState` instead would ignore them. Switch the radio button to *Foreground* for those.

Nothing about this is specific to Roblox: it drives whatever window `CONFIG['window_title']`
matches, and the radio button switches back to real input at any time.

## Updates

Every launch asks GitHub for the release tagged `latest` and compares the version stamped into it
with the running copy (`APP_VERSION` in `waverunner.py`). When a newer build exists the app offers
to download it, restarts into it once you agree, and leaves the old exe behind as
`WaveRunner.old.exe` until the swap succeeds. Downloads are rejected unless they start with the
`MZ` header of a Windows executable.

This repository is private, so GitHub will not answer that request without a token:

1. Create a fine-grained personal access token with read-only **Contents** access to
   `uxp70/waverunner`.
2. Either save it as `update_token.txt` next to `WaveRunner.exe`, or set the `WAVERUNNER_TOKEN`
   environment variable.

With no token the app skips the check, says so in the log, and runs as normal. Never commit the
token: both `update_token.txt` and the swap files are git-ignored. The one fallback that needs no
credential is making the repository public, after which the check works on its own.

## Run from source

```
pip install -r requirements.txt
python waverunner.py
```

## Use

1. Open the game window.
2. Click **Dock game**. WaveRunner finds the window whose title contains `Roblox`
   (`CONFIG['window_title']`) and snaps it to a fixed 1280x760 rectangle, so coordinates stay
   where you expect them. In background mode the game is not focused and is pushed behind your
   windows.
3. Hover a spot in the game and press **F7**. A click step is appended to `routine.json` next to
   the exe and saved immediately. Recording works the same in both modes; in background mode the
   coordinates are read from the docked client area, so keep the window where you docked it.
4. **F8** starts and stops the loop, **F9** stops at once. Hotkeys are global through the
   `keyboard` package, so they work from whatever app you are in; run WaveRunner as administrator
   if a game window that is elevated swallows them.

Guards: background mode posts to one window only and never touches your cursor; foreground mode
refuses to click while the game is not the active window, and pushing the cursor into the
top-left corner is an emergency stop. Both add a little random jitter to clicks and waits, and
both release held keys when you stop.

## Routine format

`routine.json` ships as an empty list on purpose - nothing is guessed for you. It is a list of
steps:

```json
[
  {"do": "click", "at": [0.42, 0.55]},
  {"do": "key", "key": "1", "hold": 0.05},
  {"do": "wait", "s": 0.8}
]
```

| step | fields | meaning |
| --- | --- | --- |
| `click` | `at`, optional `button` | one click |
| `double` | `at` | double click |
| `move` | `at` | move the pointer only |
| `key` | `key`, optional `hold` | press and release a key |
| `wait` | `s` | sleep, in seconds |

`at` is `[x, y]`. A value of `1.0` or less is a fraction of the window client area, so a
routine survives a resize. Anything larger is raw pixels from the client area's top-left
corner. `key` takes a single character (`1`, `e`, `f`) or a name (`space`, `enter`, `esc`,
`tab`, `shift`, `up`, `f1` ...).

## Settings

All in the `CONFIG` dict at the top of `waverunner.py`: target window title, dock rectangle,
hotkeys, `input_mode` (`background` or `foreground`), `send_to_back`, `keep_awake`, loop on/off
and gap, focus requirement for foreground mode, jitter amounts, and `check_updates` to turn the
launch-time check off entirely. The input mode and update check are also switchable from the
window at runtime.

## Build the exe yourself

```
pip install pyinstaller pydirectinput keyboard
pyinstaller --onefile --noconsole --name WaveRunner waverunner.py
```

The result is `dist/WaveRunner.exe`. Building it needs Windows, because the app uses Win32
window APIs.

## Note

Automating input in an online game is normally against that game's rules, and accounts do get
actioned for it. That risk is on whoever runs it.
