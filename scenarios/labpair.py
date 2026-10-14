"""Manually arm a read-only counter probe for a user-started PresentMon capture."""
import faulthandler
import json
import os
from pathlib import Path
import time
import uuid

profile = Path(__file__).resolve().parent.parent
if profile.name != "sodium-automation":
    raise RuntimeError("Pair probe requires the disposable automation profile")
from pair_protocol import OWNER, QpcClock, paths_for, publish, read_json
directory = profile / "minescript/lab-results"
directory.mkdir(parents=True, exist_ok=True)
nonce = uuid.uuid4().hex
paths = paths_for(directory, nonce)
reader = None
result = {"owner": OWNER, "nonce": nonce, "status": "failed", "benchmark_accepted": False}
with paths["samples"].open("x", encoding="utf-8") as output, paths["stack"].open("x", encoding="utf-8") as stack:
    def write(record):
        output.write(json.dumps({"owner": OWNER, "nonce": nonce, "benchmark_accepted": False, **record}) + "\n")
        output.flush()
    write({"phase": "starting"})
    faulthandler.dump_traceback_later(210, file=stack, exit=True)
    try:
        import minescript as ms
        from lab_common import MC, CONDITIONS, guard_world, sample_state, condition_issues
        from lab_counter_core import CounterReader, counter_issues
        guard_world()
        deadline = time.monotonic() + 15
        while ms.screen_name() is not None and time.monotonic() < deadline:
            time.sleep(0.1)
        initial = sample_state()
        issues = condition_issues(initial, require_pose=True)
        if issues:
            raise RuntimeError("Pair start conditions differ: " + ", ".join(issues))
        clock = QpcClock()
        reader = CounterReader(ms, MC.id)
        now = time.time_ns()
        arm = {"owner": OWNER, "nonce": nonce, "game_pid": initial["process_id"],
               "probe_pid": os.getpid(), "created_unix_ns": now, "expires_unix_ns": now + 120 * 10**9,
               "initial_issues": issues, "initial_state": initial,
               "qpc_frequency": clock.frequency, "benchmark_accepted": False}
        publish(paths["arm"], arm)
        write({"phase": "armed", "qpc_frequency": clock.frequency})
        ms.echo("Lab pair armed. Start Capture-Minecraft-Paired.cmd as administrator within two minutes.")
        deadline = time.monotonic() + 120
        while not paths["request"].exists():
            if paths["stop"].exists():
                raise RuntimeError("Capture controller stopped before sampling")
            if time.monotonic() > deadline:
                raise RuntimeError("No capture request arrived; pair arm expired")
            time.sleep(0.1)
        request = read_json(paths["request"])
        if request.get("owner") != OWNER or request.get("nonce") != nonce or request.get("game_pid") != arm["game_pid"]:
            raise RuntimeError("Pair request identity differs")
        write({"phase": "sampling", "qpc_frequency": clock.frequency,
               "counter_semantics": "Minecraft rolling integer FPS; not exact frame times"})
        started = time.monotonic()
        count = 0
        stopped_at = None
        while time.monotonic() - started < 60:
            tick = time.monotonic()
            sample = reader.sample(qpc=clock)
            issues = counter_issues(sample, CONDITIONS)
            sample.update(phase="sample", sample=count, condition_issues=issues)
            write(sample)
            count += 1
            if issues:
                raise RuntimeError("Pair conditions changed: " + ", ".join(issues))
            if paths["stop"].exists() and stopped_at is None:
                stop = read_json(paths["stop"])
                if stop.get("owner") != OWNER or stop.get("nonce") != nonce:
                    raise RuntimeError("Pair stop identity differs")
                stopped_at = time.monotonic()
            if stopped_at is not None and time.monotonic() - stopped_at >= 3:
                break
            time.sleep(max(0, 1 - (time.monotonic() - tick)))
        if stopped_at is None:
            raise RuntimeError("Capture controller did not finish within 60 seconds")
        guard_world()
        result.update(status="counter_pair_complete", samples=count, qpc_frequency=clock.frequency)
        write({"phase": "complete", **result})
    except Exception as error:
        result["error"] = str(error)
        write({"phase": "failed", **result})
        raise
    finally:
        publish(paths["done"], result)
        if reader is not None:
            reader.close()
        faulthandler.cancel_dump_traceback_later()
ms.echo("Lab paired counter complete; no benchmark accepted.")
