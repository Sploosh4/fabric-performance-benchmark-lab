"""User-started paired tooling calibration; always excludes benchmark acceptance."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import statistics
import time
from capture_headless import run
from pair_protocol import OWNER, QpcClock, paths_for, publish, read_json, validate_arm


class CounterPair:
    def __init__(self, profile, purpose="calibration"):
        self.profile = profile.resolve(strict=True)
        if self.profile.name != "sodium-automation":
            raise RuntimeError("Paired capture is restricted to sodium-automation")
        self.paths = self.run_dir = None
        self.game_pid = None
        if purpose not in ("calibration", "overhead"):
            raise ValueError("Unknown pairing purpose")
        self.purpose = purpose

    def prepare(self, game, run_dir, report):
        directory = self.profile / "minescript/lab-results"
        candidates = []
        for path in directory.glob("pair-arm-*.json"):
            try:
                arm = read_json(path)
                validate_arm(arm, path, game["pid"], time.time_ns())
                if arm.get("purpose", "calibration") != self.purpose:
                    continue
                paths = paths_for(directory, arm["nonce"])
                if not paths["claim"].exists() and not paths["done"].exists():
                    candidates.append((arm, paths))
            except (RuntimeError, ValueError, OSError):
                continue
        if len(candidates) != 1:
            command = "laboverhead" if self.purpose == "overhead" else "labpair"
            if not candidates:
                raise RuntimeError("No fresh unclaimed counter arm. Run \\" + command +
                                   " once, close chat, wait for the armed message, then start the launcher within two minutes.")
            raise RuntimeError(str(len(candidates)) + " fresh unclaimed counter arms found; refusing to choose. "
                               "Use \\jobs to inspect duplicate probes, wait for them to finish, then run \\" + command + " once.")
        self.arm, self.paths = candidates[0]
        self.run_dir, self.game_pid = run_dir, game["pid"]
        self.clock = QpcClock()
        if self.arm["qpc_frequency"] != self.clock.frequency:
            raise RuntimeError("Counter/controller QPC frequencies differ")
        publish(self.paths["claim"], {"owner": OWNER, "nonce": self.arm["nonce"],
                                     "game_pid": self.game_pid})
        report["counter_pair"] = {"nonce": self.arm["nonce"], "qpc_frequency": self.clock.frequency,
                                  "benchmark_accepted": False}
        shutil.copyfile(self.paths["arm"], run_dir / "counter-arm.json")

    def start(self):
        validate_arm(self.arm, self.paths["arm"], self.game_pid, time.time_ns())
        publish(self.paths["request"], {"owner": OWNER, "nonce": self.arm["nonce"],
                                       "game_pid": self.game_pid, "request_qpc": self.clock()})

    def stop(self):
        if self.paths is not None and not self.paths["stop"].exists():
            publish(self.paths["stop"], {"owner": OWNER, "nonce": self.arm["nonce"]})

    def collect(self):
        deadline = time.monotonic() + 10
        while not self.paths["done"].exists():
            if time.monotonic() > deadline:
                raise RuntimeError("Counter did not complete after capture")
            time.sleep(0.2)
        done = read_json(self.paths["done"])
        if done.get("owner") != OWNER or done.get("nonce") != self.arm["nonce"] or done.get("status") != "counter_pair_complete":
            raise RuntimeError("Counter pair failed or identity differs: " + str(done.get("error", "unknown")))
        shutil.copyfile(self.paths["samples"], self.run_dir / "counter-samples.jsonl")
        shutil.copyfile(self.paths["done"], self.run_dir / "counter-done.json")
        samples = [json.loads(line) for line in self.paths["samples"].read_text().splitlines()]
        samples = [row for row in samples if row.get("phase") == "sample"]
        return compare_pair(self.run_dir / "frames.csv", samples, self.clock.frequency, self.arm["nonce"])


def compare_pair(csv_path, samples, frequency, nonce):
    if frequency <= 0 or len(samples) < 15:
        raise ValueError("Missing paired clock/samples")
    if any(row.get("nonce") != nonce or row.get("condition_issues") or
           not row.get("foreground") or row.get("paused") or row.get("screen") is not None
           for row in samples):
        raise ValueError("Counter identity or run conditions differ")
    with Path(csv_path).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows or "QPCTime" not in rows[0]:
        raise ValueError("PresentMon QPC timestamps are missing")
    times = [int(row["QPCTime"]) / frequency for row in rows]
    if any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError("PresentMon QPC times are not increasing")
    clock_errors = [abs((b - a) - float(row["msBetweenPresents"]) / 1000)
                    for a, b, row in zip(times, times[1:], rows[1:])]
    if max(clock_errors) > 0.00005:
        raise ValueError("PresentMon QPC units do not match frame intervals")
    reads = [((row["fps_read_before_qpc"] + row["fps_read_after_qpc"]) / 2 / frequency, row)
             for row in samples]
    if any(row["fps_read_after_qpc"] < row["fps_read_before_qpc"] or row["game_fps_counter"] <= 0
           for _, row in reads):
        raise ValueError("Counter values or clock brackets are invalid")
    if any(not 0 < b[0] - a[0] <= 1.3 for a, b in zip(reads, reads[1:])):
        raise ValueError("Counter samples have gaps or unordered timestamps")
    if reads[0][0] > times[0] - 2 or reads[-1][0] < times[-1]:
        raise ValueError("Counter samples do not cover the frame capture")
    # The rolling FPS value may describe the preceding 1-second bucket and
    # be up to another second old. Exclude the opening two seconds. This is
    # preliminary agreement only; it is not exact per-frame alignment.
    eligible = [row for when, row in reads if times[0] + 2 <= when <= times[-1]]
    if len(eligible) < 5:
        raise ValueError("Too few interior counter readings")
    game_mean = statistics.mean(row["game_fps_counter"] for row in eligible)
    present_mean = (len(times) - 1) / (times[-1] - times[0])
    return {"status": "paired_tool_check_collected", "interior_counter_samples": len(eligible),
            "mean_rolling_game_counter": game_mean, "mean_present_event_fps": present_mean,
            "preliminary_difference_percent": 100 * (present_mean - game_mean) / game_mean,
            "maximum_qpc_interval_error_seconds": max(clock_errors),
            "fps_comparison_scope": "Approximate rolling-counter agreement; no exact bucket alignment",
            "calibration_complete": False, "capture_overhead": "untested", "benchmark_accepted": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--presentmon", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--results", type=Path, required=True)
    args = parser.parse_args()
    args.warmup, args.check_only = 15, False
    pair = CounterPair(args.profile)
    code = run(args, pair=pair)
    result = {"status": "rejected", "benchmark_accepted": False}
    if code == 0:
        try:
            result = pair.collect()
            print("Paired frame/counter files collected. Calibration review and overhead tests remain pending.")
        except Exception as error:
            result["reason"] = str(error)
            print("PAIR REJECTED: " + str(error))
            code = 2
    if pair.run_dir is not None:
        publish(pair.run_dir / "pair-result.json", result)
    raise SystemExit(code)
