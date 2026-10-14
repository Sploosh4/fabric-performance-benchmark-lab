"""Synthetic raw CSV/handshake dry run; fixtures are never laptop benchmark evidence."""
import csv
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from analyze_benchmark import score_suite,WAYPOINTS
from experiment_protocol import STATE_KEYS
from session_protocol import OWNER
from test_reviewed_methodology import observed


def synthetic_route(base,phase,phase_markers=False):
    events=[]
    for i,(a,b) in enumerate(zip(WAYPOINTS,WAYPOINTS[1:])):
        axis=0 if a[0]!=b[0] else 2
        yaw=(-90 if b[0]>a[0] else 90) if axis==0 else (0 if b[2]>a[2] else 180)
        start=base+i*4_000_000
        events.append({"event":"mob_route_segment_start","segment":i,"start":a,"target":b,"orientation":[yaw,6.5],"sprint":i in (0,6),"qpc":start})
        for n in range(1,11):events.append({"event":"route_path_sample","segment":i,"position":[x+(y-x)*n/10 for x,y in zip(a,b)],"qpc":start+n*250_000})
        events += [{"event":"corner_correction_start","segment":i,"qpc":start+2_600_000},
                   {"event":"corner_correction_end","segment":i,"qpc":start+2_800_000},
                   {"event":"player_action_verified","action":"sprint" if i in (0,6) else "walk","segment":i,
                    "sprinting_observed":i in (0,6),"qpc":start+2_900_000}]
        if i<6:events += [{"event":"mob_area_waypoint","nearby_display_entities":20,"qpc":start+3_000_000},
                         {"event":"mob_camera_checkpoint","segment":i,"position":b,"orientation":[0,0],"target":[0.5,102,26.5],"qpc":start+3_100_000}]
        events.append({"event":"mob_route_segment_end","segment":i,"position":b,"qpc":start+3_500_000})
    for i,action in enumerate(["jump"]*3+["punch"]*5):events.append({"event":"player_action_verified","action":action,"qpc":base+28_000_000+i*300_000})
    events.append({"event":"player_actions_complete","workload":"mob_display_loop_v2","qpc":base+31_000_000})
    return events


def make_suite(root):
    nonce="a"*32;pid=1234;exp=observed()
    state={k:False for k in STATE_KEYS}
    state.update(effective_framerate_limit=260,unlimited_framerate_cutoff=260,framerate_throttle_reason="NONE",foreground=True,paused=False,screen=None)
    identity={"owner":OWNER,"nonce":nonce,"game_pid":pid,"benchmark_accepted":False}
    arm={**identity,"movement_workload":"mob_display_loop_v2","repeats":3,"initial_issues":[],"initial_state":state,"experiment":exp}
    report={**identity,"status":"session_validation_passed","purpose":"validation","phases":[]}
    done={**identity,"status":"session_validation_passed","completed_phases":6}
    events=[]
    def write(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
    write(root/"session-arm.json",arm);write(root/"game-done.json",done)
    for phase in range(6):
        scenario=("stationary","movement")[phase%2];folder=root/"runs"/str(phase);folder.mkdir(parents=True)
        base=1_000_000_000+phase*150_000_000
        if scenario=="movement":
            events.append({"event":"unscored_route_start","phase":phase,"pass":1,"qpc":base-40_000_000})
            events+=synthetic_route(base-39_000_000,phase)
            events.append({"event":"unscored_route_complete","phase":phase,"pass":1,"qpc":base-7_000_000})
        events += [{"event":"phase_context","phase":phase,"scenario":scenario,"stage":"before","state":state,"experiment":exp,"qpc":base-100_000},
                   {"event":"action_start","phase":phase,"scenario":scenario,"qpc":base+10_000}]
        if scenario=="movement":events+=synthetic_route(base+100_000,phase)
        duration=60 if scenario=="movement" else 10
        raw=folder/"frames.csv"
        with raw.open("w",newline="") as stream:
            columns=["Application","ProcessID","SwapChainAddress","Runtime","TimeInSeconds","msBetweenPresents","QPCTime"]
            writer=csv.DictWriter(stream,fieldnames=columns);writer.writeheader()
            for tick in range(duration*100+1):writer.writerow({"Application":"javaw.exe","ProcessID":pid,"SwapChainAddress":"0x123",
                "Runtime":"Other","TimeInSeconds":tick/100,"msBetweenPresents":0 if tick==0 else 10,"QPCTime":base+tick*10_000})
        write(folder/"result.json",{"status":"tool_check_passed","csv_sha256":hashlib.sha256(raw.read_bytes()).hexdigest(),"game":{"pid":pid},"duration_seconds":duration})
        (folder/"power-focus.jsonl").write_text(json.dumps({"ac_connected":True,"minecraft_foreground":True,"original_game_alive":True})+"\n")
        events.append({"event":"phase_context","phase":phase,"scenario":scenario,"stage":"after","state":state,"experiment":exp,"qpc":base+(duration+1)*1_000_000})
        report["phases"].append({**identity,"phase":phase,"scenario":scenario,"run_directory":str(phase),"resources_enabled":False})
    events.sort(key=lambda e:e["qpc"])
    (root/"game-samples.jsonl").write_text("".join(json.dumps({"nonce":nonce,"benchmark_accepted":False,"qpc_frequency":1_000_000,**e})+"\n" for e in events))
    write(root/"session-result.json",report)


class EndToEnd(unittest.TestCase):
    def test_diagnostic_analysis_preserves_the_label_and_rejects_policy_mismatch(self):
        from analyze_session import analyze
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);make_suite(root)
            for name in ('session-arm.json','session-result.json'):
                path=root/name;value=json.loads(path.read_text());value['diagnostic_only']=True
                path.write_text(json.dumps(value))
            analysis=analyze(root)
            self.assertTrue(analysis['diagnostic_only'])
            self.assertEqual(analysis['purpose'],'diagnostic_integration')
            self.assertFalse(analysis['benchmark_accepted'])
            with self.assertRaisesRegex(ValueError,'Diagnostic integration'):score_suite(root)
            report=root/'session-result.json';value=json.loads(report.read_text());value['diagnostic_only']=False
            report.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError,'policy differs'):analyze(root)

    def test_diagnostic_suites_cannot_be_promoted_to_measurements(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);make_suite(root)
            report_path=root/'session-result.json';report=json.loads(report_path.read_text())
            report['diagnostic_only']=True;report['purpose']='diagnostic_integration';report_path.write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError,'Diagnostic integration'):score_suite(root)

    def test_utf16_raw_stdout_evidence_scores_without_rewriting_frame_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);make_suite(root)
            before=score_suite(root)
            for raw in (root/"runs").glob("*/frames.csv"):
                text=raw.read_text(encoding="utf-8")
                raw.write_text(text,encoding="utf-16",newline="")
                report_path=raw.parent/"result.json"
                report=json.loads(report_path.read_text())
                report["csv_sha256"]=hashlib.sha256(raw.read_bytes()).hexdigest()
                report_path.write_text(json.dumps(report))
            after=score_suite(root)
            self.assertEqual(after["status"],"measurement_valid")
            self.assertFalse(after["benchmark_accepted"])
            self.assertEqual([r["fixed_weight_presented_fps"] for r in before["repeats"]],
                             [r["fixed_weight_presented_fps"] for r in after["repeats"]])

    def test_raw_valid_fixture_scored_but_not_promoted_as_comparison(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);make_suite(root);result=score_suite(root)
            self.assertEqual(result["status"],"measurement_valid")
            self.assertFalse(result["benchmark_accepted"])
            self.assertEqual(len(result["repeats"]),3)
            self.assertAlmostEqual(result["repeats"][0]["fixed_weight_presented_fps"],100)
            self.assertEqual(result["repeats"][0]["sections"][0]["metrics"]["one_percent_low_presented_fps"],100)

    def test_raw_tampering_and_missing_warmup_rejected(self):
        for change in ("csv","warmup"):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);make_suite(root)
                if change=="csv":
                    with (root/"runs/0/frames.csv").open("a") as f:f.write("tampered\n")
                else:
                    path=root/"game-samples.jsonl"
                    rows=[json.loads(s) for s in path.read_text().splitlines()]
                    path.write_text("".join(json.dumps(r)+"\n" for r in rows if r["event"]!="unscored_route_complete"))
                with self.assertRaises(ValueError):score_suite(root)


if __name__=="__main__":unittest.main()
