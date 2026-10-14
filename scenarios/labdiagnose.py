"""Bounded, read-only Minescript startup diagnosis; no settings/player changes."""
import faulthandler
import json
from pathlib import Path
import time
import uuid

profile = Path(__file__).resolve().parent.parent
if profile.name != "sodium-automation":
    raise RuntimeError("Diagnosis is restricted to the disposable automation profile")
destination = profile / "minescript/lab-results"
destination.mkdir(parents=True, exist_ok=True)
run_id = uuid.uuid4().hex
started = time.monotonic()

with (destination / ("diagnose-" + run_id + ".jsonl")).open("x", encoding="utf-8") as output:
    with (destination / ("diagnose-" + run_id + "-stack.txt")).open("x", encoding="utf-8") as stack:
        def mark(phase, **details):
            output.write(json.dumps({"phase": phase, "elapsed_seconds": time.monotonic() - started,
                                     "benchmark_accepted": False, **details}) + "\n")
            output.flush()
        mark("starting", timeout_seconds=45)
        # If an RPC never returns, retain its Python stack and exit this probe
        # subprocess only. No other process, game or save is terminated.
        faulthandler.dump_traceback_later(45, file=stack, exit=True)
        try:
            mark("importing_minescript")
            import minescript as ms
            mark("calling_version_info")
            version = ms.version_info()
            mark("calling_world_info", minecraft=version.minecraft)
            world = ms.world_info()
            mark("importing_java_helpers", world_name=world.name, dimension=world.dimension)
            import java
            mark("importing_lab_common")
            from lab_common import guard_world, sample_state, condition_issues
            mark("guarding_world")
            guard_world()
            mark("sampling_state")
            state = sample_state()
            mark("complete", state=state, condition_issues=condition_issues(state))
        except Exception as error:
            mark("failed", error=str(error))
            raise
        finally:
            faulthandler.cancel_dump_traceback_later()
