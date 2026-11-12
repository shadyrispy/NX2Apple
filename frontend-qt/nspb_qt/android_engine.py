"""Where the Android engine lives, and how to fetch it.

Unlike the iOS engine (seedds/nxnative at a pin plus patches), the Android one is not built here:
it is nx2android's own repository (shirai91/nx2android), which vendors its engine (`nxnative/`)
beside the `porter/` pipeline. The launcher keeps a shallow clone in the state folder (or a folder
the player picked in Settings) and runs `python -m porter …` inside it — see android_porter.py.

A folder is an Android engine tree when it holds both `porter/cli.py` and `nxnative/dm/`. Pure
stdlib, no Qt; the Model runs the commands off the UI thread through run_fetch.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

DEFAULT_REPO = 'https://github.com/shirai91/nx2android'
DEFAULT_REF = 'main'          # a moving ref: `main` tracks the newest release work; pin a tag for a frozen build
ENGINE_DIR = 'android-engine'
ANDROID_OFFLINE = 'androidOffline'   # the clone/fetch failed to reach GitHub
ANDROID_FETCH = 'androidFetch'       # any other stop


def is_engine_tree(d: str | Path) -> bool:
    """porter/ + the vendored nxnative core: what `python -m porter` needs beside it."""
    if not d:
        return False
    p = Path(d)
    return p.joinpath('porter', 'cli.py').is_file() and p.joinpath('nxnative', 'dm').is_dir()


def default_dest(state_dir: str) -> str:
    """The engine's home in the state folder (`~/Library/Application Support/NS Port Builder/android-engine`
    on a Mac, `%LOCALAPPDATA%/NS Port Builder/android-engine` on Windows)."""
    return str(Path(state_dir, ENGINE_DIR)) if state_dir else ''


def installed(state_dir: str, chosen: str = '') -> str:
    """The folder porter runs in: the player's pick (Settings) when it is an engine tree, else the
    state folder's clone. Empty string when neither is there (the row offers Fetch)."""
    if chosen and is_engine_tree(chosen):
        return chosen
    fallback = default_dest(state_dir)
    return fallback if is_engine_tree(fallback) else ''


def head(dest: str | Path) -> str:
    """HEAD of the clone read from its files (no git process): the commit id, '' when unreadable."""
    git = Path(dest) / '.git'
    try:
        h = (git / 'HEAD').read_text(encoding='utf-8').strip()
    except OSError:
        return ''
    if not h.startswith('ref: '):
        return h
    ref = h[5:]
    try:
        return (git / ref).read_text(encoding='utf-8').strip()
    except OSError:
        pass
    try:
        for line in (git / 'packed-refs').read_text(encoding='utf-8').splitlines():
            if line.endswith(' ' + ref):
                return line.split(' ', 1)[0]
    except OSError:
        pass
    return ''


def clone_command(dest: str, repo: str = DEFAULT_REPO, ref: str = DEFAULT_REF) -> list[str]:
    return ['git', 'clone', '--depth', '1', '--branch', ref, repo, dest]


def update_commands(dest: str, repo: str = DEFAULT_REPO, ref: str = DEFAULT_REF) -> list[list[str]]:
    """Fetch the ref again and move the checkout onto it (a shallow clone: no history to walk)."""
    return [
        ['git', '-C', dest, 'fetch', '--depth', '1', 'origin', ref],
        ['git', '-C', dest, 'checkout', 'FETCH_HEAD'],
    ]


_OFFLINE_MARKS = ('Could not resolve', 'unable to access', 'Connection ', 'timed out', 'connection refused',
                  'Could not read from remote repository')


def failure_kind(log: str) -> str:
    """What a failed clone/fetch was, from its output: git's network words mean offline."""
    return ANDROID_OFFLINE if any(m in log for m in _OFFLINE_MARKS) else ANDROID_FETCH


def run_fetch(cmd: list[str], cwd: str, line: Callable[[str], None], **popen) -> tuple[bool, str | None]:
    """Run one clone/fetch command, pass its lines on, and return (ok, failure kind or None).
    Blocking: call it off the UI thread (the Model's engine-sync thread does)."""
    tail = ''
    try:
        p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding='utf-8', errors='replace', **popen)
        assert p.stdout is not None
        for out in p.stdout:
            line(out)
            tail = (tail + out)[-4000:]
        ok = p.wait() == 0
    except OSError as e:
        line(f'{e}\n')
        return False, ANDROID_FETCH
    return ok, None if ok else failure_kind(tail)


def needs_fetch(state_dir: str, chosen: str = '') -> bool:
    """No engine where the settings point: the build fetches it first (like engine.needs_sync_before_build)."""
    return not installed(state_dir, chosen)
