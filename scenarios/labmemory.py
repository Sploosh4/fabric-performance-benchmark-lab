"""Separate bounded, post-observed-G1-collection memory pilot; never a frame capture."""
import json
import time
import uuid
import minescript as ms
from lab_common import PROFILE, guard_world, sample_state, condition_issues
from lab_experiment import experiment_snapshot, retained_checkpoint
from lab_validation_core import release_inputs, assert_live, wait_live

nonce = uuid.uuid4().hex
directory = PROFILE / "minescript/lab-results"
stop = directory / ("memory-" + nonce + "-stop.json")
result = {"schema": "modpack-memory-pilot-v1", "nonce": nonce, "benchmark_accepted": False,
          "status": "failed", "checkpoints": [], "scope": "Matched loaded RestWorld; broader content workload untested"}
try:
    guard_world()
    duplicates = [j.job_id for j in ms.job_info() if not j.self and j.command and
                  j.command[0].lstrip("\\").removesuffix(".py").startswith("lab")]
    if duplicates:
        raise RuntimeError("Another lab job is active")
    deadline = time.monotonic() + 15
    while ms.screen_name() is not None and time.monotonic() < deadline:
        time.sleep(0.1)
    assert_live(stop)
    result["initial_state"] = sample_state()
    if condition_issues(result["initial_state"], require_pose=True):
        raise RuntimeError("Memory pilot requires verified stationary starting conditions")
    result["experiment"] = experiment_snapshot()
    if result["experiment"] is None:
        raise RuntimeError("Memory pilot requires a pinned experiment")
    ms.echo("Memory pilot warming up for 30 seconds; no frame capture.")
    wait_live(30, stop)
    for _ in range(3):
        result["checkpoints"].append(retained_checkpoint(stop, wait_live))
        wait_live(5, stop)
    result["final_state"] = sample_state()
    if experiment_snapshot() != result["experiment"] or condition_issues(result["final_state"], require_pose=True):
        raise RuntimeError("Memory experiment conditions changed")
    result["status"] = "memory_pilot_complete"
except Exception as error:
    result["reason"] = str(error)
finally:
    release_inputs()
    directory.mkdir(exist_ok=True)
    (directory / ("memory-" + nonce + ".json")).write_text(json.dumps(result, indent=2), encoding="utf-8")
ms.echo("Memory pilot complete; retention depends on observed old-generation collection and matched control.")
