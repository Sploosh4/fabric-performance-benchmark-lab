"""Reset the player only inside the guarded disposable world, then verify the pose."""
import json
import time
import uuid
import minescript as ms
from lab_common import PROFILE, CONDITIONS, guard_world, sample_state, condition_issues

guard_world()
deadline = time.monotonic() + 20
while ms.screen_name() is not None and time.monotonic() < deadline:
    time.sleep(0.25)
if ms.screen_name() is not None:
    raise RuntimeError("Close the command/chat screen and rerun labpose")
x, y, z = CONDITIONS["start_position"]
yaw, pitch = CONDITIONS["start_orientation"]
guard_world()  # The world may have changed while waiting for the chat screen.
ms.execute(f"tp @s {x} {y} {z} {yaw} {pitch}")
deadline = time.monotonic() + 10
record = None
issues = ["pose_not_sampled"]
while time.monotonic() < deadline:
    ms.player_set_orientation(yaw, pitch)
    record = sample_state()
    issues = condition_issues(record, require_pose=True)
    if not issues:
        break
    time.sleep(0.25)
result = {"status": "pose_verified" if not issues else "pose_rejected",
          "issues": issues, "state": record, "benchmark_accepted": False}
path = PROFILE / "minescript/lab-results" / ("pose-" + uuid.uuid4().hex + ".json")
path.parent.mkdir(exist_ok=True)
path.write_text(json.dumps(result, indent=2), encoding="utf-8")
ms.echo("Lab pose check: " + result["status"])
