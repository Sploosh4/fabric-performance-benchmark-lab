"""Validate the extended real-map player workload without collecting FPS."""
import json
import time
import uuid
import minescript as ms
from lab_common import PROFILE, MC, guard_world, sample_state, condition_issues
from lab_validation_core import wait_position
from lab_player_actions import PlayerActions
from pair_protocol import QpcClock

nonce = uuid.uuid4().hex
directory = PROFILE / "minescript/lab-results"
clock = QpcClock()
result = {"nonce": nonce, "status": "failed", "benchmark_accepted": False}
original = None
actions = None
with (directory / f"actions-{nonce}.jsonl").open("x", encoding="utf-8") as output:
    def write(record):
        output.write(json.dumps({"nonce": nonce, "unix_ns": time.time_ns(), "qpc": clock(), "qpc_frequency": clock.frequency, **record}) + "\n")
        output.flush()
    try:
        guard_world()
        if any(not j.self and j.command and j.command[0].lstrip("\\").removesuffix(".py").startswith("lab") for j in ms.job_info()):
            raise RuntimeError("Another lab job is active")
        deadline = time.monotonic() + 20
        while ms.screen_name() is not None and time.monotonic() < deadline:
            time.sleep(0.1)
        state = sample_state()
        if condition_issues(state, require_pose=True):
            raise RuntimeError("Player-action initial conditions differ")
        original = (ms.player_position(), ms.player_orientation())
        actions = PlayerActions(write)
        actions.prepare()
        actions.run()
        result["status"] = "extended_player_actions_passed"
    except Exception as error:
        result["error"] = str(error)
    finally:
        try:
            if actions is not None:
                actions.cleanup()
            if original is not None:
                guard_world()
                position, orientation = original
                ms.execute("tp @s " + " ".join(map(str, position + orientation)))
                ms.flush()
                wait_position(position)
                ms.player_set_orientation(*orientation)
                final = sample_state()
                issues = condition_issues(final, require_pose=True)
                write({"event": "restored_state", "issues": issues, "state": final})
                if issues:
                    raise RuntimeError("Restored player-action conditions differ")
        except Exception as error:
            result.update(status="failed", cleanup_error=str(error))
        write({"event": "result", **result})
        (directory / f"actions-{nonce}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
ms.echo("Extended player actions: " + result["status"] + ". No benchmark accepted.")
