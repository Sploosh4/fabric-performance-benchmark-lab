"""Request safe cancellation; the owning job releases inputs and cleans its fixture."""
import minescript as ms
from lab_common import PROFILE, guard_world, number, ProcessHandle
from session_protocol import OWNER, fresh_sessions, publish

guard_world()
sessions = fresh_sessions(PROFILE / "minescript/lab-results", number(ProcessHandle.current().pid()))
if len(sessions) != 1:
    raise RuntimeError("Expected one active validation session; found " + str(len(sessions)))
arm, files = sessions[0]
publish(files["stop"], {"owner": OWNER, "nonce": arm["nonce"], "game_pid": arm["game_pid"], "benchmark_accepted": False})
ms.echo("Lab cancellation requested; wait for cleanup before preparing again.")
