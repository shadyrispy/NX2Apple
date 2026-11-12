"""The Android target in the window: the target cycle, the options card, and the labels per language."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nspb_qt import library as lib_mod   # noqa: E402


class AndroidTargetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            from PySide6.QtWidgets import QApplication
        except ImportError as e:
            raise unittest.SkipTest(f'PySide6 not installed: {e}')
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        from PySide6.QtCore import QSettings
        from nspb_qt import model as model_mod

        self._state_tmp = tempfile.TemporaryDirectory()
        state_dir = Path(self._state_tmp.name) / 'state'
        ini_file = str(Path(self._state_tmp.name) / 'settings.ini')
        self._p_state = mock.patch.object(lib_mod, 'default_state_dir', return_value=state_dir)
        self._p_qsettings = mock.patch.object(
            model_mod, 'QSettings', side_effect=lambda *a, **kw: QSettings(ini_file, QSettings.IniFormat)
        )
        self._p_check_deps = mock.patch.object(model_mod.Model, 'check_deps', lambda _self: None)
        self._p_state.start()
        self._p_qsettings.start()
        self._p_check_deps.start()

    def tearDown(self) -> None:
        self._p_check_deps.stop()
        self._p_qsettings.stop()
        self._p_state.stop()
        self._state_tmp.cleanup()

    def _delete(self, m, w) -> None:
        from PySide6.QtCore import QEvent
        w.close()
        w.deleteLater()
        m.deleteLater()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def _window(self, lang_code: str):
        from nspb_qt.i18n import Lang
        from nspb_qt.model import Model
        from nspb_qt.ui import MainWindow

        p = mock.patch.object(Model, 'check_deps', lambda self: None)
        p.start()
        self.addCleanup(p.stop)
        m = Model()
        m.lang = Lang(lang_code)
        w = MainWindow(m)
        self.addCleanup(self._delete, m, w)
        w.show()
        self.app.processEvents()
        return m, w

    def test_target_cycles_through_android(self) -> None:
        m, w = self._window('en')
        w._switch_page('builds')
        self.app.processEvents()
        self.assertEqual(m.target, 'ios')
        self.assertTrue(w.android_group.isHidden())

        w._toggle_target()   # macOS order: ios → mac-app
        self.assertEqual(m.target, 'mac-app')
        self.assertTrue(w.android_group.isHidden())

        w._toggle_target()   # → android
        self.assertEqual(m.target, 'android')
        self.assertFalse(w.android_group.isHidden())
        self.assertTrue(w.install_group.isHidden())
        self.assertEqual(w.target_btn.text(), 'Output: Android APK')

        w._toggle_target()   # → back to ios
        self.assertEqual(m.target, 'ios')
        self.assertTrue(w.android_group.isHidden())
        self.assertFalse(w.install_group.isHidden())

    def test_android_labels_in_every_language(self) -> None:
        from nspb_qt.i18n import Lang

        for lang in Lang.all():
            m, w = self._window(lang.code)
            w._switch_page('builds')
            w._toggle_target()   # ios → mac-app
            w._toggle_target()   # → android
            self.app.processEvents()
            for lbl in (w.target_title_lbl, w.target_btn, w.android_lang_lbl, w.android_device_lbl):
                text = lbl.text()
                self.assertTrue(text, f'{lang.code}: an Android label is empty')
                self.assertFalse(text.startswith(('android.', 'build.', 'target.')),
                                 f'{lang.code}: {text!r} is a raw l10n key')
            self.assertNotEqual(w.target_hint.text(), '')
            settings_lbl = w.android_engine_title_lbl.text()
            self.assertTrue(settings_lbl and not settings_lbl.startswith('androidEngine.'),
                            f'{lang.code}: the settings row label is a raw key')

    def test_option_switches_reach_the_model_and_persist(self) -> None:
        m, w = self._window('en')
        w._switch_page('builds')
        w._toggle_target()
        w._toggle_target()   # android
        self.app.processEvents()
        w.android_fps_switch.setChecked(True)
        self.assertTrue(m.android_fps60)
        self.assertIs(m.settings_value('androidFps60', False), True)
        w.android_touch_switch.setChecked(True)
        self.assertTrue(m.android_touch)
        w.android_mtr_switch.setChecked(True)
        self.assertTrue(m.android_mt_replay)
        w.android_install_switch.setChecked(True)
        self.assertTrue(m.android_install)

        # the language combo's data is porter's -l value
        combo = w.android_lang_combo
        for i in range(combo.count()):
            combo.setCurrentIndex(i)
            self.assertEqual(m.android_language, str(combo.itemData(i) or ''))

    def test_android_dep_rows_replace_ios_ones(self) -> None:
        from nspb_qt.model import Model

        with mock.patch.object(Model, 'android_engine_path', '/eng'), \
             mock.patch('nspb_qt.model.aport.run_json', return_value=([
                 {'name': 'Android NDK', 'ok': False, 'detail': 'not found', 'required': True},
                 {'name': '.NET SDK', 'ok': True, 'detail': '10.0.403', 'required': True},
                 {'name': 'adb', 'ok': False, 'detail': '', 'required': True},
             ], 0)) as run_json:
            m = Model()
            m.target = 'android'
            m._check_deps()
        ids = [d.id for d in m.deps]
        self.assertIn('android_engine', ids)
        self.assertIn('android_ndk', ids)
        self.assertIn('android_dotnet', ids)
        self.assertIn('android_adb', ids)
        self.assertNotIn('xcode', ids)
        self.assertNotIn('metal', ids)
        by_id = {d.id: d for d in m.deps}
        self.assertFalse(by_id['android_ndk'].ok)
        self.assertTrue(by_id['android_ndk'].required)
        self.assertEqual(by_id['android_ndk'].cwd, '/eng')
        self.assertTrue(by_id['android_dotnet'].ok)
        run_json.assert_called_once()
        self.assertEqual(run_json.call_args.args[2], ['doctor', '--json'])

    def test_android_dep_rows_offer_fetch_when_engine_missing(self) -> None:
        from nspb_qt.model import Model

        with mock.patch.object(Model, 'android_engine_path', ''), \
             mock.patch('nspb_qt.android_engine.default_dest', return_value='/state/android-engine'):
            m = Model()
            m.target = 'android'
            m._check_deps()
        self.assertEqual([d.id for d in m.deps], ['android_engine'])
        self.assertFalse(m.deps[0].ok)
        self.assertEqual(m.deps[0].detail, '/state/android-engine')
        self.assertTrue(m.deps[0].required)


if __name__ == '__main__':
    unittest.main()
