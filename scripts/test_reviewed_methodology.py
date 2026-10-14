"""Mismatch rejection, metric definitions and the one-pass execution gate."""
import copy
import unittest
from pathlib import Path
import tempfile
import subprocess
import sys
import time
from capture_headless import first_frame_ready,presentmon_command
from analyze_session import frame_metrics,segmented_intervals
from analyze_benchmark import verify_contexts,verify_experiment,compare,section_intervals,camera_distance
from analyze_memory import collection_verified
from experiment_protocol import SCHEMA,POLICY,STATE_KEYS,digest


def observed(role="control"):
    files={"mods/sodium.jar":"a"*64,"minescript/labprepare.py":"b"*64}
    changes=[]
    if role=="candidate":files["mods/ixeris.jar"]="c"*64;changes=["mods/ixeris.jar"]
    manifest={"schema":SCHEMA,"configuration_id":"sodium-control" if role=="control" else "ixeris",
              "role":role,"workload":"mob_display_loop_v2","analysis_policy":POLICY,"world_origin_sha256":"d"*64,
              "conditions_sha256":"e"*64,"files":files,"expected_loaded_mods":{"sodium":"0.9.2"},
              "declared_changed_files":changes}
    return {"manifest":manifest,"manifest_sha256":digest(manifest),"actual_files_sha256":digest(files),
            "loaded_mods":{"sodium":"0.9.2"}}


def measured(role="control",fps=200,nonce="a"):
    return {"status":"measurement_valid","experiment":observed(role),"effective_state":{"vsync":False},
            "resources_enabled":False,"nonce":nonce,"suite":role+nonce,"scope":"fixture",
            "repeats":[{"fixed_weight_presented_fps":fps,"sections":[{"camera":[0,0]}]*8}]*3}


class ReviewedMethodology(unittest.TestCase):
    def test_action_readiness_requires_a_matching_first_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"frames.csv"
            self.assertFalse(first_frame_ready(path,1234))
            path.write_text("Application,ProcessID,QPCTime\n")
            self.assertFalse(first_frame_ready(path,1234))
            path.write_text("Application,ProcessID,QPCTime\njavaw.exe,1234,1000\n")
            self.assertTrue(first_frame_ready(path,1234))
            with self.assertRaises(ValueError):first_frame_ready(path,4321)
            path.write_text("Application,ProcessID,QPCTime\njavaw.exe,1234,1000")
            self.assertFalse(first_frame_ready(path,1234))

    def test_inherited_stdout_csv_is_readable_while_child_is_live(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"frames.csv"
            with path.open("xb") as output:
                child=subprocess.Popen([sys.executable,"-c",
                    "import time; print('Application,ProcessID,QPCTime',flush=True); print('javaw.exe,1234,1000',flush=True); time.sleep(10)"],
                    stdout=output,stderr=subprocess.PIPE)
                try:
                    deadline=time.monotonic()+5
                    while not first_frame_ready(path,1234):
                        self.assertIsNone(child.poll())
                        self.assertLess(time.monotonic(),deadline)
                        time.sleep(.05)
                    self.assertIsNone(child.poll())
                finally:
                    child.terminate();child.communicate(timeout=5)
            command=presentmon_command("PresentMon.exe",1234,90,"owned",qpc=True)
            self.assertIn("--output_stdout",command)
            self.assertIn("--qpc_time",command)
            self.assertNotIn("--output_file",command)

    def test_utf16_bom_and_partial_code_unit_wait_for_a_complete_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"frames.csv"
            for value in (b"\xff",b"\xff\xfe", "Application,ProcessID,QPCTime\n".encode("utf-16")):
                path.write_bytes(value);self.assertFalse(first_frame_ready(path,1234))
            data="Application,ProcessID,QPCTime\njavaw.exe,1234,1000\n".encode("utf-16")
            path.write_bytes(data[:-1]);self.assertFalse(first_frame_ready(path,1234))
            path.write_bytes(data);self.assertTrue(first_frame_ready(path,1234))
            with self.assertRaises(ValueError):first_frame_ready(path,4321)
    def test_internal_section_boundary_stall_is_retained_in_full(self):
        rows=[{"QPCTime":str(t),"msBetweenPresents":str(ms)} for t,ms in [(0,0),(100,100),(700,600),(800,100),(900,100)]]
        sections=[{"start_qpc":0,"end_qpc":500},{"start_qpc":500,"end_qpc":900}]
        self.assertEqual(section_intervals(rows,sections,1000),[[100,600],[100,100]])
        self.assertEqual(camera_distance([180,6.5],[-180,6.5]),0)
    def test_one_percent_low_uses_slowest_ceil_count_not_inverse_p99(self):
        metrics=frame_metrics([10]*100+[100])
        self.assertEqual(metrics["one_percent_low_tail_interval_count"],2)
        self.assertAlmostEqual(metrics["one_percent_low_presented_fps"],1000/55)
        self.assertEqual(metrics["stutters_over_50ms"],1)
        self.assertEqual(metrics["total_stutter_over_50ms_time_ms"],100)
        self.assertEqual(metrics["worst_stutter_over_50ms_ms"],100)
        self.assertAlmostEqual(metrics["stutters_over_50ms_per_minute"],60/1.1)

    def test_threshold_strictly_above_50_and_no_spikes_is_not_zero_worst(self):
        metrics=frame_metrics([50,10,10])
        self.assertEqual(metrics["stutters_over_50ms"],0)
        self.assertIsNone(metrics["worst_stutter_over_50ms_ms"])
        self.assertEqual(metrics["total_stutter_over_50ms_time_ms"],0)

    def test_boundary_crossing_excluded_but_true_internal_stall_retained(self):
        rows=[{"QPCTime":str(t),"msBetweenPresents":str(ms)} for t,ms in [(0,0),(100,100),(200,100),(700,500),(800,100),(900,100)]]
        self.assertEqual(segmented_intervals(rows,150,850,1000),[500,100])

    def context_fixture(self):
        state={k:False for k in STATE_KEYS};state.update(foreground=True,paused=False,screen=None)
        state.update(effective_framerate_limit=260,unlimited_framerate_cutoff=260,framerate_throttle_reason="NONE")
        exp=observed();arm={"experiment":exp,"initial_state":state,"repeats":1}
        events=[{"event":"phase_context","phase":p,"scenario":("stationary","movement")[p],
                 "stage":s,"state":state.copy(),"experiment":exp} for p in range(2) for s in ("before","after")]
        events += [{"event":"unscored_route_start","phase":1,"pass":1,"qpc":100},
                   {"event":"player_actions_complete","workload":"mob_display_loop_v2","qpc":200},
                   {"event":"unscored_route_complete","phase":1,"pass":1,"qpc":300},
                   {"event":"action_start","phase":1,"qpc":400}]
        return arm,events

    def test_one_complete_unscored_route_required(self):
        arm,events=self.context_fixture();verify_contexts(arm,events)
        for change in ("missing","extra","incomplete","overlap"):
            data=copy.deepcopy(events)
            if change=="missing":data=[e for e in data if e["event"]!="unscored_route_start"]
            if change=="extra":data.append(copy.deepcopy(data[-4]))
            if change=="incomplete":data=[e for e in data if e["event"]!="player_actions_complete"]
            if change=="overlap":data[-1]["qpc"]=250
            with self.subTest(change=change),self.assertRaises(ValueError):verify_contexts(arm,data)

    def test_old_validation_and_changed_runtime_do_not_become_benchmarks(self):
        with self.assertRaises(ValueError):verify_experiment(None)
        arm,events=self.context_fixture();events[3]["state"]["vsync"]=True
        with self.assertRaises(ValueError):verify_contexts(arm,events)

    def test_grouped_control_drift_and_undeclared_instrumentation_changes_rejected(self):
        self.assertTrue(compare(measured(),measured("candidate",220),measured(fps=201,nonce="b"))["benchmark_accepted"])
        with self.assertRaises(ValueError):compare(measured(),measured("candidate"))
        with self.assertRaises(ValueError):compare(measured(),measured("candidate"),measured(fps=230,nonce="b"))
        value=measured("candidate");value["effective_state"]["vsync"]=True
        with self.assertRaises(ValueError):compare(measured(),value,measured(nonce="b"))

    def test_unknown_young_only_and_unsettled_collection_are_inconclusive(self):
        c={"procedure":"explicit-gc-observed-then-3s-settle-v1","observed_collection":True,"stable_collection_counters":True,
           "before_gc":{"G1 Old Generation":{"count":0}},"first":{"gc":{"G1 Old Generation":{"count":1}}},
           "second":{"gc":{"G1 Old Generation":{"count":1}}}}
        self.assertTrue(collection_verified(c))
        for name in ("unknown","young","unstable"):
            other=copy.deepcopy(c)
            if name=="unknown":other["before_gc"]={}
            if name=="young":other["before_gc"]["G1 Old Generation"]["count"]=1
            if name=="unstable":other["second"]["gc"]["G1 Old Generation"]["count"]=2
            self.assertFalse(collection_verified(other))


if __name__=="__main__":unittest.main()
