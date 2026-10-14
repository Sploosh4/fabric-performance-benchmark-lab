"""Explicit in-game confirmation for one already-claimed validation session."""
import minescript as ms
from lab_common import PROFILE, guard_world, number, ProcessHandle
from session_protocol import OWNER, fresh_sessions, validate_identity, publish, read_json

guard_world()
sessions = [(arm, files) for arm, files in fresh_sessions(PROFILE / "minescript/lab-results", number(ProcessHandle.current().pid()))
            if files["claim"].exists() and not files["confirm"].exists()]
if len(sessions) != 1:
    raise RuntimeError("Expected one prepared session with its controller running; found " + str(len(sessions)))
arm, files = sessions[0]
validate_identity(read_json(files["claim"]), arm["nonce"], arm["game_pid"])
publish(files["confirm"], {"owner": OWNER, "nonce": arm["nonce"], "game_pid": arm["game_pid"], "benchmark_accepted": False})
ms.echo("Lab run confirmed. Close chat and leave Minecraft focused; the whole batch is automatic.")
