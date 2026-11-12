"""Driving the Android engine's porter CLI (nx2android/porter) the way its own GUI does.

porter is a subprocess: `python -m porter <command> --json` prints exactly one JSON document on
stdout (its chatter is redirected to stderr), and a build or install run with `--progress json`
streams one JSON event per stdout line. The events come from the engine's own Progress class
(nxnative/scripts/build_ipa_from_nsp.py): say, stage, step, progress, stage_end — and a final
result event with the APK and data pack's paths.

This module is the adapter between that stream and the launcher: run_json for the short commands
the dependency panel and the device/save pages drive, RunView to fold an event stream into the
same stage list the `--progress lines` parser builds, and the argv builders for every command the
window can run. Pure subprocess, no Qt: the Model already runs builds on its own thread.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from typing import Any

_TS_PREFIX = re.compile(r'^\[[\d.]+\]\s*')   # say() stamps every message "[<elapsed seconds>] "


# ---------------------------------------------------------------- short commands (one JSON document)

def run_json(engine_root: str, python: str, args: list[str], timeout: float | None = None) -> tuple[Any | None, int]:
    """Run `python -m porter <args>` and parse its one JSON document.

    Returns (document or None, exit code). A missing document with code 0 means the command printed
    nothing parseable (porter's BuildError path already returned a {'error': …} document for the
    ones the window drives with --json). Blocking: call it off the UI thread.
    """
    cmd = [python, '-m', 'porter', *args]
    try:
        p = subprocess.run(cmd, cwd=engine_root, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           text=True, encoding='utf-8', errors='replace', timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None, -1
    out = (p.stdout or '').strip()
    if not out:
        return None, p.returncode
    try:
        return json.loads(out), p.returncode
    except ValueError:
        return None, p.returncode


# ---------------------------------------------------------------- argv builders

def doctor_args() -> list[str]:
    return ['doctor', '--json']


def profiles_args() -> list[str]:
    return ['profiles', '--json']


def inspect_args(folder: str, keys: str = '') -> list[str]:
    return ['inspect', folder, '--json'] + (['-k', keys] if keys else [])


def devices_args() -> list[str]:
    return ['devices', '--json']


def tools_args(download: bool = False, only: str = '') -> list[str]:
    args = ['tools']
    if download:
        args.append('--download')
    if only:
        args += ['--only', only]
    args.append('--json')
    return args


def port_args(folder: str, *, keys: str = '', out: str = '', language: str = '', install: bool = False,
              device: str = '', fps60: bool = False, touch: bool = False, mt_replay: bool = False,
              alias_headroom: int | None = None, vercode_offset: int | None = None) -> list[str]:
    """`porter port` with the options the build page exposes (porter/cli.py's flags, --progress json)."""
    args = ['port', folder]
    if keys:
        args += ['-k', keys]
    if out:
        args += ['-o', out]
    if language:
        args += ['-l', language]
    if fps60:
        args.append('--fps60')
    if touch:
        args.append('--touch')
    if mt_replay:
        args.append('--mt-replay')
    if alias_headroom is not None:
        args += ['--alias-headroom', str(alias_headroom)]
    if vercode_offset:
        args += ['--vercode-offset', str(vercode_offset)]
    if device:
        args += ['--device', device]
    if install:
        args.append('--install')
    args += ['--progress', 'json']
    return args


def install_args(data: str, apk: str = '', device: str = '', replace_signer: bool = False,
                 romfs_at: str = '') -> list[str]:
    """Install a made data pack (`<App>-data`) onto the connected device, streaming progress events."""
    args = ['install', data]
    if apk:
        args += ['--apk', apk]
    if device:
        args += ['--device', device]
    if replace_signer:
        args.append('--replace-signer')
    if romfs_at:
        args += ['--romfs-at', romfs_at]
    args += ['--progress', 'json']
    return args


def saves_args(sub: str, package: str = '', device: str = '', dest: str = '', src: str = '',
               name: str = '') -> list[str]:
    """`porter saves <apps|list|export|import>`; apps/list take --json, export/import print a document too."""
    args = ['saves', sub, '--json']
    if device:
        args += ['--device', device]
    if sub != 'apps' and package:
        args += ['--package', package]
    if sub == 'export':
        args += [dest or '.']
        if name:
            args += ['--name', name]
    elif sub == 'import':
        args.append(src)
        if name:
            args += ['--name', name]
    return args


# ---------------------------------------------------------------- the event stream → stage list

@dataclass
class StageView:
    """One build stage, the same fields the build page's rows show (Model.Stage's shape)."""
    id: int = 0
    name: str = ''
    state: str = 'pending'      # pending | running | done | failed
    detail: str = ''
    percent: float = 0.0


def hms(s: float) -> str:
    """Seconds → m:ss, or h:mm:ss from an hour on (the engine's own hms)."""
    s = int(s)
    h, m = divmod(s // 60, 60)
    return f'{h}:{m:02d}:{s % 60:02d}' if h else f'{m}:{s % 60:02d}'


class RunView:
    """Folds porter's JSON event stream into a stage list, a last error, and the final result.

    feed() one parsed event at a time (parse_event for raw lines); the caller reads `stages`,
    `last_error` and `result` after each feed and mirrors `stages` into its own list.
    """
    def __init__(self) -> None:
        self.stages: list[StageView] = []
        self.planned = 0
        self.result: dict | None = None
        self.last_error = ''

    def feed(self, ev: Any) -> None:
        if not isinstance(ev, dict):
            return
        kind = ev.get('ev')
        if kind == 'stage':
            if ev.get('n'):
                self.planned = int(ev['n'])
            for st in self.stages:
                if st.state == 'running':
                    st.state = 'done'
                    st.percent = 100.0
            self.stages.append(StageView(id=int(ev.get('k', len(self.stages) + 1)),
                                         name=str(ev.get('name', '')), state='running',
                                         detail=str(ev.get('step', ''))))
        elif kind == 'step':
            st = self._running()
            if st is not None:
                st.detail = str(ev.get('step', ''))
        elif kind == 'progress':
            st = self._running()
            if st is None:
                return
            frac = ev.get('frac')
            if frac is not None:
                st.percent = min(float(frac) * 100.0, 100.0)
            parts = [str(ev.get('step') or ''), str(ev.get('note') or '')]
            detail = ' · '.join(p for p in parts if p)
            eta = ev.get('eta')
            if eta:
                detail = (detail + ' · ' if detail else '') + f'{hms(float(eta))} left'
            if detail:
                st.detail = detail
        elif kind == 'stage_end':
            st = self._running()
            if st is None:
                st = StageView(id=int(ev.get('k', 0)), name=str(ev.get('name', '')))
                self.stages.append(st)
            st.state = 'done' if ev.get('ok', True) else 'failed'
            if ev.get('summary'):
                st.detail = str(ev['summary'])
            if st.state == 'done':
                st.percent = 100.0
        elif kind == 'say':
            msg = _TS_PREFIX.sub('', str(ev.get('msg', ''))).strip()
            if '[RED]' in msg:
                self.last_error = msg.replace('[RED]', '').strip()
        elif kind == 'result':
            self.result = ev

    def _running(self) -> StageView | None:
        for st in reversed(self.stages):
            if st.state == 'running':
                return st
        return None


def parse_event(line: str) -> Any | None:
    """One stdout line of a `--progress json` run → its JSON event, or None (plain log text)."""
    s = line.strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except ValueError:
        return None


def classify(last_error: str) -> str:
    """The failure the launcher can name from porter's last [RED] line. Keys problems reuse the
    existing keys failure card; everything else stays the generic build failure."""
    low = last_error.lower()
    if 'prod.keys' in low or 'keys' in low:
        return 'keys'
    return ''
