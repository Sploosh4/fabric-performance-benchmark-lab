"""Three unattended functional movement/use/reset repeats, never an FPS benchmark."""
import faulthandler
import json
from pathlib import Path
import time
import uuid
import minescript as ms
from lab_common import PROFILE, guard_world, sample_state, condition_issues
from lab_validation_core import Fixture

directory = PROFILE / "minescript/lab-results"
directory.mkdir(exist_ok=True)
nonce = uuid.uuid4().hex
result = {"status": "failed", "nonce": nonce, "completed_repeats": 0, "benchmark_accepted": False}
with (directory / ("validation-" + nonce + ".jsonl")).open("x", encoding="utf-8") as output, \
     (directory / ("validation-" + nonce + ".stack.txt")).open("x", encoding="utf-8") as stack:
    def write(record):
        output.write(json.dumps({"nonce": nonce, "unix_ns": time.time_ns(), "benchmark_accepted": False, **record}) + "\n")
        output.flush()
    fixture = Fixture(directory / ("fixture-" + nonce + ".json"), write)
    faulthandler.dump_traceback_later(120, file=stack)  # Diagnostic only; avoid exiting with input held.
    try:
        guard_world()
        deadline = time.monotonic() + 15
        while ms.screen_name() is not None and time.monotonic() < deadline:
            time.sleep(0.1)
        initial = sample_state()
        issues = condition_issues(initial, require_pose=True)
        write({"event": "initial_state", "state": initial, "issues": issues})
        if issues:
            raise RuntimeError("Functional validation conditions differ: " + ", ".join(issues))
        fixture.build()
        for repeat in range(3):
            write({"event": "repeat_start", "repeat": repeat})
            fixture.reset()
            fixture.walk()
            fixture.interact()
            fixture.reset()
            result["completed_repeats"] += 1
        result["status"] = "functional_validation_passed"
    except Exception as error:
        result["error"] = str(error)
    finally:
        if fixture.original_position is not None:
            try:
                fixture.cleanup()
            except Exception as error:
                result["cleanup_error"] = str(error)
                result["status"] = "failed"
        faulthandler.cancel_dump_traceback_later()
        write({"event": "result", **result})
        (directory / ("validation-" + nonce + ".json")).write_text(json.dumps(result, indent=2), encoding="utf-8")
ms.echo("Lab functional validation: " + result["status"] + "; " + str(result["completed_repeats"]) + "/3 repeats. No benchmark accepted.")
