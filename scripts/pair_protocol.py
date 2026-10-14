"""Local file pairing and QPC clock; no game/desktop/process control."""
import ctypes
import json
import os
from pathlib import Path
import re
import time
import uuid

OWNER = "modpack-counter-pair-v1"
OVERHEAD_ORDER = (False, True, True, False, True, False, False, True)


def reject_duplicate_overhead_jobs(jobs):
    """Refuse a new probe; never stop an existing Minescript job."""
    others = []
    for job in jobs:
        command = job.command
        if not job.self and command:
            name = str(command[0]).replace("\\", "/").rsplit("/", 1)[-1].lower()
            if name in ("laboverhead", "laboverhead.py"):
                others.append(str(job.job_id))
    if others:
        raise RuntimeError("Lab overhead is already running (job " + ", ".join(others) +
                           "). Do not arm again. Use \\jobs to inspect it; wait for it to finish "
                           "before retrying. To cancel it manually, use \\killjob <job-id>.")


def publish(path, value):
    """Atomic no-overwrite publication; unsupported filesystems fail safely."""
    path = Path(path)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as output:
            json.dump(value, output); output.write("\n")
        if os.name == 'nt':
            temporary.rename(path)  # Windows refuses an existing destination.
        else:
            # POSIX rename would overwrite. Link the complete same-directory
            # temporary inode atomically; EEXIST never replaces another writer.
            os.link(temporary,path)
    finally:
        if temporary.exists():
            temporary.unlink()  # Only this invocation's exact temporary file.


def read_json(path):
    path = Path(path)
    if path.is_symlink() or path.stat().st_size > 256 * 1024:
        raise RuntimeError("Unsupported pairing file")
    return json.loads(path.read_text(encoding="utf-8"))


def validate_arm(arm, path, pid, now_ns):
    nonce = arm.get("nonce", "")
    if arm.get("owner") != OWNER or not re.fullmatch(r"[a-f0-9]{32}", nonce):
        raise RuntimeError("Invalid counter arm identity")
    if Path(path).name != "pair-arm-" + nonce + ".json" or arm.get("game_pid") != pid:
        raise RuntimeError("Counter arm targets another game")
    created, expires = arm.get("created_unix_ns"), arm.get("expires_unix_ns")
    if not isinstance(created, int) or not isinstance(expires, int) or not created <= now_ns < expires:
        raise RuntimeError("Counter arm is stale or from the future")
    if expires - created != 120 * 10**9:
        raise RuntimeError("Counter arm lifetime differs from contract")
    if arm.get("initial_issues") or arm.get("benchmark_accepted") is not False:
        raise RuntimeError("Counter arm conditions did not pass")


def paths_for(directory, nonce):
    if not re.fullmatch(r"[a-f0-9]{32}", nonce):
        raise RuntimeError("Invalid pairing nonce")
    directory = Path(directory)
    return {name: directory / ("pair-" + name + "-" + nonce + suffix)
            for name, suffix in (("arm", ".json"), ("claim", ".json"), ("request", ".json"),
                                 ("stop", ".json"), ("done", ".json"), ("samples", ".jsonl"),
                                 ("stack", ".txt"))}


def phase_paths(directory, nonce, phase):
    paths_for(directory, nonce)  # Validate nonce before constructing any path.
    if type(phase) is not int or not 0 <= phase < len(OVERHEAD_ORDER):
        raise RuntimeError("Invalid overhead phase")
    return {name: Path(directory) / ("overhead-" + nonce + "-" + str(phase) + "-" + name + ".json")
            for name in ("request", "ack", "stop", "done")}


def validate_phase(value, nonce, phase, pid=None):
    if value.get("owner") != OWNER or value.get("nonce") != nonce or value.get("phase") != phase:
        raise RuntimeError("Overhead phase identity differs")
    if value.get("counter_enabled") is not OVERHEAD_ORDER[phase]:
        raise RuntimeError("Overhead phase order differs")
    if pid is not None and value.get("game_pid") != pid:
        raise RuntimeError("Overhead phase targets another game")


class QpcClock:
    def __init__(self):
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.QueryPerformanceFrequency.argtypes = [ctypes.POINTER(ctypes.c_longlong)]
        self.api.QueryPerformanceFrequency.restype = ctypes.c_int
        self.api.QueryPerformanceCounter.argtypes = [ctypes.POINTER(ctypes.c_longlong)]
        self.api.QueryPerformanceCounter.restype = ctypes.c_int
        frequency = ctypes.c_longlong()
        if not self.api.QueryPerformanceFrequency(ctypes.byref(frequency)) or frequency.value <= 0:
            raise RuntimeError("QPC frequency unavailable")
        self.frequency = frequency.value

    def __call__(self):
        value = ctypes.c_longlong()
        if not self.api.QueryPerformanceCounter(ctypes.byref(value)):
            raise RuntimeError("QPC clock unavailable")
        return value.value
