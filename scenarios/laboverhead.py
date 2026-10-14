"""User-armed read-only logging overhead batch; no desktop or player control."""
import faulthandler
import json
import os
from pathlib import Path
import time
import uuid

profile = Path(__file__).resolve().parent.parent
if profile.name != "sodium-automation":
    raise RuntimeError("Overhead probe requires the disposable automation profile")
from pair_protocol import OWNER, OVERHEAD_ORDER, QpcClock, paths_for, phase_paths, publish, read_json, validate_phase, reject_duplicate_overhead_jobs
directory = profile / "minescript/lab-results"
directory.mkdir(parents=True, exist_ok=True)
nonce = uuid.uuid4().hex
paths = paths_for(directory, nonce)
reader = None
result = {"owner": OWNER, "nonce": nonce, "status": "failed", "purpose": "overhead",
          "benchmark_accepted": False}

with paths["samples"].open("x", encoding="utf-8") as output, paths["stack"].open("x", encoding="utf-8") as stack:
    def write(record):
        output.write(json.dumps({"owner": OWNER, "nonce": nonce, "benchmark_accepted": False, **record}) + "\n")
        output.flush()
    write({"event": "starting"})
    faulthandler.dump_traceback_later(420, file=stack, exit=True)
    try:
        import minescript as ms
        reject_duplicate_overhead_jobs(ms.job_info())
        from lab_common import MC, CONDITIONS, guard_world, sample_state, condition_issues
        from lab_counter_core import CounterReader, counter_issues
        guard_world()
        deadline = time.monotonic() + 15
        while ms.screen_name() is not None and time.monotonic() < deadline:
            time.sleep(0.1)
        initial = sample_state()
        issues = condition_issues(initial, require_pose=True)
        if issues:
            raise RuntimeError("Overhead start conditions differ: " + ", ".join(issues))
        reject_duplicate_overhead_jobs(ms.job_info())
        clock = QpcClock()
        reader = CounterReader(ms, MC.id)
        now = time.time_ns()
        arm = {"owner": OWNER, "nonce": nonce, "purpose": "overhead", "game_pid": initial["process_id"],
               "probe_pid": os.getpid(), "created_unix_ns": now, "expires_unix_ns": now + 120 * 10**9,
               "initial_issues": issues, "initial_state": initial,
               "qpc_frequency": clock.frequency, "benchmark_accepted": False}
        publish(paths["arm"], arm)
        write({"event": "armed", "qpc_frequency": clock.frequency})
        ms.echo("Lab overhead armed. Start Capture-Minecraft-Overhead.cmd as administrator within two minutes.")
        suite_deadline = None
        for phase, enabled in enumerate(OVERHEAD_ORDER):
            phase_files = phase_paths(directory, nonce, phase)
            wait_deadline = time.monotonic() + (120 if phase == 0 else 30)
            while not phase_files["request"].exists():
                if paths["stop"].exists() or time.monotonic() > wait_deadline:
                    raise RuntimeError("Overhead controller stopped or phase request timed out")
                time.sleep(0.1)
            request = read_json(phase_files["request"])
            validate_phase(request, nonce, phase, arm["game_pid"])
            if suite_deadline is None:
                suite_deadline = time.monotonic() + 260
            guard_world()
            before = reader.sample(qpc=clock)
            before_issues = counter_issues(before, CONDITIONS)
            if before_issues:
                raise RuntimeError("Overhead phase start differs: " + ", ".join(before_issues))
            identity = {"owner": OWNER, "nonce": nonce, "phase": phase, "counter_enabled": enabled,
                        "game_pid": arm["game_pid"], "benchmark_accepted": False}
            write({"event": "phase_start", **identity, "state": before})
            publish(phase_files["ack"], {**identity, "status": "ready", "ready_qpc": clock()})
            phase_deadline = time.monotonic() + 45
            count = 0
            while not phase_files["stop"].exists():
                if paths["stop"].exists() or time.monotonic() > min(phase_deadline, suite_deadline):
                    raise RuntimeError("Overhead capture stopped or exceeded deadline")
                tick = time.monotonic()
                if enabled:
                    sample = reader.sample(qpc=clock)
                    issues = counter_issues(sample, CONDITIONS)
                    write({"event": "sample", **identity, "sample": count,
                           "condition_issues": issues, "state": sample})
                    count += 1
                    if issues:
                        raise RuntimeError("Overhead sample conditions changed: " + ", ".join(issues))
                    time.sleep(max(0, 1 - (time.monotonic() - tick)))
                else:
                    # Keep the installed mod and script process present, but
                    # issue no Minecraft/Java calls inside idle measurement.
                    time.sleep(1)  # Match active sampling cadence without game calls.
            validate_phase(read_json(phase_files["stop"]), nonce, phase)
            guard_world()
            after = reader.sample(qpc=clock)
            after_issues = counter_issues(after, CONDITIONS)
            if after_issues:
                raise RuntimeError("Overhead phase end differs: " + ", ".join(after_issues))
            complete = {**identity, "status": "phase_complete", "counter_samples": count,
                        "before": before, "after": after,
                        "idle_midphase_pose_coverage": "unsampled" if not enabled else "sampled at approximately 1 Hz"}
            write({"event": "phase_complete", **complete})
            publish(phase_files["done"], complete)
        result.update(status="overhead_probe_complete", phases=len(OVERHEAD_ORDER))
        write({"event": "complete", **result})
    except Exception as error:
        result["error"] = str(error)
        write({"event": "failed", **result})
        raise
    finally:
        publish(paths["done"], result)
        if reader is not None:
            reader.close()
        faulthandler.cancel_dump_traceback_later()
ms.echo("Lab overhead batch complete; no benchmark accepted.")
