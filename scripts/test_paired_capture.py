"""Synthetic clock/protocol/cleanup checks; no live ETW or game execution."""
import csv
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import capture_headless
from capture_paired import compare_pair
from pair_protocol import OWNER, publish, validate_arm

NONCE = "a" * 32


class PairSafety(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="paired-capture-fixture-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def arm(self):
        return {"owner": OWNER, "nonce": NONCE, "game_pid": 1234,
                "created_unix_ns": 1000, "expires_unix_ns": 1000 + 120 * 10**9,
                "initial_issues": [], "benchmark_accepted": False}

    def test_stale_wrong_process_and_wrong_nonce_arms_rejected(self):
        path = self.directory / ("pair-arm-" + NONCE + ".json")
        validate_arm(self.arm(), path, 1234, 2000)
        for arm, pid, now in ((self.arm(), 4321, 2000), (self.arm(), 1234, 1000 + 120 * 10**9),
                              ({**self.arm(), "nonce": "../escape"}, 1234, 2000)):
            with self.assertRaises(RuntimeError): validate_arm(arm, path, pid, now)

    def test_atomic_publication_preserves_existing_file(self):
        path = self.directory / "owned-request.json"
        publish(path, {"first": True})
        with self.assertRaises(FileExistsError): publish(path, {"second": True})
        self.assertEqual(json.loads(path.read_text()), {"first": True})
        self.assertEqual(list(self.directory.glob("*.tmp")), [])

    def fixtures(self):
        path = self.directory / "frames.csv"
        frequency = 10000
        with path.open("w", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=["QPCTime", "msBetweenPresents"])
            writer.writeheader()
            writer.writerows({"QPCTime": str(1000000 + i * 100), "msBetweenPresents": "10"}
                             for i in range(1001))
        samples = [{"nonce": NONCE, "condition_issues": [], "foreground": True,
                    "paused": False, "screen": None, "game_fps_counter": 100,
                    "fps_read_before_qpc": (97 + i) * frequency,
                    "fps_read_after_qpc": (97 + i) * frequency + 10} for i in range(20)]
        return path, samples, frequency

    def test_paired_fixture_is_tooling_only(self):
        path, samples, frequency = self.fixtures()
        report = compare_pair(path, samples, frequency, NONCE)
        self.assertAlmostEqual(report["preliminary_difference_percent"], 0)
        self.assertFalse(report["benchmark_accepted"])
        self.assertFalse(report["calibration_complete"])

    def test_qpc_units_counter_gaps_and_failed_conditions_rejected(self):
        for change in ("units", "gap", "pose", "identity"):
            with self.subTest(change=change):
                path, samples, frequency = self.fixtures()
                if change == "units": frequency *= 1000
                elif change == "gap": samples[5]["fps_read_after_qpc"] += frequency * 4
                elif change == "pose": samples[5]["condition_issues"] = ["position"]
                elif change == "identity": samples[5]["nonce"] = "b" * 32
                with self.assertRaises(ValueError): compare_pair(path, samples, frequency, NONCE)

    def test_counter_without_frame_window_coverage_rejected(self):
        path, samples, frequency = self.fixtures()
        for row in samples:
            row["fps_read_before_qpc"] += 5 * frequency
            row["fps_read_after_qpc"] += 5 * frequency
        with self.assertRaisesRegex(ValueError, "cover"):
            compare_pair(path, samples, frequency, NONCE)

    def mocked_run(self, fail_start=False, duration=10):
        tool = self.directory / "fake-console.exe"
        tool.write_bytes(b"fixture tool")
        args = SimpleNamespace(results=self.directory / "results", profile=self.directory,
                               presentmon=tool, expected_sha256=hashlib.sha256(tool.read_bytes()).hexdigest(),
                               warmup=0, check_only=False, duration=duration)
        events = []
        pair = Mock()
        pair.end_on_action=False
        pair.requires_frame_stream_ready=False
        pair.prepare.side_effect = lambda *args: events.append("prepare")
        def start():
            events.append("start")
            if fail_start: raise RuntimeError("pair start failed")
        pair.start.side_effect = start
        pair.stop.side_effect = lambda: events.append("stop")
        api = Mock()
        api.IsUserAnAdmin.return_value = True
        monitor = Mock()
        monitor.sample.return_value = {"ac_connected": True, "original_game_alive": True,
                                       "minecraft_foreground": True}
        child = Mock()
        child.poll.return_value, child.returncode = 0, 0
        def popen(command, **kwargs):
            events.append("capture")
            self.assertIn("--qpc_time", command)
            self.assertEqual(command[command.index("--timed") + 1], str(duration))
            self.assertIn('--output_stdout',command)
            kwargs['stdout'].write(b'fixture csv');kwargs['stdout'].flush()
            return child
        with patch.object(capture_headless.C, "WinDLL", return_value=api,create=True), \
             patch.object(capture_headless.subprocess,"CREATE_NO_WINDOW",0,create=True), \
             patch.object(capture_headless, "Monitor", return_value=monitor), \
             patch.object(capture_headless, "process_inventory", return_value={"other_capture_pids": [],
                 "chrome_process_count": 0, "service_running": False, "games": [{"pid": 1234}]}), \
             patch.object(capture_headless.subprocess, "Popen", side_effect=popen), \
             patch.object(capture_headless, "check_csv", return_value={"csv_quality_passed": True}) as quality:
            code = capture_headless.run(args, pair=pair)
        monitor.close.assert_called_once()
        if not fail_start:
            self.assertEqual(quality.call_args.kwargs["seconds"], duration)
        return code, events

    def test_user_controller_pairs_before_capture_and_stops_afterward(self):
        code, events = self.mocked_run()
        self.assertEqual(code, 0)
        self.assertEqual(events, ["prepare", "start", "capture", "stop"])

    def test_pair_start_failure_stops_without_launching_capture(self):
        code, events = self.mocked_run(fail_start=True)
        self.assertEqual(code, 2)
        self.assertEqual(events, ["prepare", "start", "stop"])

    def test_extended_capture_uses_matching_cli_and_quality_duration(self):
        code, events = self.mocked_run(duration=60)
        self.assertEqual(code, 0)
        self.assertEqual(events[-1], "stop")


if __name__ == "__main__":
    unittest.main(verbosity=2)
