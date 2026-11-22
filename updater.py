'''Launch-time update check for WaveRunner.

Reads the GitHub release tagged `latest`, compares the version that release was
built from with the running copy, and - once the user agrees - downloads the
newer executable, swaps it in and restarts the app.

The repository is public, so GitHub answers anonymous requests; no token is
stored or needed. WAVERUNNER_TOKEN and update_token.txt are still honoured if
they exist, for anyone pointing this at a private fork.
'''
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

REPO = 'uxp70/waverunner'
RELEASE_TAG = 'latest'
TOKEN_FILE = 'update_token.txt'
API_TIMEOUT_S = 15
DOWNLOAD_TIMEOUT_S = 120

UPDATE_SCRIPT = '''@echo off
setlocal
:wait
tasklist /fi "PID eq {pid}" 2>nul | find "{pid}" >nul
if errorlevel 1 goto ready
timeout /t 1 /nobreak >nul
goto wait
:ready
if exist "{exe}" move /y "{exe}" "{backup}" >nul 2>&1
move /y "{staged}" "{exe}" >nul 2>&1
if not exist "{exe}" move /y "{backup}" "{exe}" >nul 2>&1
del "{backup}" >nul 2>&1
start "" "{exe}"
del "%~f0"
'''


class _StopAtRedirect(urllib.request.HTTPRedirectHandler):
    '''Keep the GitHub token away from the storage host it redirects to.'''

    def redirect_request(self, *args, **kwargs):
        return None


def app_dir() -> Path:
    '''The folder the program really lives in, frozen or not.'''
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def parse_version(text):
    '''(1, 2, 10) from "v1.2.10-beta", so versions compare as numbers.'''
    match = re.search(r'\d+(?:\.\d+)*', str(text or ''))
    if not match:
        return None
    return tuple(int(part) for part in match.group(0).split('.'))


def is_newer(remote, local) -> bool:
    a, b = parse_version(remote), parse_version(local)
    if not a or not b:
        return False
    width = max(len(a), len(b))
    return a + (0,) * (width - len(a)) > b + (0,) * (width - len(b))


def token() -> str:
    '''Optional GitHub token: environment first, then a file beside the exe.'''
    value = os.environ.get('WAVERUNNER_TOKEN', '').strip()
    if value:
        return value
    try:
        return (app_dir() / TOKEN_FILE).read_text(encoding='utf-8').strip()
    except OSError:
        return ''


def _request(url, accept='application/vnd.github+json', auth=''):
    headers = {'Accept': accept, 'User-Agent': 'WaveRunner'}
    if auth:
        headers['Authorization'] = 'Bearer ' + auth
    return urllib.request.Request(url, headers=headers)


def release_version(release) -> str:
    '''Read the version= line the build workflow stamps into the release body.'''
    for line in (release.get('body') or '').splitlines():
        line = line.strip()
        if line.lower().startswith('version='):
            return line.split('=', 1)[1].strip()
    match = re.search(r'\d+(?:\.\d+)+', release.get('name') or '')
    return match.group(0) if match else ''


def check(current):
    '''None when up to date, else a dict describing the newer release.'''
    url = 'https://api.github.com/repos/{}/releases/tags/{}'.format(REPO, RELEASE_TAG)
    try:
        with urllib.request.urlopen(_request(url, auth=token()), timeout=API_TIMEOUT_S) as resp:
            release = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 404):
            raise LookupError('release not readable; GitHub answered {}'.format(exc.code)) from exc
        raise
    remote = release_version(release)
    if not remote:
        raise LookupError('release has no version stamp')
    if not is_newer(remote, current):
        return None
    asset = next((a for a in release.get('assets') or []
                  if str(a.get('name', '')).lower().endswith('.exe')), None)
    if not asset:
        raise LookupError('release {} has no executable attached'.format(remote))
    return {
        'version': remote,
        'asset_url': asset['url'],
        'size': asset.get('size', 0),
        'page': release.get('html_url', ''),
    }


def download(asset_url, dest: Path) -> Path:
    '''Save the release executable to dest, refusing anything that is not one.'''
    auth = token()
    opener = urllib.request.build_opener(_StopAtRedirect)
    try:
        with opener.open(_request(asset_url, 'application/octet-stream', auth),
                         timeout=DOWNLOAD_TIMEOUT_S) as resp:
            data = resp.read()
    except urllib.error.HTTPError as exc:
        location = exc.headers.get('Location') if exc.code in (301, 302, 303, 307, 308) else None
        if not location:
            raise
        # the storage host rejects a forwarded GitHub token, so fetch bare
        with urllib.request.urlopen(_request(location), timeout=DOWNLOAD_TIMEOUT_S) as resp:
            data = resp.read()
    if not data or not data.startswith(b'MZ'):
        raise ValueError('download was not a Windows executable')
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix('.part')
    partial.write_bytes(data)
    partial.replace(dest)
    return dest


def install(staged: Path) -> bool:
    '''Swap staged in for the running exe and restart it. False when not frozen.'''
    if not getattr(sys, 'frozen', False) or os.name != 'nt':
        return False
    exe = Path(sys.executable).resolve()
    script = Path(tempfile.gettempdir()) / 'waverunner-update.cmd'
    script.write_text(
        UPDATE_SCRIPT.format(
            pid=os.getpid(),
            exe=exe,
            backup=exe.with_name(exe.stem + '.old.exe'),
            staged=staged,
        ),
        encoding='ascii',
    )
    subprocess.Popen(['cmd', '/c', str(script)], creationflags=0x08000000, close_fds=True)
    return True
