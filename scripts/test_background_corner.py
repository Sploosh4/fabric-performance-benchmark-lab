"""Diagnostic input pulses release before observations and on failed/cancelled probes."""
import importlib.util
import math
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch


class BackgroundCorner(unittest.TestCase):
    def load(self):
        state={'held':False};ms=Mock()
        ms.player_press_forward.side_effect=lambda held:state.update(held=held)
        path=Path(__file__).resolve().parents[1]/'scenarios/background_corner.py'
        spec=importlib.util.spec_from_file_location('background_corner_fixture',path)
        module=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{'minescript':ms}):spec.loader.exec_module(module)
        return module,ms,state

    def test_physical_pulse_released_before_each_observation(self):
        module,ms,state=self.load();target=[1.5,101,18.5]
        positions=iter(([1.5,101,18.32],[1.5,101,18.32],[1.5,101,18.32],target,target))
        def sample():
            self.assertFalse(state['held'])
            return next(positions),True,False
        with patch.object(module.time,'sleep'):
            module.settle(target,SimpleNamespace(sample=sample),Mock(),0)
        ms.player_press_forward.assert_any_call(True)
        ms.player_press_forward.assert_called_with(False)
        ms.player_press_sneak.assert_called_with(False)
        ms.player_set_orientation.assert_called_once_with(0,6.5)

    def test_cancelled_probe_releases_inputs(self):
        module,ms,state=self.load()
        probe=SimpleNamespace(sample=Mock(side_effect=[([1.5,101,18.32],True,False),RuntimeError('cancelled')]))
        with self.assertRaisesRegex(RuntimeError,'cancelled'):
            module.settle([1.5,101,18.5],probe,Mock(),0)
        ms.player_press_forward.assert_called_with(False)
        ms.player_press_sneak.assert_called_with(False)

    def test_normal_braking_distance_converges_with_tick_and_minimized_quantization(self):
        for quantum in (.05,.1):
            with self.subTest(quantum=quantum):
                module,ms,state=self.load();position=[1.5,101,16.0738];target=[1.5,101,17.5]
                direction={'axis':2,'sign':1}
                def orient(yaw,pitch):
                    direction.update(axis=0 if abs(yaw)==90 else 2,sign=1 if yaw in (-90,0) else -1)
                def sleep(seconds):
                    if state['held']:
                        position[direction['axis']]+=direction['sign']*1.3*math.ceil(seconds/quantum)*quantum
                def sample():
                    self.assertFalse(state['held'])
                    return list(position),True,False
                ms.player_set_orientation.side_effect=orient
                with patch.object(module.time,'sleep',side_effect=sleep):
                    module.settle(target,SimpleNamespace(sample=sample),Mock(),0)
                self.assertLessEqual(abs(position[2]-target[2]),.2)
                self.assertFalse(state['held'])

    def test_outside_correction_bound_is_rejected_without_walking(self):
        module,ms,state=self.load()
        probe=SimpleNamespace(sample=lambda:([10,101,18.5],True,False))
        with self.assertRaisesRegex(RuntimeError,'bound'):
            module.settle([1.5,101,18.5],probe,Mock(),0)
        self.assertNotIn(((True,),{}),ms.player_press_forward.call_args_list)
        ms.player_press_sneak.assert_called_with(False)


if __name__=='__main__':unittest.main()
