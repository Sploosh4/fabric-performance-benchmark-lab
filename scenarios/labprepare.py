"""Prepare one bounded validation session; wait for controller and labrun."""
import faulthandler
import json
import sys
import time
import traceback
import uuid
import minescript as ms
import session_runtime
from experiment_protocol import validate_manifest
from lab_common import PROFILE, CONDITIONS, guard_world, apply_graphics_conditions, sample_state, condition_issues, heap_snapshot
from lab_validation_core import assert_live, wait_live, wait_position, release_inputs
from lab_rooms_actions import RoomActions as PlayerActions
from room_route_protocol import WORKLOAD
from lab_experiment import experiment_snapshot
from pair_protocol import QpcClock
from session_protocol import OWNER, ROUTE_BATCH, batch_protocol, paths_for, phase_paths, schedule, validate_identity, validate_phase, publish, read_json
from auto_prepare_protocol import validate_launch_request

directory = PROFILE / "minescript/lab-results"
directory.mkdir(exist_ok=True)
repeats = int(sys.argv[1]) if len(sys.argv) == 2 else 3
if not 1 <= repeats <= 5:
    raise RuntimeError("Extended workloads allow 1–5 repeats per bounded session")
nonce = uuid.uuid4().hex
files = paths_for(directory, nonce)
result = {"owner": OWNER, "nonce": nonce, "status": "failed", "benchmark_accepted": False, "completed_phases": 0}
actions = None
clock = QpcClock()
owns_inputs = False
with files["samples"].open("x", encoding="utf-8") as output, files["stack"].open("x", encoding="utf-8") as stack:
    def write(record):
        output.write(json.dumps({"nonce": nonce, "unix_ns": time.time_ns(), "qpc": clock(), "qpc_frequency": clock.frequency, "benchmark_accepted": False, **record}) + "\n")
        output.flush()
    def stopped():
        if files["stop"].exists():
            raise RuntimeError("Validation session cancelled")
    def wait_file(path, timeout, live=False):
        deadline = time.monotonic() + timeout
        while not path.exists():
            stopped()
            if time.monotonic() > deadline or time.monotonic() > session_deadline:
                raise RuntimeError("Validation handshake timed out: " + path.name)
            if live:
                assert_live(files["stop"])
            time.sleep(0.1)
        return read_json(path)
    def reset_stationary():
        guard_world()
        assert_live(files["stop"])
        release_inputs()
        x, y, z = CONDITIONS["start_position"]
        yaw, pitch = CONDITIONS["start_orientation"]
        ms.execute(f"tp @s {x} {y} {z} {yaw} {pitch}")
        ms.flush()
        wait_position(CONDITIONS["start_position"])
        ms.player_set_orientation(yaw, pitch)
    session_deadline = time.monotonic() + 1200
    faulthandler.dump_traceback_later(1200, file=stack)
    try:
        guard_world()
        automatic=globals().get('AUTO_PREPARE_REQUEST')
        if automatic is not None:
            pinned=validate_manifest(read_json(PROFILE/'minescript/lab-experiment.json'))
            validate_launch_request(automatic,PROFILE,CONDITIONS,pinned)
            session_runtime.configure(automatic.get('diagnostic_only',False))
        duplicates = [j.job_id for j in ms.job_info() if not j.self and j.command and j.command[0].lstrip("\\").removesuffix(".py") in ("labprepare", "labautorun", "labactions", "labvalidate", "labtour", "laboverhead", "labpair", "labstate")]
        if duplicates:
            raise RuntimeError("Another lab job is active: " + str(duplicates))
        owns_inputs = True
        deadline = time.monotonic() + 20
        while ms.screen_name() is not None and time.monotonic() < deadline:
            time.sleep(0.1)
        apply_graphics_conditions()
        reset_stationary()
        initial = sample_state()
        issues = condition_issues(initial, require_pose=True)
        write({"event": "initial_state", "state": initial, "issues": issues})
        if issues:
            raise RuntimeError("Preparation conditions differ: " + ", ".join(issues))
        result["game_pid"] = initial["process_id"]
        identity = {"owner": OWNER, "nonce": nonce, "game_pid": initial["process_id"], "benchmark_accepted": False}
        experiment = experiment_snapshot(stopped)
        protocol = batch_protocol(experiment["manifest"])
        order = schedule(repeats, protocol)
        now = time.time_ns()
        arm = {**identity, "repeats": repeats, "movement_workload": WORKLOAD, "batch_protocol": protocol, "initial_state": initial, "initial_issues": [],
               "experiment": experiment,
               "created_unix_ns": now, "expires_unix_ns": now + 900 * 10**9}
        automatic=globals().get('AUTO_PREPARE_REQUEST')
        if automatic is not None:
            validate_launch_request(automatic,PROFILE,CONDITIONS,experiment['manifest'])
            arm.update(auto_prepare_nonce=automatic['nonce'],auto_prepare_mode=automatic['mode'])
            arm['diagnostic_only']=automatic.get('diagnostic_only',False)
        publish(files["arm"], arm)
        ms.echo("Lab prepared: " + str(repeats) + " repeats. Start Capture-Minecraft-Session.cmd, then run \\labrun once.")
        claim = wait_file(files["claim"], 900)
        validate_identity(claim, nonce, identity["game_pid"])
        if automatic is not None and claim.get('mode')!=automatic['mode']:
            raise RuntimeError('Automatic preparation/controller mode differs')
        confirm = wait_file(files["confirm"], 300)
        validate_identity(confirm, nonce, identity["game_pid"])
        deadline = time.monotonic() + 15
        while ms.screen_name() is not None and time.monotonic() < deadline:
            stopped()
            time.sleep(0.1)
        assert_live(files["stop"])
        # Setup and human confirmation must not consume the active batch budget.
        # Keep both stages bounded; per-phase acknowledgement limits still apply.
        session_deadline = time.monotonic() + 1200
        faulthandler.cancel_dump_traceback_later()
        faulthandler.dump_traceback_later(1200, file=stack)
        write({"event": "active_session_started", "budget_seconds": 1200})
        publish(files["started"], {**identity, "status": "started"})
        for phase, scenario in enumerate(order):
            phase_files = phase_paths(directory, nonce, phase)
            request = wait_file(phase_files["request"], 120, live=True)
            validate_phase(request, identity, phase, scenario)
            guard_world()
            if scenario == "stationary":
                reset_stationary()
            elif scenario == "movement":
                actions = PlayerActions(write, files["stop"])
                actions.prepare()
                write({"event": "unscored_route_start", "phase": phase, "scenario": scenario, "pass": 1})
                actions.run()
                write({"event": "unscored_route_complete", "phase": phase, "scenario": scenario, "pass": 1})
                if protocol == ROUTE_BATCH:
                    actions.restart_after_unscored()
                else:
                    actions.cleanup()
                    actions = PlayerActions(write, files["stop"])
                    actions.prepare()
            assert_live(files["stop"])
            phase_id = {**identity, "phase": phase, "scenario": scenario}
            before_state = sample_state()
            phase_experiment = experiment_snapshot(stopped)
            if phase_experiment != experiment:
                raise RuntimeError("Pinned experiment or loaded mods changed before capture")
            issues = condition_issues(before_state)
            if issues:
                raise RuntimeError("Phase settings differ: " + ", ".join(issues))
            write({"event": "phase_context", "phase": phase, "scenario": scenario, "stage": "before",
                   "state": before_state, "experiment": phase_experiment})
            write({"event": "heap_snapshot", "phase": phase, "scenario": scenario, "stage": "before", **heap_snapshot()})
            publish(phase_files["ready"], {**phase_id, "status": "ready"})
            go = wait_file(phase_files["go"], 60, live=True)
            validate_phase(go, identity, phase, scenario)
            write({"event": "action_start", "phase": phase, "scenario": scenario})
            if scenario == "movement":
                actions.run()
            else:
                wait_live(1, files["stop"])
            publish(phase_files["action"], {**phase_id, "status": "action_verified",
                    "completed_qpc": clock(), "qpc_frequency": clock.frequency})
            stop = wait_file(phase_files["stop"], 90, live=True)
            validate_phase(stop, identity, phase, scenario)
            write({"event": "heap_snapshot", "phase": phase, "scenario": scenario, "stage": "after", **heap_snapshot()})
            after_state = sample_state()
            after_experiment = experiment_snapshot(stopped)
            if after_experiment != experiment or condition_issues(after_state):
                raise RuntimeError("Experiment or settings changed during capture")
            write({"event": "phase_context", "phase": phase, "scenario": scenario, "stage": "after",
                   "state": after_state, "experiment": after_experiment})
            if scenario == "movement":
                actions.cleanup()
                reset_stationary()
                actions = None
            publish(phase_files["done"], {**phase_id, "status": "phase_complete"})
            result["completed_phases"] += 1
        result["status"] = "session_validation_passed"
    except Exception as error:
        result["error"] = str(error)
        result["traceback"] = traceback.format_exc()
    finally:
        try:
            if actions is not None:
                actions.cleanup()
            if owns_inputs:
                release_inputs()
            if result.get("game_pid") is not None:
                guard_world()
                x, y, z = CONDITIONS["start_position"]
                yaw, pitch = CONDITIONS["start_orientation"]
                ms.execute(f"tp @s {x} {y} {z} {yaw} {pitch}")
                ms.flush()
                wait_position(CONDITIONS["start_position"])
        except Exception as error:
            result["cleanup_error"] = str(error)
            result["status"] = "failed"
        faulthandler.cancel_dump_traceback_later()
        write({"event": "result", **result})
        publish(files["done"], result)
        session_runtime.configure(False)
ms.echo("Lab session: " + result["status"] + "; " + str(result["completed_phases"]) + " phases. No benchmark accepted.")
if result.get("error"):
    ms.echo("Preparation/session reason: " + result["error"])
if result.get("cleanup_error"):
    ms.echo("Cleanup reason: " + result["cleanup_error"])
