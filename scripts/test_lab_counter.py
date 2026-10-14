"""Counter transport and invalid-scenario fixtures; no game/capture starts."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("counter_fixture", ROOT / "scenarios/lab_counter_core.py")
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)


class CounterSafety(unittest.TestCase):
    def test_result_handle_released_if_conversion_fails(self):
        ms = Mock()
        ms.java_class.return_value = 1
        ms.java_member.side_effect = [2, 3, 4]
        ms.java_call_method.return_value = 5
        ms.java_to_string.side_effect = ValueError("conversion failed")
        reader = core.CounterReader(ms, 100)
        with self.assertRaises(ValueError): reader.value("getFps")
        ms.java_release.assert_called_with(5)
        reader.close()
        ms.java_release.assert_called_with(1, 2, 3, 4)
        self.assertEqual(reader.handles, [])

    def test_cached_members_not_recreated_during_samples(self):
        ms = Mock()
        ms.java_class.return_value = 1
        ms.java_member.side_effect = [2, 3, 4]
        ms.java_call_method.return_value = 5
        ms.java_to_string.return_value = "120"
        reader = core.CounterReader(ms, 100)
        self.assertEqual(reader.value("getFps"), "120")
        self.assertEqual(reader.value("getFps"), "120")
        self.assertEqual(ms.java_member.call_count, 3)
        reader.close()

    def test_invalid_boolean_rejected(self):
        ms = Mock()
        ms.java_to_string.return_value = "unknown"
        reader = core.CounterReader(ms, 100)
        with self.assertRaisesRegex(RuntimeError, "invalid boolean"):
            reader.boolean("isPaused")
        reader.close()

    def test_condition_changes_rejected(self):
        conditions = json.loads((ROOT / "presets/lab-conditions.json").read_text())
        good = {"game_fps_counter": 120, "foreground": True, "paused": False, "screen": None,
                "position": [0.5, 101, 0.5], "orientation": [0, 6.5]}
        self.assertEqual(core.counter_issues(good, conditions), [])
        for key, value, issue in (("foreground", False, "unpaused_foreground_world"),
                                  ("screen", "Chat screen", "unpaused_foreground_world"),
                                  ("game_fps_counter", 0, "game_fps_counter"),
                                  ("position", [1.5, 101, 0.5], "position"),
                                  ("orientation", [0, float("nan")], "orientation")):
            with self.subTest(key=key):
                self.assertIn(issue, core.counter_issues({**good, key: value}, conditions))


if __name__ == "__main__":
    unittest.main(verbosity=2)
