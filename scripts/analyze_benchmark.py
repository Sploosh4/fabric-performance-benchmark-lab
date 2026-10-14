"""Score pinned, matched experiments without changing validation evidence."""
import argparse
from collections import Counter
import csv
import json
import math
from pathlib import Path
import statistics

from analyze_session import analyze, segmented_intervals, frame_metrics
from experiment_protocol import digest, validate_manifest, matched_state, POLICY
from frame_csv import csv_encoding
from room_route_protocol import WORKLOAD as ROOM_WORKLOAD
from rooms_analysis import scene_evidence, scored_action_events
from session_protocol import batch_protocol, schedule

WAYPOINTS = ((1.5, 101, 0.5), (1.5, 101, 17.5), (-13.5, 101, 17.5),
             (-13.5, 101, 35.5), (13.5, 101, 35.5), (13.5, 101, 17.5),
             (1.5, 101, 17.5), (1.5, 101, 0.5))


def distance(a, b):
    if len(a) != len(b) or any(not math.isfinite(float(x)) for x in (*a, *b)):
        raise ValueError("Invalid position/orientation")
    return max(abs(x-y) for x,y in zip(a,b))


def camera_distance(a,b):
    distance(a,b)  # Validate finite values and shape before angular wrapping.
    if len(a)!=2:raise ValueError("Invalid camera orientation")
    return max(abs((a[0]-b[0]+180)%360-180),abs(a[1]-b[1]))


def section_intervals(rows,sections,frequency):
    """Assign complete route frames by their earlier endpoint; keep boundary stalls."""
    begin,end=sections[0]["start_qpc"],sections[-1]["end_qpc"]
    segmented_intervals(rows,begin,end,frequency)  # Validate timestamps/intervals.
    buckets=[[] for _ in sections]
    previous=None
    for row in rows:
        current=int(row["QPCTime"])
        if previous is not None and begin<=previous<current<=end:
            for index,section in enumerate(sections):
                if section["start_qpc"]<=previous<section["end_qpc"]:
                    buckets[index].append(float(row["msBetweenPresents"]))
                    break
            else:raise ValueError("Complete route frame has no section")
        previous=current
    if any(not bucket for bucket in buckets):raise ValueError("Empty matched section")
    return buckets


def verify_experiment(observed):
    if not isinstance(observed, dict):
        raise ValueError("No pinned experiment evidence; validation only")
    manifest = validate_manifest(observed["manifest"])
    if observed["manifest_sha256"] != digest(manifest) or observed["actual_files_sha256"] != digest(manifest["files"]):
        raise ValueError("Experiment identity/hash differs")
    for mod, version in manifest["expected_loaded_mods"].items():
        if observed["loaded_mods"].get(mod) != version:
            raise ValueError("Loaded mod version differs")
    return manifest


def verify_contexts(arm, events):
    manifest = verify_experiment(arm.get("experiment"))
    state = matched_state(arm["initial_state"])
    if state["vsync"] is not False or state["unlimited_framerate_cutoff"]!=260 or state["effective_framerate_limit"]<260 or state["framerate_throttle_reason"]!="NONE":
        raise ValueError("Uncapped VSync-off frame conditions required")
    protocol = batch_protocol(arm)
    if protocol != batch_protocol(manifest):
        raise ValueError("Batch protocol differs from pinned experiment")
    phases = schedule(arm["repeats"], protocol)
    expected = {(phase, stage) for phase in range(len(phases)) for stage in ("before", "after")}
    seen = set()
    for event in (e for e in events if e["event"] == "phase_context"):
        key = (event["phase"], event["stage"])
        if key not in expected or key in seen or event["scenario"] != phases[event["phase"]]:
            raise ValueError("Phase context duplicated/missing/wrong scenario")
        if event["experiment"] != arm["experiment"] or matched_state(event["state"]) != state:
            raise ValueError("Configuration or effective conditions changed")
        if not event["state"]["foreground"] or event["state"]["paused"] or event["state"]["screen"] is not None:
            raise ValueError("Phase world was not active")
        seen.add(key)
    if seen != expected:
        raise ValueError("Complete before/after phase context required")
    movement_phases = [i for i,s in enumerate(phases) if s=="movement"]
    all_warmups = [e for e in events if e["event"] in ("unscored_route_start","unscored_route_complete")]
    if len(all_warmups) != 2*len(movement_phases) or any(e["phase"] not in movement_phases for e in all_warmups):
        raise ValueError("Unexpected unscored route pass")
    for phase in movement_phases:
        warmups=[e for e in events if e["event"] in ("unscored_route_start","unscored_route_complete") and e["phase"]==phase]
        if [e["event"] for e in warmups] != ["unscored_route_start","unscored_route_complete"] or any(e["pass"]!=1 for e in warmups):
            raise ValueError("Exactly one complete unscored route pass required")
        begin,end=warmups
        matching=[e for e in events if e["event"]=="player_actions_complete" and begin["qpc"]<e["qpc"]<end["qpc"]]
        action=[e for e in events if e["event"]=="action_start" and e["phase"]==phase]
        if len(matching)!=1 or matching[0].get("workload")!=manifest["workload"] or len(action)!=1 or not begin["qpc"]<end["qpc"]<action[0]["qpc"]:
            raise ValueError("Warmup was incomplete or overlapped scoring")
        if manifest["workload"]==ROOM_WORKLOAD:
            scene_evidence([e for e in events if begin["qpc"]<e["qpc"]<end["qpc"]],events[0]["qpc_frequency"])
    return manifest, state


def section_evidence(events):
    starts = [e for e in events if e["event"] == "mob_route_segment_start"]
    ends = [e for e in events if e["event"] == "mob_route_segment_end"]
    complete = [e for e in events if e["event"] == "player_actions_complete"]
    if len(starts) != 7 or len(ends) != 7 or len(complete) != 1:
        raise ValueError("Matched movement section markers required")
    sections = []
    for i, (start, end) in enumerate(zip(starts, ends)):
        if start["segment"] != i or end["segment"] != i or not start["qpc"] < end["qpc"]:
            raise ValueError("Movement section order differs")
        if distance(start["start"], WAYPOINTS[i]) > POLICY["endpoint_tolerance_blocks"] or distance(start["target"], WAYPOINTS[i+1]) > 0.001:
            raise ValueError("Route start/target differs")
        if distance(end["position"], WAYPOINTS[i+1]) > POLICY["endpoint_tolerance_blocks"]:
            raise ValueError("Route endpoint differs")
        axis = 0 if WAYPOINTS[i][0] != WAYPOINTS[i+1][0] else 2
        expected_yaw = (-90 if WAYPOINTS[i+1][0] > WAYPOINTS[i][0] else 90) if axis == 0 else (0 if WAYPOINTS[i+1][2] > WAYPOINTS[i][2] else 180)
        if camera_distance(start["orientation"], [expected_yaw, 6.5]) > POLICY["camera_tolerance_degrees"] or start["sprint"] != (i in (0,6)):
            raise ValueError("Movement camera/sprint differs")
        samples = [e for e in events if e["event"] == "route_path_sample" and e["segment"] == i]
        if len(samples) < POLICY["minimum_path_samples"]:
            raise ValueError("Insufficient trajectory evidence")
        positions = [start["start"]] + [e["position"] for e in samples] + [end["position"]]
        low, high = sorted((WAYPOINTS[i][axis], WAYPOINTS[i+1][axis]))
        for pos in positions:
            if len(pos) != 3 or any(not math.isfinite(float(v)) for v in pos):
                raise ValueError("Invalid trajectory")
            if any(abs(pos[a]-WAYPOINTS[i][a]) > POLICY["path_tolerance_blocks"] for a in range(3) if a != axis) or not low-0.35 <= pos[axis] <= high+0.35:
                raise ValueError("Trajectory left the matched scene")
        # A long stall yields repeated positions, not an excuse to trim frames.
        if any(distance(a,b) > POLICY["maximum_sample_gap_blocks"] for a,b in zip(positions,positions[1:])):
            raise ValueError("Trajectory coverage gap")
        if any(not start["qpc"] <= e["qpc"] <= end["qpc"] for e in samples):
            raise ValueError("Trajectory sample outside its section")
        cameras = [e for e in events if e["event"] == "mob_camera_checkpoint" and e["segment"] == i]
        if i < 6:
            if len(cameras) != 1 or distance(cameras[0]["position"], WAYPOINTS[i+1]) > 0.25:
                raise ValueError("Mob camera checkpoint missing")
            camera = cameras[0]
            if camera["target"] != [0.5,102,26.5] or not start["qpc"] <= camera["qpc"] <= end["qpc"]:
                raise ValueError("Mob camera target/window differs")
        elif cameras:
            raise ValueError("Unexpected camera checkpoint")
        next_start = starts[i+1]["qpc"] if i < 6 else end["qpc"]
        if next_start < end["qpc"]:
            raise ValueError("Overlapping movement sections")
        corrections = [e for e in events if e["event"] in ("corner_correction_start", "corner_correction_end") and e["segment"] == i]
        if [e["event"] for e in corrections] != ["corner_correction_start", "corner_correction_end"]:
            raise ValueError("Correction timing missing")
        sections.append({"section": i, "start_qpc": start["qpc"], "end_qpc": next_start,
                         "path_samples": len(samples), "camera": cameras[0]["orientation"] if cameras else None,
                         "correction_qpc": corrections[1]["qpc"]-corrections[0]["qpc"]})
    if complete[0]["qpc"] <= ends[-1]["qpc"]:
        raise ValueError("Action section completion differs")
    sections.append({"section": 7, "start_qpc": ends[-1]["qpc"], "end_qpc": complete[0]["qpc"],
                     "path_samples": None, "camera": None, "correction_qpc": 0})
    return sections


def score_suite(suite):
    suite = Path(suite).resolve(strict=True)
    report = json.loads((suite / "session-result.json").read_text())
    arm = json.loads((suite / "session-arm.json").read_text())
    if report.get('diagnostic_only') or arm.get('diagnostic_only') or report.get('purpose')=='diagnostic_integration':
        raise ValueError('Diagnostic integration captures cannot be used as performance comparison measurements')
    validated = analyze(suite)  # Revalidate raw CSV/hash/power/focus/action evidence.
    arm = json.loads((suite / "session-arm.json").read_text())
    report = json.loads((suite / "session-result.json").read_text())
    events = [json.loads(s) for s in (suite / "game-samples.jsonl").read_text().splitlines()]
    manifest, state = verify_contexts(arm, events)
    if arm["repeats"] < POLICY["minimum_measured_repeats"] or report.get("purpose") != "validation":
        raise ValueError("Not a measured experiment batch (minimum three repeats)")
    enabled = {p["resources_enabled"] for p in validated["phases"]}
    if len(enabled) != 1:
        raise ValueError("Mixed resource-sampling conditions")
    for e in events:
        if e["event"] == "heap_snapshot" and "retention_status" in e:
            raise ValueError("Collection procedure must run outside frame captures")
    repeats = []
    frequency = validated["qpc_frequency"]
    action_starts = [i for i,e in enumerate(events) if e["event"] == "action_start"]
    for phase in validated["phases"]:
        if phase["scenario"] != "movement":
            continue
        index = phase["phase"]
        window_events = events[action_starts[index]:action_starts[index+1] if index+1 < len(action_starts) else len(events)]
        rooms=manifest["workload"]==ROOM_WORKLOAD
        if rooms:
            window_events=scored_action_events(window_events)
        sections = scene_evidence(window_events,frequency) if rooms else section_evidence(window_events)
        raw = (suite / "runs" / report["phases"][index]["run_directory"] / "frames.csv").resolve(strict=True)
        with raw.open(encoding=csv_encoding(raw), newline="") as f:
            rows = list(csv.DictReader(f))
        buckets=([segmented_intervals(rows,s["start_qpc"],s["end_qpc"],frequency) for s in sections]
                 if rooms else section_intervals(rows,sections,frequency))
        for section,values in zip(sections,buckets):
            section["metrics"] = frame_metrics(values)
            section["metrics"]["stutters_over_50ms_per_minute"] = section["metrics"]["stutters_over_50ms"] * 60 / section["metrics"]["analyzed_seconds"]
            section["duration_seconds"] = (section["end_qpc"]-section["start_qpc"])/frequency
            section["frame_assignment"]=("Both endpoints inside the scene; teleport crossings excluded, complete in-scene stalls retained" if rooms else "Full complete-route intervals assigned by earlier QPC endpoint; boundary stalls retained")
        weighted_ms = sum(w * 1000/s["metrics"]["average_presented_fps"] for w,s in zip(manifest["analysis_policy"]["scene_weights"], sections))
        repeats.append({"phase": index, "sections": sections, "fixed_weight_presented_fps": 1000/weighted_ms})
    return {"schema": "modpack-benchmark-v1", "status": "measurement_valid",
            "benchmark_accepted": False, "suite": str(suite), "nonce": arm["nonce"], "game_pid": arm["game_pid"],
            "experiment": arm["experiment"], "effective_state": state, "resources_enabled": enabled.pop(),
            "repeats": repeats, "phases": validated["phases"],
            "scope": "Presented frames in the pinned RestWorld scenes; not displayed FPS/input latency or all workloads"}


def compare(control, candidate, control_after=None):
    a, b = verify_experiment(control["experiment"]), verify_experiment(candidate["experiment"])
    policy=a["analysis_policy"]
    if batch_protocol(a) != batch_protocol(b):
        raise ValueError("Experiment comparison differs: batch protocol")
    if control["status"] != "measurement_valid" or candidate["status"] != "measurement_valid":
        raise ValueError("Unverified measurement")
    if a["role"] != "control" or b["role"] != "candidate" or a["configuration_id"] == b["configuration_id"]:
        raise ValueError("Expected distinct control/candidate configurations")
    for key in ("workload", "world_origin_sha256", "world_restored_tree_sha256", "conditions_sha256", "analysis_policy"):
        if a.get(key) != b.get(key):
            raise ValueError("Experiment comparison differs: " + key)
    if control["effective_state"] != candidate["effective_state"] or control["resources_enabled"] != candidate["resources_enabled"]:
        raise ValueError("Runtime/graphics/sampling conditions differ")
    if control_after is None:
        raise ValueError("Grouped return-to-control evidence required before accepting comparison")
    if control_after["experiment"] != control["experiment"] or control_after["effective_state"] != control["effective_state"] or control_after["resources_enabled"] != control["resources_enabled"]:
        raise ValueError("Return-to-control configuration differs")
    if control_after["status"] != "measurement_valid" or control_after["nonce"] == control["nonce"]:
        raise ValueError("Fresh verified return-to-control batch required")
    differences = {key for key in a["files"].keys() | b["files"].keys() if a["files"].get(key) != b["files"].get(key)}
    if not differences or differences != set(b.get("declared_changed_files", [])):
        raise ValueError("Candidate changes differ from declared isolated experiment")
    if any(not key.startswith(("mods/", "config/")) for key in differences):
        raise ValueError("Instrumentation changed between comparisons")
    for ra in control["repeats"]:
        for rb in candidate["repeats"]:
            for sa,sb in zip(ra["sections"],rb["sections"]):
                if sa["camera"] is not None and camera_distance(sa["camera"],sb["camera"]) > POLICY["camera_tolerance_degrees"]:
                    raise ValueError("Camera exposure differs between configurations")
                left,right=sa.get("camera_checkpoints",[]),sb.get("camera_checkpoints",[])
                if len(left)!=len(right) or any(camera_distance(c,d)>policy["camera_tolerance_degrees"] for c,d in zip(left,right)):
                    raise ValueError("Room camera exposure differs between configurations")
    ac = [r["fixed_weight_presented_fps"] for r in control["repeats"]]
    bc = [r["fixed_weight_presented_fps"] for r in candidate["repeats"]]
    ending = [r["fixed_weight_presented_fps"] for r in control_after["repeats"]]
    drift = 100*(statistics.median(ending)/statistics.median(ac)-1)
    if abs(drift) > policy["maximum_control_drift_pct"]:
        raise ValueError("Control performance drift exceeds predeclared tolerance")
    gain = 100*(statistics.median(bc)/statistics.median(ac)-1)
    scenes=[]
    for index,weight in enumerate(policy["scene_weights"]):
        row={"section":index,"fixed_weight":weight,"metrics":{}}
        for metric in ("average_presented_fps","one_percent_low_presented_fps","p95_ms","p99_ms",
                       "stutters_over_50ms_per_minute","worst_frame_ms","worst_stutter_over_50ms_ms",
                       "total_stutter_over_50ms_time_ms"):
            left=[r["sections"][index].get("metrics",{}).get(metric) for r in control["repeats"]]
            right=[r["sections"][index].get("metrics",{}).get(metric) for r in candidate["repeats"]]
            l=[v for v in left if v is not None];r=[v for v in right if v is not None]
            row["metrics"][metric]={"control_values":left,"candidate_values":right,
                                    "control_median":statistics.median(l) if l else None,
                                    "candidate_median":statistics.median(r) if r else None}
        scenes.append(row)
    return {"schema": "modpack-comparison-v1", "status": "comparison_accepted", "benchmark_accepted": True,
            "control_suite": control["suite"], "candidate_suite": candidate["suite"],
            "control_configuration": a["configuration_id"], "candidate_configuration": b["configuration_id"],
            "changed_files": sorted(differences), "control_presented_fps": ac, "candidate_presented_fps": bc,
            "median_fixed_weight_presented_fps_change_pct": gain,
            "return_to_control_suite": control_after["suite"], "control_drift_pct": drift,
            "scene_comparisons":scenes,"one_percent_low_definition":policy["one_percent_low_definition"],
            "decision": "screening_only_requires_drift_and_correctness_review",
            "scope": control["scope"], "statistical_significance_established": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite", type=Path)
    parser.add_argument("--control", type=Path)
    parser.add_argument("--control-after", type=Path)
    args = parser.parse_args()
    target = args.suite / ("benchmark-comparison.json" if args.control else "benchmark-measurement.json")
    result = {"schema": "modpack-benchmark-v1", "benchmark_accepted": False, "status": "rejected"}
    try:
        measured = score_suite(args.suite)
        result = compare(score_suite(args.control), measured, score_suite(args.control_after) if args.control_after else None) if args.control else measured
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as error:
        result["reason"] = str(error)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
    print(str(target))
    return 2 if result["status"] == "rejected" else 0


if __name__ == "__main__":
    raise SystemExit(main())
