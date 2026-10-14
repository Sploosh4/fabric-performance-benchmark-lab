"""Synthetic CSV quality fixtures; never live performance evidence."""
import csv
import tempfile
import unittest
from pathlib import Path

from validate_capture import REQUIRED, validate_csv


class CaptureQuality(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="modpack-capture-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "fixture.csv"
        self.rows = [{"Application": "javaw.exe", "ProcessID": "1234", "SwapChainAddress": "0xABC",
                      "PresentRuntime": "Other", "TimeInMs": str(i * 10),
                      "MsBetweenPresents": "NA" if i == 0 else "10"} for i in range(501)]

    def check(self):
        with self.path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=sorted(REQUIRED))
            writer.writeheader()
            writer.writerows(self.rows)
        return validate_csv(self.path, pid=1234, application="javaw.exe", duration_seconds=5,
                            tolerance_seconds=0.1)

    def test_valid_fixture_quality_not_benchmark(self):
        report = self.check()
        self.assertTrue(report["quality_checks_passed"])
        self.assertFalse(report["benchmark_accepted"])
        self.assertEqual(report["metrics"]["average_presented_fps"], 100)
        self.assertEqual(report["metrics"]["one_percent_low_fps"], 100)

    def test_utf16_transport_preserves_the_same_quality_metrics(self):
        utf8=self.check()
        content=self.path.read_text(encoding="utf-8")
        self.path.write_text(content,encoding="utf-16")
        utf16=validate_csv(self.path,pid=1234,application="javaw.exe",duration_seconds=5,tolerance_seconds=.1)
        self.assertEqual(utf8,utf16)

    def test_wrong_pid_and_application_rejected(self):
        for column, value in (("ProcessID", "4321"), ("Application", "chrome.exe")):
            original = self.rows[100][column]
            self.rows[100][column] = value
            self.assertFalse(self.check()["quality_checks_passed"])
            self.rows[100][column] = original

    def test_header_only_rejected(self):
        self.rows = []
        self.assertFalse(self.check()["quality_checks_passed"])

    def test_short_capture_rejected(self):
        self.rows = self.rows[:100]
        self.assertFalse(self.check()["quality_checks_passed"])

    def test_mixed_stream_rejected(self):
        self.rows[100]["SwapChainAddress"] = "0xDEF"
        self.assertFalse(self.check()["quality_checks_passed"])

    def test_nonfinite_and_nonpositive_interval_rejected(self):
        for value in ("NA", "NaN", "inf", "0", "-1"):
            self.rows[100]["MsBetweenPresents"] = value
            self.assertFalse(self.check()["quality_checks_passed"])

    def test_duplicate_timestamp_rejected(self):
        self.rows[100]["TimeInMs"] = self.rows[99]["TimeInMs"]
        self.assertFalse(self.check()["quality_checks_passed"])

    def test_inconsistent_interval_rejected(self):
        self.rows[100]["MsBetweenPresents"] = "9"
        self.assertFalse(self.check()["quality_checks_passed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
