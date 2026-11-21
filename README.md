# WaveRunner

A small Windows helper that docks a game window to a fixed rectangle and replays a routine of
mouse clicks and key presses that you record yourself. Nothing is hardcoded to one game or one
screen size - you place the steps.

## Download the exe

Grab `WaveRunner.exe` from the [Releases](../../releases) page. You do not need Python to run it.

The exe is built by GitHub Actions on a `windows-latest` runner straight from `waverunner.py`
(`.github/workflows/build-exe.yml`), so the download always matches this source.

Windows SmartScreen will warn about an unsigned exe from a small project. Use *More info* then
*Run anyway*, or build it yourself from source if you would rather.

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
   where you expect them.
3. Focus the game, hover a spot, press **F7**. A click step is appended to `routine.json` next to
   the exe and saved immediately.
4. **F8** starts and stops the loop, **F9** stops at once, and shoving the cursor into the
   top-left corner is an emergency stop.

Guards: it will not click while the game is not the active window, and it adds a little random
jitter to clicks and waits.

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
| `move` | `at` | move the cursor only |
| `key` | `key`, optional `hold` | press and release a key |
| `wait` | `s` | sleep, in seconds |

`at` is `[x, y]`. A value of `1.0` or less is a fraction of the window client area, so a
routine survives a resize. Anything larger is raw pixels from the client area's top-left
corner.

## Settings

All in the `CONFIG` dict at the top of `waverunner.py`: target window title, dock rectangle,
hotkeys, loop on/off and gap, focus requirement, jitter amounts, and `check_updates` to turn the
launch-time check off entirely.

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
