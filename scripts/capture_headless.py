"""User-started, finite PresentMon tool check. Never controls Minecraft or accepts a benchmark."""
import argparse
import csv
import ctypes as C
from ctypes import wintypes as W
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
import os
import re
from pathlib import Path
import statistics
import subprocess
import tempfile
import time
import uuid
from validate_capture import validate_csv
from frame_csv import csv_encoding,csv_prefix


def first_frame_ready(path,pid):
    """Readiness evidence only, never a performance convergence check."""
    if not Path(path).exists():return False
    prefix=csv_prefix(path)
    # A writer may have flushed only part of its next row.
    lines=prefix.splitlines()
    if prefix and not prefix.endswith(("\n", "\r")):lines=lines[:-1]
    if len(lines)<2:return False
    reader=csv.DictReader(lines[:2])
    row=next(reader,None)
    if not row or not row.get("QPCTime") or not row.get("ProcessID"):return False
    try:
        if row.get("Application","").lower() not in ("java.exe","javaw.exe") or int(row["ProcessID"])!=pid:
            raise ValueError("First observed frame belongs to another process")
        return int(row["QPCTime"])>0
    except TypeError:return False


def presentmon_command(tool, pid, duration, session_name, qpc=False):
    """Stream CSV to our inherited, readable handle rather than a locked exporter file."""
    command = [str(tool), "--process_id", str(pid), "--timed", str(duration),
               "--terminate_after_timed", "--terminate_on_proc_exit", "--v1_metrics",
               "--output_stdout", "--no_console_stats", "--session_name", session_name]
    if qpc:command.append("--qpc_time")
    return command


def stop_owned_trace(tool, session_name):
    """Gracefully drain only this controller's uniquely named trace session."""
    if not re.fullmatch(r"Modpack_[a-f0-9]{32}", session_name):
        raise RuntimeError("Refusing to stop an unowned trace session")
    result = subprocess.run([str(tool), "--terminate_existing_session", "--session_name", session_name],
                            capture_output=True, text=True, timeout=10,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError("Owned trace did not stop cleanly: code " + str(result.returncode))
    return result.returncode


def verify_route_capture(path, action):
    """Require a flushed complete frame beyond the verified action boundary."""
    with Path(path).open(encoding=csv_encoding(path), newline="") as stream:
        rows = list(csv.DictReader(stream))
    boundary = action["completed_qpc"]
    if not rows or not int(rows[0]["QPCTime"]) < boundary < int(rows[-1]["QPCTime"]):
        raise ValueError("Capture did not retain frames before and after route completion")


def check_csv(path, pid, seconds=10):
    with Path(path).open(encoding=csv_encoding(path), newline="") as stream:
        reader = csv.DictReader(stream)
        console26 = {"Application", "ProcessID", "SwapChainAddress", "Runtime",
                     "TimeInSeconds", "msBetweenPresents"}
        if console26.issubset(reader.fieldnames or []):
            rows = list(reader)
            if not rows or rows[0]["Application"].lower() not in {"java.exe", "javaw.exe"}:
                raise ValueError("Wrong application or empty console capture")
            # The installed 2.6.0 --v1_metrics exporter uses seconds, Runtime
            # and a lowercase ms prefix. Normalize explicitly; keep raw bytes.
            fields = ["Application", "ProcessID", "SwapChainAddress", "PresentRuntime",
                      "TimeInMs", "MsBetweenPresents"]
            # Completed evidence may be mounted read-only. Normalize a temporary
            # copy in the system scratch directory, never beside the raw capture.
            with tempfile.TemporaryDirectory(prefix="normalize-console26-") as temp:
                normalized = Path(temp) / "normalized.csv"
                with normalized.open("w", encoding="utf-8", newline="") as output:
                    writer = csv.DictWriter(output, fieldnames=fields); writer.writeheader()
                    for row in rows:
                        writer.writerow({"Application": row["Application"], "ProcessID": row["ProcessID"],
                            "SwapChainAddress": row["SwapChainAddress"], "PresentRuntime": row["Runtime"],
                            "TimeInMs": str(Decimal(row["TimeInSeconds"]) * 1000),
                            "MsBetweenPresents": row["msBetweenPresents"]})
                quality = validate_csv(normalized, pid=pid, application=rows[0]["Application"],
                                       duration_seconds=seconds, tolerance_seconds=1)
            if not quality["quality_checks_passed"]:
                raise ValueError("; ".join(quality["reasons"]))
            return {"csv_quality_passed": True, "schema": "installed-console-2.6.0-v1",
                    "frames": len(rows), "elapsed_seconds": quality["observed_seconds"],
                    "average_presented_fps": quality["metrics"]["average_presented_fps"],
                    "first_interval_discarded": True, "raw_timestamp_unit": "seconds",
                    "frame_interval_unit": "milliseconds", "benchmark_accepted": False,
                    "normalization": {"Runtime": "PresentRuntime", "TimeInSeconds": "TimeInMs = seconds * 1000",
                                      "msBetweenPresents": "MsBetweenPresents"},
                    "dropped_flag_count": sum(row.get("Dropped") == "1" for row in rows),
                    "all_present_events_retained": True, "csv_validation": quality}
        if "TimeInMs" in (reader.fieldnames or []):
            first = next(reader, None)
            application = first.get("Application", "") if first else ""
            if application.lower() not in {"java.exe", "javaw.exe"}:
                raise ValueError("Wrong application or empty console capture")
            quality = validate_csv(path, pid=pid, application=application,
                                   duration_seconds=seconds, tolerance_seconds=1)
            if not quality["quality_checks_passed"]:
                raise ValueError("; ".join(quality["reasons"]))
            return {"csv_quality_passed": True, "schema": "console-v1",
                    "frames": sum(s["frames"] for s in quality["streams"]),
                    "elapsed_seconds": quality["observed_seconds"],
                    "average_presented_fps": quality["metrics"]["average_presented_fps"],
                    "first_interval_discarded": True, "timestamp_unit": "milliseconds",
                    "frame_interval_unit": "milliseconds", "benchmark_accepted": False,
                    "csv_validation": quality}
        required = {"Application", "ProcessID", "SwapChainAddress", "PresentRuntime",
                    "TimeInSeconds", "MsBetweenPresents"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("Expected pinned headless CSV columns are missing")
        rows = list(reader)
    if len(rows) < 31:
        raise ValueError("Capture has fewer than 30 usable intervals")
    if any(r["Application"].lower() not in {"javaw.exe", "java.exe"}
           or int(r["ProcessID"]) != pid for r in rows):
        raise ValueError("Wrong process in capture")
    streams = {(r["SwapChainAddress"], r["PresentRuntime"]) for r in rows}
    if len(streams) != 1 or not all(next(iter(streams))):
        raise ValueError("Mixed or missing presentation stream identity")
    if len({tuple(r.items()) for r in rows}) != len(rows):
        raise ValueError("Duplicate frame rows")
    timestamps = [float(r["TimeInSeconds"]) for r in rows]
    intervals = [float(r["MsBetweenPresents"]) for r in rows[1:]]
    if any(not math.isfinite(t) or t < 0 for t in timestamps):
        raise ValueError("Invalid timestamps")
    if any(b <= a for a, b in zip(timestamps, timestamps[1:])):
        raise ValueError("Duplicate or decreasing timestamps")
    if any(not math.isfinite(t) or t <= 0 for t in intervals):
        raise ValueError("Invalid frame intervals")
    elapsed = timestamps[-1] - timestamps[0]
    if abs(elapsed - seconds) > 1:
        raise ValueError("Capture window differs from requested duration")
    def rounding_ms(t):
        return 0 if t == 0 else 500 * 10 ** (math.floor(math.log10(abs(t))) - 3)
    for a, b, interval in zip(timestamps, timestamps[1:], intervals):
        bound = rounding_ms(a) + rounding_ms(b) + 0.000051
        if abs((b - a) * 1000 - interval) > bound + 1e-9:
            raise ValueError("Timestamp/interval inconsistency beyond exporter rounding")
    return {"csv_quality_passed": True, "frames": len(rows), "elapsed_seconds": elapsed,
            "average_presented_fps": 1000 / statistics.mean(intervals),
            "first_interval_discarded": True, "presentation_stream": list(next(iter(streams))),
            "timestamp_unit": "seconds", "frame_interval_unit": "milliseconds",
            "benchmark_accepted": False}


class Monitor:
    def __init__(self, pid):
        self.k = C.WinDLL("kernel32", use_last_error=True)
        self.u = C.WinDLL("user32", use_last_error=True)
        signatures = {
            "OpenProcess": ([W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
            "CloseHandle": ([W.HANDLE], W.BOOL),
            "WaitForSingleObject": ([W.HANDLE, W.DWORD], W.DWORD),
            "CreateMutexW": ([C.c_void_p, W.BOOL, W.LPCWSTR], W.HANDLE),
            "ReleaseMutex": ([W.HANDLE], W.BOOL),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(self.k, name); fn.argtypes = args; fn.restype = result
        self.u.GetForegroundWindow.argtypes = []; self.u.GetForegroundWindow.restype = W.HWND
        self.u.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
        self.u.GetWindowThreadProcessId.restype = W.DWORD
        self.pid = pid
        self.handle = self.k.OpenProcess(0x100000 | 0x1000, False, pid)
        if not self.handle:
            raise RuntimeError("Could not monitor the original Minecraft process")
        self.mutex = None

    def lock(self):
        self.mutex = self.k.CreateMutexW(None, True, "Local\\ModpackFiniteFrameCapture")
        if not self.mutex:
            raise RuntimeError("Could not acquire capture lock")
        if C.get_last_error() == 183:
            self.k.CloseHandle(self.mutex); self.mutex = None
            raise RuntimeError("Another automated capture is already active")

    def sample(self):
        window_pid = W.DWORD()
        self.u.GetWindowThreadProcessId(self.u.GetForegroundWindow(), C.byref(window_pid))
        return {"utc": datetime.now(timezone.utc).isoformat(),
                "minecraft_foreground": window_pid.value == self.pid,
                "original_game_alive": self.k.WaitForSingleObject(self.handle, 0) == 0x102}

    def close(self):
        if self.mutex:
            self.k.ReleaseMutex(self.mutex); self.k.CloseHandle(self.mutex)
        self.k.CloseHandle(self.handle)


def process_inventory(profile):
    # Authentication-bearing command lines stay entirely inside PowerShell.
    ps = r'''
$ErrorActionPreference='Stop'
$wanted=[IO.Path]::GetFullPath($env:PMLAB_EXPECTED_PROFILE).TrimEnd('\')
$games=@()
foreach ($p in Get-CimInstance Win32_Process -Filter "Name='java.exe' OR Name='javaw.exe'") {
  if ($p.CommandLine -notmatch 'net\.minecraft\.client\.main\.Main|net\.fabricmc\.loader\.impl\.launch\.knot\.KnotClient') { continue }
  $m=[regex]::Match($p.CommandLine,'--gameDir\s+(?:"([^"]+)"|(\S+))')
  if (-not $m.Success) { continue }
  $actual=[IO.Path]::GetFullPath($m.Groups[1].Value+$m.Groups[2].Value).TrimEnd('\')
  if ($actual -ieq $wanted) { $games += @{pid=[int]$p.ProcessId; application=$p.Name; started_utc=$p.CreationDate.ToUniversalTime().ToString('o')} }
}
@{games=$games} | ConvertTo-Json -Depth 4 -Compress
'''
    env = os.environ.copy(); env["PMLAB_EXPECTED_PROFILE"] = str(profile.resolve(strict=True))
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
                            capture_output=True, text=True, timeout=20, env=env,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError("Minecraft identity preflight failed; no process arguments were retained")
    return json.loads(result.stdout)


def enforce_output_limit(paths,maximum_bytes):
    # Writers may not have created/flushed a file yet; this is a runaway guard only.
    total=0
    for path in paths:
        try:total+=path.stat().st_size
        except FileNotFoundError:continue
    if total>maximum_bytes:raise RuntimeError('Runaway capture output exceeded configured limit; raw evidence retained')


def run(args, pair=None):
    maximum_run_bytes=getattr(args,'maximum_run_bytes',1024**4)
    if type(maximum_run_bytes) is not int or maximum_run_bytes<1024**3:
        raise ValueError('Runaway-output limit must be at least 1 GiB')
    duration = getattr(args, "duration", 10)
    route_ended = getattr(pair, "end_on_action", False)
    if type(duration) is not int or (duration not in (10, 60, 90) and not (route_ended and duration == 180)):
        raise ValueError("Capture duration must be 10, 60 or 90 seconds")
    report = {"benchmark_accepted": False, "status": "rejected", "scope": "Stationary tool check",
              "duration_seconds": duration, "warmup_seconds": args.warmup,
              "focus_process_poll_seconds": 0.25, "missing_validation": [
                  "World/menu/camera state, in-game FPS calibration, capture overhead and repeated mod comparisons"]}
    if route_ended:
        report.update(scope="Fixed player-route frame capture; comparison acceptance remains separate",
                      capture_policy="verified-route-completion-plus-two-second-drain-v1",
                      maximum_capture_seconds=duration)
    report['maximum_run_bytes']=maximum_run_bytes
    run_dir = args.results.resolve() / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
    run_dir.mkdir(parents=True, exist_ok=False)
    monitor = child = None
    try:
        shell = C.WinDLL("shell32", use_last_error=True)
        shell.IsUserAnAdmin.argtypes = []; shell.IsUserAnAdmin.restype = W.BOOL
        report["controller_elevated"] = bool(shell.IsUserAnAdmin())
        report["requires_administrator"] = True
        if not report["controller_elevated"]:
            raise RuntimeError("Right-click Capture-Minecraft.cmd and choose Run as administrator; ETW capture needs an elevated controller")
        inventory = process_inventory(args.profile)
        report['diagnostic_only']=getattr(args,'diagnostic_only',False)
        if len(inventory["games"]) != 1:
            raise RuntimeError("Launch exactly one Minecraft client from the selected profile")
        game = inventory["games"][0]; report["game"] = game
        tool = args.presentmon.resolve(strict=True)
        if hashlib.sha256(tool.read_bytes()).hexdigest() != args.expected_sha256:
            raise RuntimeError("PresentMon executable differs from the verified tool")
        report["presentmon_sha256"] = args.expected_sha256
        monitor = Monitor(game["pid"]); monitor.lock()
        if args.check_only:
            report["preflight_sample"] = monitor.sample()
            report["status"] = "preflight_only"
            print("Preflight passed. No capture was started.")
            return 0
        if pair is not None:
            pair.prepare(game, run_dir, report)
        diagnostic=getattr(args,'diagnostic_only',False)
        print('Diagnostic capture permits background/minimized Minecraft; frame availability must still verify.' if diagnostic else 'Keep Minecraft focused with menus closed.',flush=True)
        print("Waiting for capture readiness before the " + str(duration) + "-second capture.", flush=True)
        deadline = time.monotonic() + 120
        while True:
            sample = monitor.sample()
            if not sample["original_game_alive"]:
                raise RuntimeError("Minecraft exited before capture")
            if diagnostic or sample["minecraft_foreground"]:
                break
            if time.monotonic() > deadline:
                raise RuntimeError("Timed out waiting for manual Minecraft focus")
            time.sleep(0.25)
        with (run_dir / "focus-process.jsonl").open("x", encoding="utf-8") as telemetry:
            def checked_sample(stage):
                sample = monitor.sample(); sample["stage"] = stage
                telemetry.write(json.dumps(sample) + "\n"); telemetry.flush()
                required=('original_game_alive',) if diagnostic else ('minecraft_foreground','original_game_alive')
                if not all(sample[k] for k in required):
                    failed = [k for k in required if not sample[k]]
                    raise RuntimeError("Capture conditions failed during " + stage + ": " + ", ".join(failed))
                health = getattr(pair, "health", None)
                if callable(health):
                    health()
            if pair is not None:
                pair.start()
            warm_until = time.monotonic() + args.warmup
            while time.monotonic() < warm_until:
                checked_sample("warmup"); time.sleep(0.25)
            checked_sample("before_capture")
            capture_start = getattr(pair, "capture_start", None)
            deferred_start = getattr(pair,"requires_frame_stream_ready",False)
            if callable(capture_start) and not deferred_start:
                capture_start()
            csv_path = run_dir / "frames.csv"
            report["backend"] = "PresentMon-2.6.0-x64 console, pinned v1 CSV"
            session_name = "Modpack_" + uuid.uuid4().hex
            report["etw_session_name"] = session_name
            command = presentmon_command(tool, game["pid"], duration, session_name, qpc=pair is not None)
            report["csv_transport"] = "PresentMon stdout to owned inherited file handle; diagnostics on stderr"
            with csv_path.open("xb") as frames, (run_dir / "cli-output.txt").open("x", encoding="utf-8") as output:
                recording_started = time.monotonic()
                child = subprocess.Popen(command, cwd=tool.parent, stdout=frames, stderr=output,
                                         creationflags=subprocess.CREATE_NO_WINDOW)
                if deferred_start:
                    ready_deadline=time.monotonic()+10
                    while not first_frame_ready(csv_path,game["pid"]):
                        checked_sample("waiting_for_first_frame")
                        if child.poll() is not None or time.monotonic()>ready_deadline:
                            raise RuntimeError("PresentMon did not expose a first frame before the route deadline")
                        time.sleep(0.1)
                    report["action_start_policy"]="First observed process/QPC frame before in-game action confirmation"
                    if callable(capture_start):capture_start()
                cap_deadline = time.monotonic() + duration + 15
                action = None
                action_seen = None
                gracefully_stopped = False
                while child.poll() is None:
                    checked_sample("capture_and_flush")
                    enforce_output_limit((csv_path,run_dir/'cli-output.txt'),maximum_run_bytes)
                    if route_ended and not gracefully_stopped:
                        if action is None:
                            action = pair.capture_complete()
                            if action is not None:
                                action_seen = time.monotonic()
                        if action is not None and time.monotonic() - action_seen >= 2:
                            report["owned_session_stop_exit_code"] = stop_owned_trace(tool, session_name)
                            report["duration_seconds"] = time.monotonic() - recording_started
                            report["route_completion"] = action
                            gracefully_stopped = True
                            cap_deadline = time.monotonic() + 15
                    if time.monotonic() > cap_deadline:
                        raise RuntimeError("Capture exceeded its bounded deadline")
                    time.sleep(0.25)
                checked_sample("after_capture")
            report["cli_exit_code"] = child.returncode
            if child.returncode:
                raise RuntimeError("PresentMon CLI failed; see this run's CLI output")
            if route_ended:
                if not gracefully_stopped:
                    raise RuntimeError("Route completion was not verified before capture ended")
                verify_route_capture(csv_path, action)
            report.update(check_csv(csv_path, game["pid"], seconds=report["duration_seconds"]))
            report["csv_sha256"] = hashlib.sha256(csv_path.read_bytes()).hexdigest()
            report["status"] = "tool_check_passed"
            print(str(round(report["duration_seconds"], 2)) + "-second capture passed frame-data checks. It is not yet an accepted benchmark.", flush=True)
            return 0
    except Exception as error:
        report["reason"] = str(error)
        print("REJECTED: " + str(error), flush=True)
        return 2
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill(); child.wait(timeout=5)
            # Clean only this invocation's uniquely named ETW session.
            try:
                cleanup = subprocess.run([str(args.presentmon.resolve()), "--terminate_existing_session",
                                          "--session_name", report["etw_session_name"]],
                                         capture_output=True, text=True, timeout=10,
                                         creationflags=subprocess.CREATE_NO_WINDOW)
                report["owned_session_cleanup_exit_code"] = cleanup.returncode
            except Exception as cleanup_error:
                report["owned_session_cleanup_error"] = str(cleanup_error)
        if monitor is not None:
            monitor.close()
        if pair is not None:
            try:
                pair.stop()
            except Exception as stop_error:
                report["counter_stop_error"] = str(stop_error)
        (run_dir / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print("Results: " + str(run_dir), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--presentmon", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--results", type=Path, default=Path(__file__).resolve().parent.parent / "automated-captures")
    parser.add_argument("--warmup", type=int, default=15, choices=range(5, 121))
    parser.add_argument("--check-only", action="store_true")
    raise SystemExit(run(parser.parse_args()))
