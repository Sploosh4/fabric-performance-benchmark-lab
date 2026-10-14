"""Validate PresentMon v1 frame evidence without claiming world/route calibration."""
import argparse
import csv
import json
import math
import statistics
from pathlib import Path
from frame_csv import csv_encoding

REQUIRED = {"Application", "ProcessID", "SwapChainAddress", "PresentRuntime", "TimeInMs", "MsBetweenPresents"}


def finite_number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def percentile(values, fraction):
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    return ordered[lower] + (ordered[math.ceil(position)] - ordered[lower]) * (position - lower)


def validate_csv(path, *, pid, application, duration_seconds, swap_chain=None,
                 tolerance_seconds=2.0, minimum_intervals=30):
    reasons = []
    report = {"quality_checks_passed": False, "benchmark_accepted": False,
              "reasons": reasons, "primary_metric": "presented-frame intervals (MsBetweenPresents)",
              "missing_validation": ["verified Minecraft process identity/lifetime", "world/scenario success",
                                     "foreground telemetry", "Minecraft/OpenGL calibration", "capture overhead"]}
    if duration_seconds <= 0 or tolerance_seconds < 0 or minimum_intervals < 2:
        raise ValueError("Invalid duration, tolerance or sample policy")
    with Path(path).open(encoding=csv_encoding(path), newline="") as stream:
        reader = csv.DictReader(stream)
        if not REQUIRED.issubset(reader.fieldnames or []):
            reasons.append("Required pinned v1 columns are missing")
            return report
        rows = list(reader)
    if not rows:
        reasons.append("CSV contains no frames")
        return report
    streams = {}
    for row in rows:
        try:
            correct_pid = int(row["ProcessID"]) == pid
        except (ValueError, TypeError):
            correct_pid = False
        if not correct_pid or row["Application"].casefold() != application.casefold():
            reasons.append("CSV contains an unexpected process/application")
            return report
        key = (row["SwapChainAddress"], row["PresentRuntime"])
        if not all(key):
            reasons.append("CSV is missing presentation-stream identity")
            return report
        streams.setdefault(key, []).append(row)
    report["streams"] = [{"swap_chain": key[0], "runtime": key[1], "frames": len(value)}
                         for key, value in streams.items()]
    # Do not choose the fastest/largest stream after looking at its FPS.
    if len(streams) != 1:
        reasons.append("Mixed presentation streams require a calibrated filter; rejected")
        return report
    key, selected = next(iter(streams.items()))
    if swap_chain is not None and key[0].casefold() != swap_chain.casefold():
        reasons.append("Presentation stream differs from the pinned calibration")
        return report
    times = [finite_number(row["TimeInMs"]) for row in selected]
    if any(value is None or value < 0 for value in times):
        reasons.append("Frame timestamps are missing, non-finite or negative")
        return report
    if any(right <= left for left, right in zip(times, times[1:])):
        reasons.append("Duplicate or non-increasing frame timestamps")
        return report
    # Discard the first interval even when positive: its earlier endpoint may
    # predate capture. Preserve every subsequent stall rather than trimming it.
    intervals = [finite_number(row["MsBetweenPresents"]) for row in selected[1:]]
    if any(value is None or value <= 0 for value in intervals):
        reasons.append("Frame intervals are missing, non-finite or non-positive")
        return report
    if len(intervals) < minimum_intervals:
        reasons.append("Insufficient valid frame intervals")
        return report
    elapsed = (times[-1] - times[0]) / 1000
    report["observed_seconds"] = elapsed
    if abs(elapsed - duration_seconds) > tolerance_seconds:
        reasons.append("Observed frame duration differs from the requested capture window")
    deltas = [right - left for left, right in zip(times, times[1:])]
    if any(abs(delta - interval) > max(0.05, delta * 0.005)
           for delta, interval in zip(deltas, intervals)):
        reasons.append("Present intervals do not agree with frame timestamps")
    if reasons:
        return report
    slowest = sorted(intervals, reverse=True)[:max(1, math.ceil(len(intervals) * 0.01))]
    report["metrics"] = {"interval_count": len(intervals), "average_presented_fps": 1000 / statistics.mean(intervals),
                         "p50_ms": percentile(intervals, 0.50), "p95_ms": percentile(intervals, 0.95),
                         "p99_ms": percentile(intervals, 0.99),
                         "one_percent_low_fps": 1000 / statistics.mean(slowest),
                         "stutters_over_50ms": sum(value > 50 for value in intervals),
                         "tail_sample_warning": "few samples for p99" if len(intervals) < 500 else None}
    report["quality_checks_passed"] = True
    report["notes"] = ["Displayed FPS and CPU/GPU latency are not inferred from presented intervals",
                       "Blank/NA/zero latency fields are not interpreted as accurate measurements",
                       "CSV quality alone does not accept a benchmark run"]
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--application", choices=("java.exe", "javaw.exe"), required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--swap-chain")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = validate_csv(args.csv, pid=args.pid, application=args.application,
                          duration_seconds=args.duration, swap_chain=args.swap_chain)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["quality_checks_passed"] else 2)


if __name__ == "__main__":
    main()
