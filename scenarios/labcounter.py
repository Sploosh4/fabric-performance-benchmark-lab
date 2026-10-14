"""Finite counter API/timing check, manually started in the disposable world."""
import faulthandler
import json
from pathlib import Path
import time
import uuid

profile = Path(__file__).resolve().parent.parent
if profile.name != "sodium-automation":
    raise RuntimeError("Counter probe requires the disposable automation profile")
destination = profile / "minescript/lab-results"
destination.mkdir(parents=True, exist_ok=True)
run_id = uuid.uuid4().hex
reader = None
started = time.monotonic()
status = "failed"
with (destination / ("counter-" + run_id + ".jsonl")).open("x", encoding="utf-8") as output:
    with (destination / ("counter-" + run_id + "-stack.txt")).open("x", encoding="utf-8") as stack:
        def write(record):
            output.write(json.dumps({"elapsed_seconds": time.monotonic() - started,
                                     "benchmark_accepted": False, **record}) + "\n")
            output.flush()
        write({"phase": "starting", "hard_timeout_seconds": 60})
        faulthandler.dump_traceback_later(60, file=stack, exit=True)
        try:
            import minescript as ms
            from lab_common import MC, CONDITIONS, guard_world
            from lab_counter_core import CounterReader, counter_issues
            guard_world()
            reader = CounterReader(ms, MC.id)
            write({"phase": "waiting_for_chat_close"})
            deadline = time.monotonic() + 15
            while ms.screen_name() is not None and time.monotonic() < deadline:
                time.sleep(0.1)
            if ms.screen_name() is not None:
                raise RuntimeError("Chat/menu remained open")
            initial = reader.sample()
            issues = counter_issues(initial, CONDITIONS)
            if issues:
                raise RuntimeError("Start conditions differ: " + ", ".join(issues))
            write({"phase": "warmup", "seconds": 3})
            time.sleep(3)
            write({"phase": "sampling", "duration_seconds": 20, "target_period_seconds": 1,
                   "counter_semantics": "Minecraft getFps rolling integer; not per-frame timestamps"})
            measured = time.monotonic()
            samples = []
            while time.monotonic() - measured < 20:
                tick = time.monotonic()
                sample = reader.sample()
                sample.update(phase="sample", sample=len(samples), measurement_elapsed_seconds=tick - measured,
                              condition_issues=counter_issues(sample, CONDITIONS))
                write(sample)
                samples.append(sample)
                if sample["condition_issues"]:
                    raise RuntimeError("Counter run conditions changed: " + ", ".join(sample["condition_issues"]))
                time.sleep(max(0, 1 - (time.monotonic() - tick)))
            guard_world()
            if len(samples) < 15:
                raise RuntimeError("Too few counter samples; transport is too slow")
            max_cost = max(sample["sample_cost_seconds"] for sample in samples)
            status = "counter_tool_check_passed" if max_cost <= 0.25 else "counter_tool_check_slow"
            write({"phase": "complete", "status": status, "samples": len(samples),
                   "maximum_sample_cost_seconds": max_cost,
                   "note": "Call duration is not measured instrumentation overhead; capture calibration is pending"})
        except Exception as error:
            write({"phase": "failed", "error": str(error)})
            raise
        finally:
            if reader is not None:
                reader.close()
            faulthandler.cancel_dump_traceback_later()
ms.echo("Lab counter check: " + status + "; no benchmark accepted.")
