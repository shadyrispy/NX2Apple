"""android_engine.py: the engine-tree test, the clone/update argv, and the fetch runner."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nspb_qt import android_engine as aeng   # noqa: E402


def _make_tree(base: Path) -> None:
    """A minimal engine tree: porter/cli.py + nxnative/dm."""
    base.mkdir(parents=True, exist_ok=True)
    (base / 'porter').mkdir(exist_ok=True)
    (base / 'porter' / 'cli.py').write_text('', encoding='utf-8')
    (base / 'nxnative' / 'dm').mkdir(parents=True, exist_ok=True)


class IsEngineTreeTests(unittest.TestCase):
    def test_porter_and_vendored_core(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(aeng.is_engine_tree(d))
            (Path(d, 'porter').mkdir())
            (Path(d, 'porter', 'cli.py').write_text('', encoding='utf-8'))
            self.assertFalse(aeng.is_engine_tree(d))   # porter alone is not enough
            (Path(d, 'nxnative', 'dm').mkdir(parents=True))
            self.assertTrue(aeng.is_engine_tree(d))

    def test_empty_and_missing(self) -> None:
        self.assertFalse(aeng.is_engine_tree(''))
        self.assertFalse(aeng.is_engine_tree('/nonexistent/path/here'))


class InstalledTests(unittest.TestCase):
    def test_chosen_wins_when_valid(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            _make_tree(Path(d, 'chosen'))
            self.assertEqual(aeng.installed(d, str(Path(d, 'chosen'))), str(Path(d, 'chosen')))

    def test_default_clone_used_when_choice_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            _make_tree(Path(d, 'android-engine'))
            self.assertEqual(aeng.installed(d, str(Path(d, 'gone'))), str(Path(d, 'android-engine')))
            self.assertEqual(aeng.installed(d, ''), str(Path(d, 'android-engine')))

    def test_nothing_installed(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(aeng.installed(d, ''), '')

    def test_needs_fetch_follows_installed(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(aeng.needs_fetch(d, ''))
            _make_tree(Path(d, 'android-engine'))
            self.assertFalse(aeng.needs_fetch(d, ''))


class HeadTests(unittest.TestCase):
    def test_detached_head(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            git = Path(d, '.git')
            git.mkdir()
            (git / 'HEAD').write_text('abc123\n', encoding='utf-8')
            self.assertEqual(aeng.head(d), 'abc123')

    def test_branch_ref(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            git = Path(d, '.git')
            (git / 'refs' / 'heads').mkdir(parents=True)
            (git / 'HEAD').write_text('ref: refs/heads/main\n', encoding='utf-8')
            (git / 'refs' / 'heads' / 'main').write_text('def456\n', encoding='utf-8')
            self.assertEqual(aeng.head(d), 'def456')

    def test_packed_refs(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            git = Path(d, '.git')
            git.mkdir()
            (git / 'HEAD').write_text('ref: refs/heads/main\n', encoding='utf-8')
            (git / 'packed-refs').write_text('aaa111 refs/remotes/origin/x\nbbb222 refs/heads/main\n',
                                             encoding='utf-8')
            self.assertEqual(aeng.head(d), 'bbb222')

    def test_no_git(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(aeng.head(d), '')


class CommandTests(unittest.TestCase):
    def test_clone_command(self) -> None:
        self.assertEqual(aeng.clone_command('/dest'),
                         ['git', 'clone', '--depth', '1', '--branch', 'main', aeng.DEFAULT_REPO, '/dest'])

    def test_update_commands(self) -> None:
        self.assertEqual(aeng.update_commands('/dest', 'https://example/x', 'v1'),
                         [['git', '-C', '/dest', 'fetch', '--depth', '1', 'origin', 'v1'],
                          ['git', '-C', '/dest', 'checkout', 'FETCH_HEAD']])

    def test_failure_kind_offline(self) -> None:
        self.assertEqual(aeng.failure_kind('fatal: unable to access repo: Connection refused'), aeng.ANDROID_OFFLINE)
        self.assertEqual(aeng.failure_kind('error: Could not resolve host'), aeng.ANDROID_OFFLINE)
        self.assertEqual(aeng.failure_kind('fatal: not a git repository'), aeng.ANDROID_FETCH)

    def test_run_fetch_streams_and_classifies(self) -> None:
        py = sys.executable
        lines: list[str] = []
        ok, kind = aeng.run_fetch([py, '-c', 'print("hello"); print("world")'], str(Path.cwd()), lines.append)
        self.assertTrue(ok)
        self.assertIsNone(kind)
        self.assertEqual([ln.strip() for ln in lines], ['hello', 'world'])

        lines.clear()
        ok, kind = aeng.run_fetch([py, '-c',
                                   'import sys; print("fatal: unable to access"); sys.exit(1)'],
                                  str(Path.cwd()), lines.append)
        self.assertFalse(ok)
        self.assertEqual(kind, aeng.ANDROID_OFFLINE)

        lines.clear()
        ok, kind = aeng.run_fetch([py, '-c', 'print("boom"); raise SystemExit(3)'],
                                  str(Path.cwd()), lines.append)
        self.assertFalse(ok)
        self.assertEqual(kind, aeng.ANDROID_FETCH)


if __name__ == '__main__':
    unittest.main()
