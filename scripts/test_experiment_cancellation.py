"""Cancellation during loaded-registry inspection must not retain a partial registry."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch


class RegistryCancellation(unittest.TestCase):
    def load(self):
        common=SimpleNamespace(**{name:None for name in
            ('PROFILE','ManagementFactory','Runtime','MC','number','heap_snapshot','guard_world')})
        bridge=SimpleNamespace(JavaClass=Mock(),JavaBoundMember=Mock())
        path=Path(__file__).resolve().parents[1]/'scenarios/lab_experiment.py'
        spec=importlib.util.spec_from_file_location('registry_cancellation_fixture',path)
        module=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{'java':bridge,'lab_common':common}):spec.loader.exec_module(module)
        return module,bridge

    def test_cancel_before_any_bridge_call(self):
        module,bridge=self.load()
        with self.assertRaisesRegex(RuntimeError,'cancelled'):
            module.loaded_mods(Mock(side_effect=RuntimeError('cancelled')))
        bridge.JavaClass.assert_not_called()
        self.assertIsNone(module.LOADED_MODS)

    def test_cancel_between_calls_does_not_cache_partial_registry(self):
        module,bridge=self.load()
        cancel=Mock(side_effect=[None,None,RuntimeError('cancelled')])
        with self.assertRaisesRegex(RuntimeError,'cancelled'):module.loaded_mods(cancel)
        self.assertEqual(bridge.JavaBoundMember.call_count,1)
        self.assertIsNone(module.LOADED_MODS)

    def test_cached_registry_still_checks_cancellation(self):
        module,bridge=self.load();module.LOADED_MODS={'fixture':'1'}
        with self.assertRaisesRegex(RuntimeError,'cancelled'):
            module.loaded_mods(Mock(side_effect=RuntimeError('cancelled')))
        self.assertEqual(module.LOADED_MODS,{'fixture':'1'})
        bridge.JavaClass.assert_not_called()


if __name__=='__main__':unittest.main()
