"""Action failure boundaries: release movement and preserve unexpected screens."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


class PlayerActionSafety(unittest.TestCase):
    def setUp(self):
        self.ms, self.mc, self.live = Mock(), Mock(), Mock()
        self.ms.player_position.return_value = [1.5, 101, 0.5]
        self.core = SimpleNamespace(assert_live=self.live, release_inputs=Mock(), wait_live=Mock(), wait_position=Mock(), read_block=Mock(), block_kind=Mock())
        common = SimpleNamespace(MC=self.mc, guard_world=Mock())
        spec = importlib.util.spec_from_file_location("action_safety", Path(__file__).resolve().parents[1] / "scenarios/lab_player_actions.py")
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"minescript": self.ms, "lab_common": common, "lab_validation_core": self.core,
                                     "lab_mob_route":SimpleNamespace(WAYPOINTS=(),verify_route=Mock()),
                                     "java": SimpleNamespace(JavaClass=lambda _: Mock())}):
            spec.loader.exec_module(self.module)
        self.actions = self.module.PlayerActions(Mock())

    def test_focus_failure_releases_both_movement_keys(self):
        self.live.side_effect = [None, RuntimeError("focus lost")]
        with self.assertRaisesRegex(RuntimeError, "focus lost"):
            self.actions.leg(8.5, sprint=True)
        self.ms.player_press_forward.assert_called_with(False)
        self.ms.player_press_sprint.assert_called_with(False)

    def test_punch_never_attacks_a_block(self):
        self.mc.hitResult.getType.return_value = "BLOCK"
        with self.assertRaisesRegex(RuntimeError, "clear air"):
            self.actions.punch()
        self.ms.player_press_attack.assert_not_called()

    def test_failed_jump_releases_jump_key(self):
        self.mc.player.onGround.return_value = True
        self.live.side_effect = [None, RuntimeError("cancelled")]
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            self.actions.jump()
        self.ms.player_press_jump.assert_called_with(False)

    def test_cleanup_preserves_an_unowned_screen(self):
        owned = Mock()
        owned.equals.return_value = False
        self.actions.inventory_screen = owned
        self.actions.close_inventory()
        self.mc.player.closeContainer.assert_not_called()
        self.assertIsNone(self.actions.inventory_screen)

    def test_failed_screen_close_still_releases_inputs(self):
        with patch.object(self.actions, "close_inventory", side_effect=RuntimeError("screen close failed")):
            with self.assertRaisesRegex(RuntimeError, "screen close failed"):
                self.actions.cleanup()
        self.ms.press_key_bind.assert_called_with("key.inventory", False)
        self.core.release_inputs.assert_called_once()


if __name__ == "__main__":
    unittest.main()
