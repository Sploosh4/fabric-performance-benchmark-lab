"""One elevated, bounded worker for explicit in-game lab sessions and overhead checks."""
import ctypes
from datetime import datetime
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import time
import uuid

from capture_headless import Monitor, process_inventory
from capture_session import main as session_main
from capture_overhead import main as overhead_main
from pair_protocol import paths_for as pair_paths, read_json, validate_arm as validate_pair
from session_protocol import fresh_sessions

from lab_settings import load
SETTINGS=load(required=False)
PROFILE=SETTINGS.profile
OUTPUTS=SETTINGS.outputs
TOOL=SETTINGS.presentmon
TOOL_HASH=SETTINGS.presentmon_sha256


def pending(directory, pid, attempted):
    candidates = [("session", arm["nonce"]) for arm, files in fresh_sessions(directory, pid)
                  if not files["claim"].exists() and arm["nonce"] not in attempted]
    for path in directory.glob("pair-arm-*.json"):
        try:
            arm = read_json(path)
            validate_pair(arm, path, pid, time.time_ns())
            if arm.get("purpose") != "overhead" or arm["nonce"] in attempted:
                continue
            files = pair_paths(directory, arm["nonce"])
            if not files["claim"].exists() and not files["done"].exists() and not files["stop"].exists():
                candidates.append(("overhead", arm["nonce"]))
        except (RuntimeError, ValueError, OSError):
            continue
    return candidates


def main():
    load()
    logs = OUTPUTS / "session-controller-logs"
    logs.mkdir(exist_ok=True)
    nonce = uuid.uuid4().hex
    stop = logs / ("worker-stop-" + nonce + ".json")
    state_path = logs / ("worker-" + nonce + ".json")
    status = {"owner": "modpack-bounded-lab-worker-v1", "nonce": nonce, "benchmark_accepted": False,
              "status": "starting", "stop_file": str(stop), "maximum_idle_lifetime_minutes": 45, "batches": []}
    monitor = mutex = None
    with (logs / ("worker-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + nonce[:8] + ".log")).open("x", encoding="utf-8", buffering=1) as log:
        sys.stdout = sys.stderr = log
        try:
            shell = ctypes.WinDLL("shell32", use_last_error=True)
            if not shell.IsUserAnAdmin():
                raise RuntimeError("This worker needs one administrator consent at launch")
            games = process_inventory(PROFILE)["games"]
            if len(games) != 1:
                raise RuntimeError("Expected one already-open matching Minecraft instance")
            pid = games[0]["pid"]
            status["game_pid"] = pid
            monitor = Monitor(pid)
            mutex = monitor.k.CreateMutexW(None, True, "Local\\ModpackValidationWorker")
            if not mutex:
                raise RuntimeError("Worker mutex unavailable")
            if ctypes.get_last_error() == 183:
                monitor.k.CloseHandle(mutex)
                mutex = None
                raise RuntimeError("Another lab worker is already running")
            deadline, attempted = time.monotonic() + 45 * 60, set()
            last = None
            while time.monotonic() < deadline and not stop.exists():
                if not monitor.sample()["original_game_alive"]:
                    status["status"] = "game_exited"
                    break
                candidates = pending(PROFILE / "minescript/lab-results", pid, attempted)
                if len(candidates) == 1:
                    kind, armed_nonce = candidates[0]
                    attempted.add(armed_nonce)  # Never retry a rejected arm in a loop.
                    status["status"] = "running_" + kind
                    state_path.write_text(json.dumps(status, indent=2), encoding="utf-8")
                    args = SimpleNamespace(profile=PROFILE, presentmon=TOOL, expected_sha256=TOOL_HASH,
                        results=OUTPUTS / ("session-captures" if kind == "session" else "overhead-captures"), functional_only=False)
                    code = session_main(args) if kind == "session" else overhead_main(args)
                    status["batches"].append({"kind": kind, "nonce": armed_nonce, "exit_code": code, "benchmark_accepted": False})
                    last = None
                else:
                    current = "idle_ready" if not candidates else "ambiguous_arms_refused"
                    status["status"] = current
                    if current != last:
                        print(current, flush=True)
                        state_path.write_text(json.dumps(status, indent=2), encoding="utf-8")
                        last = current
                    time.sleep(0.5)
            else:
                status["status"] = "stopped" if stop.exists() else "idle_deadline_reached"
        except Exception as error:
            status.update(status="failed", error=str(error))
            print("WORKER FAILED: " + str(error), flush=True)
        finally:
            if mutex is not None:
                monitor.k.ReleaseMutex(mutex)
                monitor.k.CloseHandle(mutex)
            if monitor is not None:
                monitor.close()
            state_path.write_text(json.dumps(status, indent=2), encoding="utf-8")
    return 2 if status["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
