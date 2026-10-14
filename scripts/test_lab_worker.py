"""Worker selection checks only; never launches an elevated process or game."""
from pathlib import Path
import tempfile
import time
import unittest
from pair_protocol import OWNER as PAIR_OWNER, paths_for as pair_paths, publish
from session_protocol import OWNER, paths_for
from launch_lab_worker import pending

SESSION = "a" * 32
OVERHEAD = "b" * 32


class WorkerSelection(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lab-worker-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        now = time.time_ns()
        self.session = {"owner": OWNER, "nonce": SESSION, "game_pid": 1234, "benchmark_accepted": False,
            "created_unix_ns": now, "expires_unix_ns": now + 900 * 10**9, "repeats": 3, "initial_issues": []}
        self.overhead = {"owner": PAIR_OWNER, "nonce": OVERHEAD, "game_pid": 1234, "benchmark_accepted": False,
            "created_unix_ns": now, "expires_unix_ns": now + 120 * 10**9, "purpose": "overhead", "initial_issues": []}

    def test_explicit_sessions_and_overhead_are_the_only_supported_jobs(self):
        publish(paths_for(self.directory, SESSION)["arm"], self.session)
        self.assertEqual(pending(self.directory, 1234, set()), [("session", SESSION)])
        publish(pair_paths(self.directory, OVERHEAD)["arm"], {**self.overhead, "purpose": "calibration"})
        self.assertEqual(pending(self.directory, 1234, set()), [("session", SESSION)])

    def test_ambiguous_arms_are_returned_without_claiming_anything(self):
        publish(paths_for(self.directory, SESSION)["arm"], self.session)
        publish(pair_paths(self.directory, OVERHEAD)["arm"], self.overhead)
        self.assertEqual(len(pending(self.directory, 1234, set())), 2)
        self.assertEqual(list(self.directory.glob("*claim*")), [])

    def test_attempted_claimed_and_finished_arms_are_not_retried(self):
        publish(paths_for(self.directory, SESSION)["arm"], self.session)
        self.assertEqual(pending(self.directory, 1234, {SESSION}), [])
        publish(paths_for(self.directory, SESSION)["claim"], {})
        self.assertEqual(pending(self.directory, 1234, set()), [])
        publish(pair_paths(self.directory, OVERHEAD)["arm"], self.overhead)
        publish(pair_paths(self.directory, OVERHEAD)["done"], {})
        self.assertEqual(pending(self.directory, 1234, set()), [])

    def test_another_minecraft_process_is_ignored(self):
        publish(paths_for(self.directory, SESSION)["arm"], self.session)
        publish(pair_paths(self.directory, OVERHEAD)["arm"], self.overhead)
        self.assertEqual(pending(self.directory, 777, set()), [])


if __name__ == "__main__":
    unittest.main()
