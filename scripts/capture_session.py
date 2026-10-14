"""One persistent controller for a user-confirmed validation batch; no desktop input."""
import argparse
import ctypes
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import time
import uuid

from capture_headless import Monitor, process_inventory, run
from resource_monitor import ResourceRecorder
from session_protocol import OWNER, ROUTE_BATCH, batch_protocol, fresh_sessions, phase_paths, schedule, validate_identity, validate_phase, publish, read_json


def sampling_order(arm, args):
    if getattr(args, "resource_overhead", False):
        if batch_protocol(arm) == ROUTE_BATCH or getattr(args, "no_resources", False) or arm["repeats"] != 4 or arm.get("movement_workload") not in ("mob_display_loop_v2","restworld_rooms_v1"):
            raise ValueError("Resource overhead check requires \\labprepare 4 with the current route; do not combine with --no-resources")
        return (True, False, False, True)
    return (not getattr(args, "no_resources", False),) * arm["repeats"]


class Session:
    def __init__(self, arm, files, directory, monitor, output, resources=None):
        self.arm, self.files, self.directory = arm, files, directory
        self.monitor, self.output = monitor, output
        self.identity = {"owner": OWNER, "nonce": arm["nonce"], "game_pid": arm["game_pid"], "benchmark_accepted": False}
        self.deadline = time.monotonic() + 1200
        self.active_started = False
        self.resources = resources
        self.resources_enabled = resources is not None
        self.resource_context = {"stage": "waiting_for_labrun"}

    def begin(self, started):
        validate_identity(started, self.arm["nonce"], self.arm["game_pid"])
        if started.get("status") != "started":
            raise RuntimeError("Game did not confirm session start")
        if self.active_started:
            raise RuntimeError("Active session budget cannot be restarted")
        self.health(require_focus=True)
        self.deadline = time.monotonic() + 1200
        self.active_started = True

    def health(self, require_focus=True):
        if getattr(self, "external_stop", None) is not None and self.external_stop.exists():
            raise RuntimeError("Capture broker cancellation requested")
        if self.files["stop"].exists():
            raise RuntimeError("Validation session cancelled")
        if time.monotonic() > self.deadline:
            raise RuntimeError("Validation session exceeded its bounded deadline")
        sample = self.monitor.sample()
        self.output.write(json.dumps(sample) + "\n")
        self.output.flush()
        required = ("original_game_alive",) + (("minecraft_foreground",) if require_focus and not self.arm.get('diagnostic_only',False) else ())
        failed = [name for name in required if not sample[name]]
        if failed:
            raise RuntimeError("Session conditions failed: " + ", ".join(failed))
        if self.resources is not None and self.resources_enabled:
            self.resources.tick(self.resource_context)
        if self.files["done"].exists():
            done = read_json(self.files["done"])
            validate_identity(done, self.arm["nonce"], self.arm["game_pid"])
            if done.get("status") != "session_validation_passed":
                raise RuntimeError("Game-side session failed: " + str(done.get("error", "unknown")))

    def wait(self, path, timeout, require_focus=True):
        deadline = time.monotonic() + timeout
        while not path.exists():
            self.health(require_focus)
            if time.monotonic() > deadline:
                raise RuntimeError("Session acknowledgement timed out: " + path.name)
            time.sleep(0.1)
        value = read_json(path)
        validate_identity(value, self.arm["nonce"], self.arm["game_pid"])
        return value

    def stop(self):
        if not self.files["stop"].exists():
            publish(self.files["stop"], self.identity)


class Phase:
    requires_frame_stream_ready = True
    def __init__(self, session, index, scenario):
        self.session, self.index, self.scenario = session, index, scenario
        self.files = phase_paths(session.directory, session.arm["nonce"], index)
        self.identity = {**session.identity, "phase": index, "scenario": scenario}
        self.run_dir = None
        self.end_on_action = batch_protocol(session.arm) == ROUTE_BATCH

    def capture_complete(self):
        if not self.files["action"].exists():
            return None
        action = read_json(self.files["action"])
        validate_phase(action, self.identity, self.index, self.scenario)
        if action.get("status") != "action_verified":
            raise RuntimeError("Game action did not verify")
        if any(type(action.get(k)) is not int or action[k] <= 0 for k in ("completed_qpc", "qpc_frequency")):
            raise RuntimeError("Action completion clock missing")
        return action

    def prepare(self, game, run_dir, report):
        self.run_dir = run_dir
        self.session.resource_context = {"phase": self.index, "scenario": self.scenario, "stage": "preparing",
                                         "resources_enabled": self.session.resources_enabled}
        if getattr(self.session,'measurement_gate',None) is not None:self.session.measurement_gate()
        if game["pid"] != self.session.arm["game_pid"]:
            raise RuntimeError("Minecraft process changed")
        self.health()
        publish(self.files["request"], self.identity)
        ready = self.session.wait(self.files["ready"], 600 if self.session.arm.get('diagnostic_only') else 180)
        validate_phase(ready, self.identity, self.index, self.scenario)
        if ready.get("status") != "ready":
            raise RuntimeError("Game scene was not ready")
        report["validation_phase"] = self.identity

    def start(self):
        self.session.resource_context["stage"] = "warmup"
        self.health()

    def capture_start(self):
        if getattr(self.session,'measurement_gate',None) is not None:self.session.measurement_gate()
        self.session.resource_context["stage"] = "capture"
        self.health()
        publish(self.files["go"], self.identity)

    def health(self):
        self.session.health()

    def stop(self):
        self.session.resource_context["stage"] = "finishing"
        if self.files["request"].exists() and not self.files["stop"].exists():
            publish(self.files["stop"], self.identity)

    def finish(self):
        action = self.session.wait(self.files["action"], 10)
        validate_phase(action, self.identity, self.index, self.scenario)
        if action.get("status") != "action_verified":
            raise RuntimeError("Game action did not verify")
        self.stop()
        done = self.session.wait(self.files["done"], 90)
        validate_phase(done, self.identity, self.index, self.scenario)
        if done.get("status") != "phase_complete":
            raise RuntimeError("Game phase did not verify its reset")
        return {**self.identity, "status": "phase_complete", "run_directory": self.run_dir.name,
                "resources_enabled": self.session.resources_enabled}


def main(args):
    suite = args.results.resolve() / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8])
    suite.mkdir(parents=True, exist_ok=False)
    report = {"status": "rejected", "benchmark_accepted": False, "phases": [],
              "mode": "functional_only" if args.functional_only else "functional_frame_capture",
              "scope": "Stationary and real-map player workload validation; mod performance comparisons pending"}
    monitor = session = resources = None
    code = 2
    try:
        automatic=getattr(args,'auto_prepare_request',None)
        if automatic is not None and not args.functional_only:
            raise RuntimeError('Automatic confirmation is restricted to functional-only sessions')
        if not args.functional_only:
            shell = ctypes.WinDLL("shell32", use_last_error=True)
            if not shell.IsUserAnAdmin():
                raise RuntimeError("Start Capture-Minecraft-Session.cmd as administrator once for the whole batch")
        inventory = process_inventory(args.profile)
        if len(inventory["games"]) != 1:
            raise RuntimeError("Expected exactly one matching Minecraft process")
        game = inventory["games"][0]
        directory = args.profile.resolve(strict=True) / "minescript/lab-results"
        candidates = [(arm, files) for arm, files in fresh_sessions(directory, game["pid"]) if not files["claim"].exists()]
        if len(candidates) != 1:
            raise RuntimeError("Run \\labprepare once first; fresh unclaimed sessions found: " + str(len(candidates)))
        arm, files = candidates[0]
        measured=getattr(args,'capture_prepare_request',None)
        if arm.get('auto_prepare_mode')=='functional_only' and (not args.functional_only or automatic is None):
            raise RuntimeError('Automatic functional arm cannot be consumed by manual/frame capture')
        if arm.get('auto_prepare_mode')=='functional_frame_capture' and (args.functional_only or measured is None):
            raise RuntimeError('Automatic measured arm requires its approved broker request')
        if arm.get('auto_prepare_mode') not in (None,'functional_only','functional_frame_capture'):
            raise RuntimeError('Unknown automatic preparation mode')
        if measured is not None:
            if args.functional_only or automatic is not None:raise RuntimeError('Functional mode cannot escalate to a measured request')
            from capture_auto_protocol import validate_capture_request,validate_capture_arm,check_window
            from experiment_protocol import validate_manifest
            from lab_settings import load
            settings=load()
            conditions=read_json(args.profile/'minescript/lab-conditions.json')
            manifest=validate_manifest(read_json(args.profile/'minescript/lab-experiment.json'))
            validate_capture_request(measured,args.profile,conditions,manifest)
            validate_capture_arm(arm,measured)
            window=check_window(settings,measured['measurement_window_nonce'])
            if window.get('diagnostic_only',False)!=measured.get('diagnostic_only',False):raise RuntimeError('Diagnostic request/window policy differs')
        if automatic is not None:
            from auto_prepare_protocol import validate_request,validate_auto_arm
            from experiment_protocol import validate_manifest
            conditions=read_json(args.profile/'minescript/lab-conditions.json')
            manifest=validate_manifest(read_json(args.profile/'minescript/lab-experiment.json'))
            validate_request(automatic,args.profile,conditions,manifest)
            validate_auto_arm(arm,automatic)
        diagnostic=arm.get('diagnostic_only',False)
        if type(diagnostic) is not bool or (diagnostic and automatic is None and measured is None):
            raise RuntimeError('Diagnostic arm requires a matching validated automatic permission')
        report.update(diagnostic_only=diagnostic)
        args.diagnostic_only=diagnostic
        monitor = Monitor(game["pid"])
        with (suite / "session-focus-process.jsonl").open("x", encoding="utf-8") as telemetry:
            session = Session(arm, files, directory, monitor, telemetry)
            if measured is not None:
                session.measurement_gate=lambda:check_window(settings,measured['measurement_window_nonce'])
            session.external_stop = getattr(args, "external_stop", None)
            session.health(require_focus=False)
            order = sampling_order(arm, args)
            report["resource_sampling_order"] = list(order)
            report["purpose"] = "resource_sampling_overhead" if getattr(args, "resource_overhead", False) else "validation"
            if diagnostic:report['purpose']='diagnostic_integration'
            if not getattr(args, "no_resources", False):
                resources = ResourceRecorder(game["pid"], suite / "resource-samples.jsonl")
                session.resources = resources
                session.resources_enabled = True
            else:
                report["resources"] = {"status": "disabled_for_overhead_control"}
            publish(files["claim"], {**session.identity, "controller_pid": __import__("os").getpid(), "mode": report["mode"]})
            shutil.copyfile(files["arm"], suite / "session-arm.json")
            print('Diagnostic controller ready; automatic confirmation needs no chat commands or focus.' if diagnostic else 'Controller ready. Run \\labrun once unless using automatic launch; keep Minecraft focused.',flush=True)
            if automatic is not None:
                session.health(require_focus=True)
                validate_request(automatic,args.profile,conditions,manifest)
                validate_identity(read_json(files['claim']),arm['nonce'],arm['game_pid'])
                publish(files['confirm'],session.identity)
                report['auto_prepare_nonce']=automatic['nonce']
            started = session.wait(files["started"], 300, require_focus=False)
            session.begin(started)
            args.results, args.warmup, args.check_only = suite / "runs", 0, False
            args.results.mkdir(exist_ok=True)
            protocol = batch_protocol(arm)
            phases = schedule(arm["repeats"], protocol)
            for index, scenario in enumerate(phases):
                repeat_index = index if protocol == ROUTE_BATCH else index // 2
                if protocol == ROUTE_BATCH or index % 2 == 0:
                    session.resources_enabled = order[repeat_index]
                    if session.resources_enabled and resources is not None:
                        resources.prime()
                    print("Resource monitoring " + ("ON" if session.resources_enabled else "OFF") + " for repeat " + str(repeat_index + 1), flush=True)
                args.duration = 180 if protocol == ROUTE_BATCH else (90 if scenario == "movement" and arm.get("movement_workload") in ("player_actions_v1", "mob_display_loop_v1", "mob_display_loop_v2", "restworld_rooms_v1") else 10)
                phase = Phase(session, index, scenario)
                print("Validation phase " + str(index + 1) + ": " + scenario, flush=True)
                if args.functional_only:
                    run_dir = args.results / ("functional-" + str(index))
                    run_dir.mkdir(exist_ok=False)
                    try:
                        phase.prepare(game, run_dir, {})
                        until = time.monotonic() + 2
                        while time.monotonic() < until:
                            phase.health()
                            time.sleep(0.1)
                        phase.capture_start()
                        action = session.wait(phase.files["action"], (600 if diagnostic else 180) if scenario == "movement" else 15)
                        validate_phase(action, phase.identity, index, scenario)
                    finally:
                        phase.stop()
                else:
                    if run(args, pair=phase) != 0:
                        detail = "Capture rejected"
                        if phase.run_dir is not None and (phase.run_dir / "result.json").exists():
                            detail = read_json(phase.run_dir / "result.json").get("reason", detail)
                        raise RuntimeError("Validation phase " + str(index + 1) + " failed: " + detail)
                report["phases"].append(phase.finish())
            done = session.wait(files["done"], 90)
            if done.get("status") != "session_validation_passed" or done.get("completed_phases") != len(phases) or done.get("cleanup_error"):
                raise RuntimeError("Game-side completion or cleanup failed")
            shutil.copyfile(files["done"], suite / "game-done.json")
            shutil.copyfile(files["samples"], suite / "game-samples.jsonl")
            report["status"] = "session_validation_passed"
            code = 0
    except Exception as error:
        report["reason"] = str(error)
        print("SESSION REJECTED: " + str(error), flush=True)
    finally:
        if session is not None:
            try:
                session.stop()
            except Exception as error:
                report["stop_error"] = str(error)
                report["status"], code = "rejected", 2
        if monitor is not None:
            monitor.close()
        if resources is not None:
            try:
                report["resources"] = resources.close()
            except Exception as error:
                report["resources"] = {"status": "cleanup_failed", "reason": str(error)}
                report["status"], code = "rejected", 2
        publish(suite / "session-result.json", report)
        print("Session results: " + str(suite), flush=True)
    return code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--presentmon", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--functional-only", action="store_true")
    parser.add_argument("--no-resources", action="store_true", help="Explicit sampling-off control for overhead checks")
    parser.add_argument("--resource-overhead", action="store_true", help="Four-repeat resource sampling ON/OFF/OFF/ON pilot")
    raise SystemExit(main(parser.parse_args()))
