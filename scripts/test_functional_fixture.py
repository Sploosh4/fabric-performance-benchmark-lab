"""Safety checks for temporary fixtures; all game APIs are mocked."""
import importlib.util
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SOURCE = Path(__file__).resolve().parents[1] / "scenarios/lab_validation_core.py"


class FunctionalFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="functional-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.ms, self.mc, self.guard = Mock(), Mock(), Mock()
        self.mc.isWindowActive.return_value = True
        self.mc.isPaused.return_value = False
        self.ms.screen_name.return_value = None
        spec = importlib.util.spec_from_file_location("functional_fixture_test", SOURCE)
        self.core = importlib.util.module_from_spec(spec)
        common = SimpleNamespace(PROFILE=self.directory, CONDITIONS={"world_folder": "disposable"}, MC=self.mc, guard_world=self.guard)
        with patch.dict(sys.modules, {"minescript": self.ms, "lab_common": common, "java": SimpleNamespace(JavaClass=lambda name: Mock(name=name))}):
            spec.loader.exec_module(self.core)
        self.write = Mock()
        self.fixture = self.core.Fixture(self.directory / "journal.json", self.write)

    def test_occupied_space_is_never_modified(self):
        with patch.object(self.core, "read_region_kinds", return_value=["minecraft:stone"] * 324), self.assertRaisesRegex(RuntimeError, "occupied"):
            self.fixture.build()
        self.ms.execute.assert_not_called()
        self.ms.player_inventory_select_slot.assert_not_called()

    def test_native_region_requires_loaded_chunks_and_inclusive_bounds(self):
        self.mc.level.hasChunkAt.return_value = True
        self.mc.level.getBlockStates.return_value.toList.return_value = "[" + ", ".join(["Block{minecraft:air}"] * 324) + "]"
        self.assertEqual(self.core.read_region_kinds(), ["minecraft:air"] * 324)
        self.core.AABB.assert_called_once_with(-4, 199, -4, 4, 202, 4)
        self.mc.level.hasChunkAt.return_value = False
        with self.assertRaisesRegex(RuntimeError, "not loaded"):
            self.core.read_region_kinds()

    def test_unknown_region_data_is_never_treated_as_air(self):
        self.mc.level.hasChunkAt.return_value = True
        self.mc.level.getBlockStates.return_value.toList.return_value = "[null]"
        with self.assertRaisesRegex(RuntimeError, "324 block states"):
            self.core.read_region_kinds()

    def test_wrong_world_is_rejected_before_input_or_blocks(self):
        self.guard.side_effect = RuntimeError("Wrong world")
        with self.assertRaises(RuntimeError):
            self.fixture.build()
        self.ms.execute.assert_not_called()
        self.ms.get_block_region.assert_not_called()

    def test_focus_loss_or_cancel_prevents_progress(self):
        self.mc.isWindowActive.return_value = False
        with self.assertRaisesRegex(RuntimeError, "foreground"):
            self.core.assert_live()
        stop = self.directory / "stop.json"
        stop.write_text("{}")
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            self.core.assert_live(stop)

    def test_diagnostic_unfocused_world_can_progress_but_paused_world_cannot(self):
        self.core.session_runtime.configure(True)
        self.mc.isWindowActive.return_value=False
        try:
            self.core.assert_live()
            self.mc.isPaused.return_value=True
            with self.assertRaises(RuntimeError):self.core.assert_live()
            self.mc.isPaused.return_value=False;self.ms.screen_name.return_value='PauseScreen'
            with self.assertRaises(RuntimeError):self.core.assert_live()
        finally:self.core.session_runtime.configure(False)

    def test_failed_movement_releases_forward_input(self):
        self.ms.player_position.side_effect = [[0.5, 200, -2.5], [12, 200, 0]]
        self.ms.world_info.return_value = SimpleNamespace(game_ticks=100)
        with self.assertRaisesRegex(RuntimeError, "bounded route"):
            self.fixture.walk()
        self.assertEqual(self.ms.player_press_forward.call_args_list[-1].args, (False,))

    def test_failed_use_releases_use_input(self):
        self.ms.player_position.return_value = [3.5, 200, -0.5]
        self.ms.player_get_targeted_block.return_value = SimpleNamespace(position=[3, 201, 2])
        with patch.object(self.core, "read_block", return_value="minecraft:lever[powered=false]"), \
             patch.object(self.core, "wait_live", side_effect=[None, RuntimeError("focus lost")]):
            with self.assertRaisesRegex(RuntimeError, "focus lost"):
                self.fixture.interact()
        self.assertEqual(self.ms.player_press_use.call_args_list[-1].args, (False,))

    def test_cleanup_preserves_a_changed_block(self):
        self.fixture.owned = [{"position": [0, 199, 0], "kind": "minecraft:smooth_stone"}]
        with patch.object(self.core, "read_block", return_value="minecraft:diamond_block"), \
             patch.object(self.core, "read_blocks", return_value=["minecraft:diamond_block"]), \
             self.assertRaisesRegex(RuntimeError, "Unexpected block preserved"):
            self.fixture.cleanup()
        self.ms.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
