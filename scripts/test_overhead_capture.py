"""Offline suite-order, phase identity and stop fixtures; no live capture."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from capture_overhead import PhaseCapture, summarize, main
from capture_paired import CounterPair
from pair_protocol import OWNER, OVERHEAD_ORDER, paths_for, phase_paths, publish, read_json, validate_phase, reject_duplicate_overhead_jobs

NONCE = "a" * 32


class OverheadSafety(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="overhead-capture-fixture-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def phases(self):
        return [{"phase": i, "counter_enabled": enabled,
                 "average_presented_fps": 90 if enabled else 100,
                 "stream": {"runtime": "DXGI", "swap_chain": "0xABC"}}
                for i, enabled in enumerate(OVERHEAD_ORDER)]

    def test_order_is_balanced_in_both_directions(self):
        pairs = list(zip(OVERHEAD_ORDER[::2], OVERHEAD_ORDER[1::2]))
        self.assertEqual(pairs.count((False, True)), 2)
        self.assertEqual(pairs.count((True, False)), 2)
        result = summarize(self.phases())
        self.assertAlmostEqual(result["median_counter_logging_change_percent"], -10)
        self.assertFalse(result["benchmark_accepted"])
        self.assertEqual(result["presentmon_capture_overhead"], "untested")

    def test_incomplete_reordered_and_changed_stream_rejected(self):
        for mode in ("incomplete", "order", "stream", "nan"):
            phases = self.phases()
            if mode == "incomplete": phases.pop()
            elif mode == "order": phases[0]["counter_enabled"] = True
            elif mode == "stream": phases[4]["stream"]["runtime"] = "Other"
            else: phases[4]["average_presented_fps"] = float("nan")
            with self.subTest(mode=mode), self.assertRaises(ValueError): summarize(phases)

    def test_phase_paths_and_identity_reject_wrong_phase_mode_and_pid(self):
        with self.assertRaises(RuntimeError): phase_paths(self.directory, "../escape", 0)
        with self.assertRaises(RuntimeError): phase_paths(self.directory, NONCE, 8)
        value = {"owner": OWNER, "nonce": NONCE, "phase": 0, "counter_enabled": False, "game_pid": 1234}
        validate_phase(value, NONCE, 0, 1234)
        for change in ({"phase": 1}, {"counter_enabled": True}, {"game_pid": 4321}):
            with self.assertRaises(RuntimeError): validate_phase({**value, **change}, NONCE, 0, 1234)

    def test_phase_stop_is_published_after_start_failure(self):
        pair = Mock()
        hook = PhaseCapture(pair, 0)
        hook.files = phase_paths(self.directory, NONCE, 0)
        hook.identity = {"owner": OWNER, "nonce": NONCE, "phase": 0, "counter_enabled": False,
                         "game_pid": 1234, "benchmark_accepted": False}
        with patch("capture_overhead.wait_file", side_effect=RuntimeError("ack failed")):
            with self.assertRaises(RuntimeError): hook.start()
        hook.stop()
        self.assertEqual(read_json(hook.files["stop"]), hook.identity)
        hook.stop()  # No overwrite/republication on repeated cleanup.

    def test_game_process_cannot_change_between_phases(self):
        pair = Mock()
        pair.paths, pair.game_pid = {"claimed": True}, 1234
        hook = PhaseCapture(pair, 1)
        with self.assertRaisesRegex(RuntimeError, "process changed"):
            hook.prepare({"pid": 4321}, self.directory, {})

    def test_duplicate_probe_is_refused_without_stopping_jobs(self):
        own = SimpleNamespace(self=True, command=["laboverhead"], job_id=8)
        unrelated = SimpleNamespace(self=False, command=["labpose"], job_id=9)
        reject_duplicate_overhead_jobs([own, unrelated])
        for name in ("laboverhead", "laboverhead.py", r"C:\fixture\laboverhead.py", r"\laboverhead"):
            duplicate = SimpleNamespace(self=False, command=[name], job_id=7)
            with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, r"already running.*job 7"):
                reject_duplicate_overhead_jobs([own, duplicate])

    def test_probe_failure_is_detected_before_another_capture(self):
        paths = paths_for(self.directory, NONCE)
        pair = SimpleNamespace(paths=paths, arm={"nonce": NONCE})
        hook = PhaseCapture(pair, 1)
        hook.health()
        publish(paths["done"], {"owner": OWNER, "nonce": NONCE, "status": "failed", "error": "focus lost"})
        with self.assertRaisesRegex(RuntimeError, "probe failed: focus lost"):
            hook.health()

    def test_duplicate_arms_are_reported_and_neither_is_claimed(self):
        profile = self.directory / "sodium-automation"
        directory = profile / "minescript/lab-results"
        directory.mkdir(parents=True)
        for nonce in (NONCE, "b" * 32):
            publish(paths_for(directory, nonce)["arm"], {"owner": OWNER, "nonce": nonce,
                "purpose": "overhead", "game_pid": 1234, "created_unix_ns": 1000,
                "expires_unix_ns": 1000 + 120 * 10**9, "initial_issues": [], "benchmark_accepted": False})
        with patch("capture_paired.time.time_ns", return_value=2000):
            with self.assertRaisesRegex(RuntimeError, "2 fresh unclaimed counter arms"):
                CounterPair(profile, purpose="overhead").prepare({"pid": 1234}, self.directory, {})
        self.assertEqual(list(directory.glob("pair-claim-*.json")), [])

    def test_calibration_launcher_does_not_claim_an_overhead_arm(self):
        profile = self.directory / "sodium-automation"
        directory = profile / "minescript/lab-results"
        directory.mkdir(parents=True)
        arm = {"owner": OWNER, "nonce": NONCE, "purpose": "overhead", "game_pid": 1234,
               "created_unix_ns": 1000, "expires_unix_ns": 1000 + 120 * 10**9,
               "initial_issues": [], "benchmark_accepted": False, "qpc_frequency": 10000}
        publish(paths_for(directory, NONCE)["arm"], arm)
        with patch("capture_paired.time.time_ns", return_value=2000):
            with self.assertRaisesRegex(RuntimeError, "labpair"):
                CounterPair(profile).prepare({"pid": 1234}, self.directory, {})
        self.assertFalse(paths_for(directory, NONCE)["claim"].exists())

    def fake_suite(self, fail_phase=None):
        profile = self.directory / "sodium-automation"
        directory = profile / "minescript/lab-results"
        directory.mkdir(parents=True)
        paths = paths_for(directory, NONCE)
        arm = {"owner": OWNER, "nonce": NONCE, "purpose": "overhead", "game_pid": 1234,
               "created_unix_ns": 1000, "expires_unix_ns": 1000 + 120 * 10**9,
               "initial_issues": [], "benchmark_accepted": False, "qpc_frequency": 10000}
        publish(paths["arm"], arm)
        paths["samples"].write_text("fixture-only\n")
        visited = []
        def fake_run(args, pair):
            phase = pair.phase
            visited.append(phase)
            target = args.results / ("fixture-" + str(phase))
            target.mkdir(parents=True)
            pair.prepare({"pid": 1234}, target, {})
            pair.start()
            if phase == fail_phase:
                publish(target / "result.json", {"status": "rejected", "reason": "fixture focus lost"})
                pair.stop()
                return 2
            publish(target / "result.json", {"status": "tool_check_passed", "csv_sha256": "fixture",
                "average_presented_fps": 99 if OVERHEAD_ORDER[phase] else 100,
                "csv_validation": {"streams": [{"runtime": "DXGI", "swap_chain": "0xABC"}]}})
            pair.stop()
            return 0
        def fake_wait(path):
            if path == paths["done"]:
                value = {"owner": OWNER, "nonce": NONCE, "status": "overhead_probe_complete"}
            else:
                request = path.with_name(path.name.replace("-ack.json", "-request.json").replace("-done.json", "-request.json"))
                value = read_json(request)
                value.update(status="ready" if path.name.endswith("-ack.json") else "phase_complete",
                             counter_samples=25 if value["counter_enabled"] else 0)
            publish(path, value)
            return value
        args = SimpleNamespace(profile=profile, results=self.directory / "suites", presentmon=Path("unused"),
                               expected_sha256="unused")
        with patch("capture_overhead.run", side_effect=fake_run), \
             patch("capture_overhead.wait_file", side_effect=fake_wait), \
             patch("capture_paired.QpcClock", return_value=SimpleNamespace(frequency=10000)), \
             patch("capture_paired.time.time_ns", return_value=2000):
            code = main(args)
        result_path = next((self.directory / "suites").glob("*/overhead-result.json"))
        return code, visited, read_json(result_path), paths

    def test_whole_suite_collects_eight_phases_and_stops_probe(self):
        code, visited, result, paths = self.fake_suite()
        self.assertEqual(code, 0)
        self.assertEqual(visited, list(range(8)))
        self.assertEqual(len(result["phases"]), 8)
        self.assertAlmostEqual(result["median_counter_logging_change_percent"], -1)
        self.assertFalse(result["benchmark_accepted"])
        self.assertTrue(paths["stop"].exists())

    def test_mid_suite_failure_aborts_and_preserves_partial_report(self):
        code, visited, result, paths = self.fake_suite(fail_phase=3)
        self.assertEqual(code, 2)
        self.assertEqual(visited, [0, 1, 2, 3])
        self.assertEqual(len(result["phases"]), 3)
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["failed_phase"], 3)
        self.assertIn("phase 4/8 failed: fixture focus lost", result["reason"])
        self.assertFalse(result["benchmark_accepted"])
        self.assertTrue(paths["stop"].exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
