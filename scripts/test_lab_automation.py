"""Offline world-boundary and condition fixtures; never starts Minecraft."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT.parent.parent / "sodium-automation"


class LabBoundaries(unittest.TestCase):
    def setUp(self):
        self.world = SimpleNamespace(name="RestWorld_26.1", dimension="minecraft:overworld")
        self.version = SimpleNamespace(minecraft="26.1.2")
        self.server = Mock()
        self.server.getWorldPath.return_value = str(PROFILE / "saves/Lab_RestWorld_sodium_automation")
        self.mc = Mock()
        self.mc.hasSingleplayerServer.return_value = True
        self.mc.getSingleplayerServer.return_value = self.server
        self.ms = SimpleNamespace(world_info=lambda: self.world, version_info=lambda: self.version)
        def java_class(name):
            if name == "net.minecraft.client.Minecraft":
                return SimpleNamespace(getInstance=lambda: self.mc)
            return SimpleNamespace(ROOT="root")
        spec = importlib.util.spec_from_file_location("lab_fixture_common", ROOT / "scenarios/lab_common.py")
        self.lab = importlib.util.module_from_spec(spec)
        # Point the imported script at the prepared profile; all Java/MS access is mocked.
        self.lab.__file__ = str(PROFILE / "minescript/lab_common.py")
        conditions = (ROOT / "presets/lab-conditions.json").read_text(encoding="utf-8")
        with patch.dict(sys.modules, {"minescript": self.ms, "java": SimpleNamespace(JavaClass=java_class)}):
            with patch.object(Path, "read_text", return_value=conditions):
                spec.loader.exec_module(self.lab)

    def test_expected_disposable_world_allowed(self):
        self.assertEqual(self.lab.guard_world(), (self.world, self.version))

    def test_explicit_portable_profile_allowed_but_another_profile_rejected(self):
        portable=PROFILE.parent/'portable-profile'
        self.lab.PROFILE=portable
        self.lab.CONDITIONS['configured_profile']=str(portable)
        self.server.getWorldPath.return_value=str(portable/'saves/Lab_RestWorld_sodium_automation')
        self.assertEqual(self.lab.guard_world(),(self.world,self.version))
        self.lab.PROFILE=portable.parent/'wrong-profile'
        with self.assertRaisesRegex(RuntimeError,'profile'):self.lab.guard_world()

    def test_dimension_visits_require_explicit_whitelisted_dimension(self):
        self.world.dimension = "minecraft:the_nether"
        with self.assertRaises(RuntimeError):
            self.lab.guard_world()
        self.assertEqual(self.lab.guard_world("minecraft:the_nether"), (self.world, self.version))
        with self.assertRaisesRegex(RuntimeError, "whitelist"):
            self.lab.guard_world("mod:another_world")

    def test_other_profile_rejected_before_options(self):
        self.lab.PROFILE = PROFILE.parent / "sodium"
        with self.assertRaisesRegex(RuntimeError, "profile"):
            self.lab.apply_graphics_conditions()
        self.assertEqual(self.mc.options.mock_calls, [])

    def test_wrong_world_version_dimension_and_multiplayer_rejected_before_options(self):
        for field, value in (("version", "26.2"), ("name", "My valuable world"),
                             ("dimension", "minecraft:the_nether"), ("singleplayer", False),
                             ("path", str(PROFILE / "saves/unrelated-world"))):
            with self.subTest(field=field):
                self.version.minecraft = "26.1.2"
                self.world.name, self.world.dimension = "RestWorld_26.1", "minecraft:overworld"
                self.mc.hasSingleplayerServer.return_value = True
                self.server.getWorldPath.return_value = str(PROFILE / "saves/Lab_RestWorld_sodium_automation")
                if field == "version": self.version.minecraft = value
                elif field == "singleplayer": self.mc.hasSingleplayerServer.return_value = value
                elif field == "path": self.server.getWorldPath.return_value = value
                else: setattr(self.world, field, value)
                with self.assertRaises(RuntimeError):
                    self.lab.apply_graphics_conditions()
                self.assertEqual(self.mc.options.mock_calls, [])

    def valid_record(self):
        conditions = self.lab.CONDITIONS
        return {**copy.deepcopy(conditions["options"]), "java_major": "25",
                "heap_cap_bytes": 6144 * 1024**2, "fullscreen": True,
                "custom_fullscreen_mode_selected": False,
                "framebuffer_width": 2240, "framebuffer_height": 1400,
                "monitor_width": 2240, "monitor_height": 1400,
                "paused": False, "screen": None, "foreground": True,
                "game_fps_counter": 100, "position": conditions["start_position"],
                "effective_framerate_limit":260,"unlimited_framerate_cutoff":260,"framerate_throttle_reason":"NONE",
                "orientation": conditions["start_orientation"]}

    def test_default_monitor_resolution_passes_without_hardcoded_pixel_size(self):
        record = self.valid_record()
        self.assertEqual(self.lab.condition_issues(record, require_pose=True), [])
        record.update(framebuffer_width=2560, monitor_width=2560,
                      framebuffer_height=1600, monitor_height=1600)
        self.assertEqual(self.lab.condition_issues(record), [])

    def test_diagnostic_background_ignores_render_throttle_but_not_pause_pose_or_world(self):
        record=self.valid_record()
        record.update(foreground=False,effective_framerate_limit=10,framerate_throttle_reason='WINDOW_ICONIFIED',
                      game_fps_counter=0,pause_on_lost_focus=False,diagnostic_only=True)
        self.assertIn('effective_frame_cap',self.lab.condition_issues(record))
        self.lab.session_runtime.configure(True)
        try:
            self.assertEqual(self.lab.condition_issues(record,require_pose=True),[])
            self.assertIn('unpaused_foreground_world',self.lab.condition_issues({**record,'paused':True}))
            self.assertIn('diagnostic_pause_on_lost_focus',self.lab.condition_issues({**record,'pause_on_lost_focus':True}))
            self.assertIn('start_position',self.lab.condition_issues({**record,'position':[8,100,8]},require_pose=True))
        finally:self.lab.session_runtime.configure(False)

    def test_mismatched_conditions_rejected(self):
        for key, value, issue in (("heap_cap_bytes", 4096 * 1024**2, "heap_cap"),
                                  ("vsync", True, "vsync"),
                                  ("framebuffer_width", 1920, "native_framebuffer"),
                                  ("custom_fullscreen_mode_selected", True, "default_fullscreen_mode"),
                                  ("paused", True, "unpaused_foreground_world"),
                                  ("screen", "PauseScreen", "unpaused_foreground_world"),
                                  ("foreground", False, "unpaused_foreground_world"),
                                  ("java_major", "21", "java_major"),
                                  ("game_fps_counter", 0, "game_fps_counter")):
            with self.subTest(key=key):
                record = self.valid_record(); record[key] = value
                self.assertIn(issue, self.lab.condition_issues(record))

    def test_invalid_camera_or_position_rejected(self):
        for key, value, issue in (("position", [], "start_position"),
                                  ("position", [0.5, 105, 0.5], "start_position"),
                                  ("orientation", [0, float("nan")], "start_orientation")):
            with self.subTest(key=key, value=value):
                record = self.valid_record(); record[key] = value
                self.assertIn(issue, self.lab.condition_issues(record, require_pose=True))

    def test_java_long_process_and_heap_values_are_json_serializable(self):
        class JavaLong:
            def __str__(self): return "6442450944"
        converted = self.lab.number(JavaLong())
        self.assertEqual(json.loads(json.dumps({"heap": converted}))["heap"], 6442450944)


if __name__ == "__main__":
    unittest.main(verbosity=2)
