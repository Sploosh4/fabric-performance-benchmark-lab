"""Bounded local session handshake, shared by Minecraft and the controller."""
from pathlib import Path
import re
import time
from pair_protocol import publish, read_json

OWNER = "modpack-validation-session-v2"
SCENARIOS = ("stationary", "movement")
LEGACY_BATCH = "stationary-route-v1"
ROUTE_BATCH = "full-route-only-v1"


def batch_protocol(value):
    protocol = value.get("batch_protocol", LEGACY_BATCH)
    if protocol not in (LEGACY_BATCH, ROUTE_BATCH):
        raise RuntimeError("Unknown batch protocol")
    if protocol == ROUTE_BATCH and value.get("movement_workload", value.get("workload")) != "restworld_rooms_v1":
        raise RuntimeError("Route-only batch requires the full room route")
    return protocol


def paths_for(directory, nonce):
    if not isinstance(nonce, str) or not re.fullmatch(r"[a-f0-9]{32}", nonce):
        raise RuntimeError("Invalid validation session nonce")
    return {name: Path(directory) / ("session-" + nonce + "-" + name + suffix)
            for name, suffix in (("arm", ".json"), ("claim", ".json"), ("confirm", ".json"),
                                 ("stop", ".json"), ("started", ".json"), ("done", ".json"),
                                 ("samples", ".jsonl"), ("stack", ".txt"))}


def phase_paths(directory, nonce, phase):
    paths_for(directory, nonce)
    if type(phase) is not int or not 0 <= phase < 20:
        raise RuntimeError("Invalid validation phase")
    return {name: Path(directory) / ("session-" + nonce + "-phase-" + str(phase) + "-" + name + ".json")
            for name in ("request", "ready", "go", "action", "stop", "done")}


def validate_identity(value, nonce, game_pid):
    if value.get("owner") != OWNER or value.get("nonce") != nonce or value.get("game_pid") != game_pid:
        raise RuntimeError("Validation session identity differs")
    if value.get("benchmark_accepted") is not False:
        raise RuntimeError("Validation tooling cannot accept a benchmark")


def validate_arm(value, path, now_ns, pid=None):
    nonce = value.get("nonce")
    paths_for(Path(path).parent, nonce)
    if Path(path).name != "session-" + nonce + "-arm.json":
        raise RuntimeError("Validation arm filename differs")
    if type(value.get("game_pid")) is not int or value["game_pid"] <= 0:
        raise RuntimeError("Invalid game process")
    validate_identity(value, nonce, value["game_pid"] if pid is None else pid)
    created, expires = value.get("created_unix_ns"), value.get("expires_unix_ns")
    if type(created) is not int or type(expires) is not int or expires - created != 900 * 10**9 or not created <= now_ns < expires:
        raise RuntimeError("Validation session arm expired")
    if type(value.get("repeats")) is not int or not 1 <= value["repeats"] <= 10 or value.get("initial_issues"):
        raise RuntimeError("Invalid repeat count or initial conditions")
    workload = value.get("movement_workload")
    if workload not in (None, "player_actions_v1", "mob_display_loop_v1", "mob_display_loop_v2", "restworld_rooms_v1") or (workload is not None and value["repeats"] > 5):
        raise RuntimeError("Unsupported or excessive extended workload")
    batch_protocol(value)


def fresh_sessions(directory, pid=None):
    sessions = []
    for path in Path(directory).glob("session-*-arm.json"):
        try:
            arm = read_json(path)
            validate_arm(arm, path, time.time_ns(), pid)
            files = paths_for(directory, arm["nonce"])
            if not files["done"].exists() and not files["stop"].exists():
                sessions.append((arm, files))
        except (RuntimeError, ValueError, OSError):
            continue
    return sessions


def schedule(repeats, protocol=LEGACY_BATCH):
    if type(repeats) is not int or not 1 <= repeats <= 10:
        raise RuntimeError("Repeats must be between one and ten")
    if protocol == ROUTE_BATCH:
        if repeats > 5:
            raise RuntimeError("Full route batches allow at most five repeats")
        return ("movement",) * repeats
    if protocol != LEGACY_BATCH:
        raise RuntimeError("Unknown batch protocol")
    return tuple(SCENARIOS * repeats)


def validate_phase(value, identity, phase, scenario):
    validate_identity(value, identity["nonce"], identity["game_pid"])
    if value.get("phase") != phase or value.get("scenario") != scenario or scenario not in SCENARIOS:
        raise RuntimeError("Validation phase order differs")
