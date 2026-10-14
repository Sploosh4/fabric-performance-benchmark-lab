"""User-started eight-trace incremental logging overhead check, no desktop input."""
import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import shutil
import statistics
import time
import uuid
from capture_headless import run
from capture_paired import CounterPair
from pair_protocol import OWNER, OVERHEAD_ORDER, phase_paths, publish, read_json, validate_phase


def wait_file(path, timeout=10):
    deadline = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() > deadline:
            raise RuntimeError("Overhead phase acknowledgement timed out")
        time.sleep(0.1)
    return read_json(path)


class PhaseCapture:
    def __init__(self, pair, phase):
        self.pair, self.phase = pair, phase
        self.files = self.run_dir = None

    def prepare(self, game, run_dir, report):
        self.run_dir = run_dir
        if self.pair.paths is None:
            self.pair.prepare(game, run_dir, report)
        elif game["pid"] != self.pair.game_pid:
            raise RuntimeError("Minecraft process changed during overhead suite")
        self.files = phase_paths(self.pair.profile / "minescript/lab-results", self.pair.arm["nonce"], self.phase)
        self.identity = {"owner": OWNER, "nonce": self.pair.arm["nonce"], "phase": self.phase,
                         "game_pid": self.pair.game_pid, "counter_enabled": OVERHEAD_ORDER[self.phase],
                         "benchmark_accepted": False}
        report["overhead_phase"] = self.identity
        shutil.copyfile(self.pair.paths["arm"], run_dir / "overhead-arm.json")

    def start(self):
        publish(self.files["request"], self.identity)
        ack = wait_file(self.files["ack"])
        validate_phase(ack, self.identity["nonce"], self.phase, self.pair.game_pid)
        if ack.get("status") != "ready":
            raise RuntimeError("Game-side overhead phase is not ready")
        shutil.copyfile(self.files["ack"], self.run_dir / "overhead-start.json")

    def stop(self):
        if self.files is not None and not self.files["stop"].exists():
            publish(self.files["stop"], self.identity)

    def health(self):
        if self.pair.paths is None or not self.pair.paths["done"].exists():
            return
        done = read_json(self.pair.paths["done"])
        if done.get("owner") != OWNER or done.get("nonce") != self.pair.arm["nonce"]:
            raise RuntimeError("Game-side overhead completion identity differs")
        if done.get("status") != "overhead_probe_complete":
            raise RuntimeError("Game-side overhead probe failed: " + str(done.get("error", "unknown")))

    def finish(self):
        done = wait_file(self.files["done"])
        validate_phase(done, self.identity["nonce"], self.phase, self.pair.game_pid)
        if done.get("status") != "phase_complete":
            raise RuntimeError("Overhead phase did not complete")
        count = done.get("counter_samples")
        if type(count) is not int or (OVERHEAD_ORDER[self.phase] and count < 20) or (not OVERHEAD_ORDER[self.phase] and count != 0):
            raise RuntimeError("Counter logging did not match the phase mode")
        shutil.copyfile(self.files["done"], self.run_dir / "overhead-done.json")
        result = read_json(self.run_dir / "result.json")
        streams = result.get("csv_validation", {}).get("streams", [])
        if result.get("status") != "tool_check_passed" or len(streams) != 1:
            raise RuntimeError("Frame trace failed quality/stream checks")
        return {"phase": self.phase, "counter_enabled": OVERHEAD_ORDER[self.phase],
                "run_directory": self.run_dir.name, "average_presented_fps": result["average_presented_fps"],
                "frame_sha256": result["csv_sha256"], "stream": streams[0],
                "counter_samples": done["counter_samples"], "benchmark_accepted": False}


def summarize(phases):
    if len(phases) != len(OVERHEAD_ORDER) or any(p.get("phase") != i or p.get("counter_enabled") is not enabled
                                                for i, (p, enabled) in enumerate(zip(phases, OVERHEAD_ORDER))):
        raise ValueError("Incomplete or incorrectly ordered overhead suite")
    streams = {(p["stream"]["runtime"], p["stream"]["swap_chain"]) for p in phases}
    if len(streams) != 1:
        raise ValueError("Presentation stream changed during overhead suite")
    if any(not math.isfinite(p["average_presented_fps"]) or p["average_presented_fps"] <= 0 for p in phases):
        raise ValueError("Invalid overhead phase FPS")
    differences = []
    for index in range(0, len(phases), 2):
        left, right = phases[index:index + 2]
        active, idle = (left, right) if left["counter_enabled"] else (right, left)
        differences.append(100 * (active["average_presented_fps"] / idle["average_presented_fps"] - 1))
    return {"status": "overhead_tooling_batch_collected", "paired_counter_logging_changes_percent": differences,
            "median_counter_logging_change_percent": statistics.median(differences),
            "scope": "Incremental active counter/pose logging versus idle probe; PresentMon runs in both",
            "presentmon_capture_overhead": "untested",
            "note": "Four short pairs quantify observed differences, not statistical significance or a mod gain",
            "benchmark_accepted": False}


def main(args):
    suite = args.results.resolve() / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
    suite.mkdir(parents=True, exist_ok=False)
    report = {"status": "rejected", "benchmark_accepted": False, "phases": [],
              "order": list(OVERHEAD_ORDER), "scope": "Incremental counter logging tooling check"}
    pair = CounterPair(args.profile, purpose="overhead")
    code = 2
    try:
        args.results = suite / "runs"
        args.warmup, args.check_only = 15, False
        for phase, enabled in enumerate(OVERHEAD_ORDER):
            print("Overhead phase " + str(phase + 1) + "/8: counter " + ("logging" if enabled else "idle"), flush=True)
            hook = PhaseCapture(pair, phase)
            if run(args, pair=hook) != 0:
                detail = "No child result was produced; inspect the controller output"
                if hook.run_dir is not None and (hook.run_dir / "result.json").exists():
                    detail = read_json(hook.run_dir / "result.json").get("reason", "Capture phase was rejected")
                    report["failed_run_directory"] = hook.run_dir.name
                report["failed_phase"] = phase
                raise RuntimeError("Overhead phase " + str(phase + 1) + "/8 failed: " + detail)
            report["phases"].append(hook.finish())
            publish(suite / ("phase-" + str(phase) + ".json"), report["phases"][-1])
        done = wait_file(pair.paths["done"])
        if done.get("owner") != OWNER or done.get("nonce") != pair.arm["nonce"] or done.get("status") != "overhead_probe_complete":
            raise RuntimeError("Game-side overhead batch failed")
        shutil.copyfile(pair.paths["samples"], suite / "game-samples.jsonl")
        shutil.copyfile(pair.paths["done"], suite / "game-done.json")
        report.update(summarize(report["phases"]))
        code = 0
        print("All eight overhead tooling traces collected. No benchmark accepted.", flush=True)
    except Exception as error:
        report["reason"] = str(error)
        print("OVERHEAD REJECTED: " + str(error), flush=True)
    finally:
        try:
            pair.stop()
        except Exception as stop_error:
            report["probe_stop_error"] = str(stop_error)
            report["status"] = "rejected"
            code = 2
        publish(suite / "overhead-result.json", report)
        print("Overhead results: " + str(suite), flush=True)
    return code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--presentmon", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--results", type=Path, required=True)
    raise SystemExit(main(parser.parse_args()))
