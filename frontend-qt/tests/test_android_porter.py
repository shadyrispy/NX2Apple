"""android_porter.py: the event stream → stage list mapping, the argv builders, and classify."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nspb_qt import android_porter as aport   # noqa: E402


def _events() -> list[dict]:
    """A porter run's events, the shapes its own Progress class emits."""
    return [
        {'ev': 'say', 'msg': '[0.4] [2/6] the rewriter'},
        {'ev': 'stage', 'k': 1, 'n': 6, 'name': 'extract', 'step': 'reading', 't': 1.0},
        {'ev': 'step', 'k': 1, 'name': 'extract', 'step': 'decoding'},
        {'ev': 'progress', 'k': 1, 'name': 'extract', 'step': 'decoding', 'done': 400, 'total': 1000,
         'unit': 'B', 'est': False, 'note': 'warm', 'frac': 0.4, 'eta': 62.0, 'elapsed': 5.0},
        {'ev': 'stage_end', 'k': 1, 'name': 'extract', 'ok': True, 'summary': '1.2 GB', 'elapsed': 8.0},
        {'ev': 'stage', 'k': 2, 'n': 6, 'name': 'rewrite', 'step': '', 't': 9.0},
        {'ev': 'say', 'msg': '[9.2] [RED] no such file: prod.keys'},
        {'ev': 'result', 'apk': '/tmp/Celeste.apk', 'data': '/tmp/Celeste-data', 'title_id': 700000000,
         'name': 'Celeste', 'package': 'org.nx2a.celeste', 'status': 'playable', 'installed': False},
    ]


class RunViewTests(unittest.TestCase):
    def test_full_stream(self) -> None:
        run = aport.RunView()
        for ev in _events():
            run.feed(ev)
        self.assertEqual(run.planned, 6)
        self.assertEqual([st.state for st in run.stages], ['done', 'running'])
        self.assertEqual(run.stages[0].name, 'extract')
        self.assertEqual(run.stages[0].detail, '1.2 GB')
        self.assertEqual(run.stages[0].percent, 100.0)
        self.assertEqual(run.stages[1].name, 'rewrite')
        self.assertEqual(run.last_error, 'no such file: prod.keys')
        self.assertIsNotNone(run.result)
        self.assertEqual(run.result['apk'], '/tmp/Celeste.apk')
        self.assertEqual(run.result['data'], '/tmp/Celeste-data')

    def test_progress_shows_step_note_and_eta(self) -> None:
        run = aport.RunView()
        run.feed({'ev': 'stage', 'k': 1, 'n': 3, 'name': 'extract', 'step': '', 't': 0.0})
        run.feed({'ev': 'progress', 'k': 1, 'name': 'extract', 'step': 'decoding', 'done': 1, 'total': 4,
                  'unit': 'B', 'est': False, 'note': 'warm', 'frac': 0.25, 'eta': 62.0, 'elapsed': 1.0})
        st = run.stages[0]
        self.assertAlmostEqual(st.percent, 25.0)
        self.assertIn('decoding', st.detail)
        self.assertIn('warm', st.detail)
        self.assertIn('1:02 left', st.detail)

    def test_progress_without_running_stage_is_ignored(self) -> None:
        run = aport.RunView()
        run.feed({'ev': 'progress', 'k': 9, 'name': 'x', 'step': '', 'done': None, 'total': None,
                  'unit': '', 'est': False, 'note': '', 'frac': None, 'eta': None, 'elapsed': 0.0})
        self.assertEqual(run.stages, [])

    def test_stage_end_attaches_to_a_new_stage(self) -> None:
        run = aport.RunView()
        run.feed({'ev': 'stage_end', 'k': 1, 'name': 'late', 'ok': False, 'summary': '', 'elapsed': 1.0})
        self.assertEqual(len(run.stages), 1)
        self.assertEqual(run.stages[0].state, 'failed')

    def test_stage_event_closes_the_previous_stage(self) -> None:
        run = aport.RunView()
        run.feed({'ev': 'stage', 'k': 1, 'n': 2, 'name': 'a', 'step': '', 't': 0.0})
        run.feed({'ev': 'stage', 'k': 2, 'n': 2, 'name': 'b', 'step': '', 't': 1.0})
        self.assertEqual([st.state for st in run.stages], ['done', 'running'])

    def test_feed_ignores_non_events(self) -> None:
        run = aport.RunView()
        run.feed('not a dict')          # type: ignore[arg-type]
        run.feed({'no_ev': 1})
        self.assertEqual(run.stages, [])

    def test_parse_event(self) -> None:
        self.assertEqual(aport.parse_event(' {"ev": "say", "msg": "x"} '), {'ev': 'say', 'msg': 'x'})
        self.assertIsNone(aport.parse_event('plain log line'))
        self.assertIsNone(aport.parse_event(''))
        self.assertIsNone(aport.parse_event('[12.3] [RED] also plain'))


class ArgvTests(unittest.TestCase):
    def test_port_args_full(self) -> None:
        args = aport.port_args('/games', keys='/k/keys', out='/out', language='zh-Hans', install=True,
                               device='R58M', fps60=True, touch=True, mt_replay=True,
                               alias_headroom=16, vercode_offset=7)
        self.assertEqual(args, ['port', '/games', '-k', '/k/keys', '-o', '/out', '-l', 'zh-Hans',
                                '--fps60', '--touch', '--mt-replay', '--alias-headroom', '16',
                                '--vercode-offset', '7', '--device', 'R58M', '--install',
                                '--progress', 'json'])

    def test_port_args_minimal(self) -> None:
        self.assertEqual(aport.port_args('/games'), ['port', '/games', '--progress', 'json'])

    def test_install_args(self) -> None:
        self.assertEqual(aport.install_args('/d', apk='/a.apk', device='R58M', replace_signer=True),
                         ['install', '/d', '--apk', '/a.apk', '--device', 'R58M', '--replace-signer',
                          '--progress', 'json'])

    def test_saves_args(self) -> None:
        self.assertEqual(aport.saves_args('apps'), ['saves', 'apps', '--json'])
        self.assertEqual(aport.saves_args('list', package='org.nx2a.celeste'),
                         ['saves', 'list', '--json', '--package', 'org.nx2a.celeste'])
        self.assertEqual(aport.saves_args('export', package='p', dest='/tmp', name='n1'),
                         ['saves', 'export', '--json', '--package', 'p', '/tmp', '--name', 'n1'])
        self.assertEqual(aport.saves_args('import', src='/save', device='R58M'),
                         ['saves', 'import', '--json', '--device', 'R58M', '/save'])

    def test_tools_and_doctor_and_inspect(self) -> None:
        self.assertEqual(aport.doctor_args(), ['doctor', '--json'])
        self.assertEqual(aport.tools_args(download=True, only='ndk'),
                         ['tools', '--download', '--only', 'ndk', '--json'])
        self.assertEqual(aport.inspect_args('/games', '/k'), ['inspect', '/games', '--json', '-k', '/k'])
        self.assertEqual(aport.inspect_args('/games'), ['inspect', '/games', '--json'])

    def test_run_json_parses_one_document(self) -> None:
        doc, code = aport.run_json(str(Path(__file__).parent), sys.executable,
                                   ['-c', 'import json; print(json.dumps({"ok": 1}))'])
        self.assertEqual((doc, code), ({'ok': 1}, 0))
        doc, code = aport.run_json(str(Path(__file__).parent), sys.executable,
                                   ['-c', 'print("not json")'])
        self.assertIsNone(doc)
        doc, code = aport.run_json(str(Path(__file__).parent), sys.executable,
                                   ['-c', 'raise SystemExit(2)'])
        self.assertIsNone(doc)
        self.assertEqual(code, 2)


class ClassifyTests(unittest.TestCase):
    def test_keys_stop(self) -> None:
        self.assertEqual(aport.classify('no such file: prod.keys'), 'keys')
        self.assertEqual(aport.classify('the keys are too old for this update'), 'keys')

    def test_other_stays_unknown(self) -> None:
        self.assertEqual(aport.classify('disk full while extracting'), '')

    def test_hms(self) -> None:
        self.assertEqual(aport.hms(62), '1:02')
        self.assertEqual(aport.hms(3600 + 60), '1:01:00')


if __name__ == '__main__':
    unittest.main()
