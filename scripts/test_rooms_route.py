"""Scene, transition, sprint-jump and capture-boundary checks; synthetic evidence only."""
import copy
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from room_route_protocol import WORKLOAD,SCENES,ROOM_POLICY,walk_yaw
from rooms_analysis import scene_evidence
from analyze_session import segmented_intervals
from analyze_benchmark import score_suite
from experiment_protocol import digest
from test_benchmark_end_to_end import make_suite


def route(base=1000,frequency=1000):
    out=[];tick=base
    for index,s in enumerate(SCENES):
        if index:
            out.append({"event":"room_transition_start","scene":s["id"],"qpc":tick})
            tick+=frequency
            out.append({"event":"room_transition_complete","scene":s["id"],"qpc":tick});tick+=10
        content={"display_mobs":20} if index==0 else {"paintings":10} if index==1 else {"redstone_display_blocks":13}
        out.append({"event":"room_scene_start","scene":s["id"],"position":s["points"][0],"content":content,"qpc":tick});tick+=10
        for leg,(a,b) in enumerate(zip(s["points"],s["points"][1:])):
            sprint=index==0 and leg==0;start=tick
            out.append({"event":"room_route_leg_start","scene":s["id"],"leg":leg,"position":a,"target":b,
                        "sprint":sprint,"orientation":[walk_yaw(a,b),6.5],"qpc":start})
            for n in range(1,11):
                position=[x+(y-x)*n/10 for x,y in zip(a,b)]
                if sprint and n in (4,8):position[1]=101.8
                out.append({"event":"room_route_path_sample","scene":s["id"],"leg":leg,"position":position,"qpc":start+n*frequency//4})
            if sprint:
                for j in range(2):out.append({"event":"player_action_verified","action":"jump","scene":s["id"],"leg":0,
                    "jump_index":j,"observed_height":101.8,"ground_y":101.,"sprinting_observed":True,"qpc":start+(j+1)*frequency+1})
            tick=start+3*frequency
            out.append({"event":"room_route_leg_end","scene":s["id"],"leg":leg,"position":b,"sprinting_observed":sprint,"qpc":tick});tick+=10
            out.append({"event":"player_action_verified","action":"sprint" if sprint else "walk","scene":s["id"],"leg":leg,"qpc":tick});tick+=10
            for view,yaw in enumerate(s["camera_yaws"] or (None,)):
                orientation=[yaw,s["camera_pitch"]] if yaw is not None else [0.,5.]
                out.append({"event":"room_camera_begin","scene":s["id"],"leg":leg,"view":view,"position":b,
                            "orientation":orientation,"target":list(s["camera_target"]) if "camera_target" in s else None,"qpc":tick})
                tick+=int(s["camera_hold_seconds"]*frequency)
                out.append({"event":"room_camera_end","scene":s["id"],"leg":leg,"view":view,"orientation":orientation,"qpc":tick});tick+=10
        out.append({"event":"room_scene_complete","scene":s["id"],"position":s["points"][-1],"qpc":tick});tick+=10
    out.append({"event":"player_actions_complete","workload":WORKLOAD,"qpc":tick})
    return sorted(out,key=lambda e:e["qpc"])


class RoomsRoute(unittest.TestCase):
    def test_corridor_survey_handles_y_before_z_and_still_rejects_real_changes(self):
        changed={}
        def kind(pos):return changed.get(pos,"minecraft:smooth_quartz" if pos[1]==100 else "minecraft:air")
        class State:
            def __init__(self,pos):self.pos=pos
            def __str__(self):return "Block{"+kind(self.pos)+"}"
            def getCollisionShape(self,*args):return SimpleNamespace(isEmpty=lambda:kind(self.pos) in ("minecraft:pale_oak_wall_sign","minecraft:stone_button"))
        def stream(box):
            x0,y0,z0,x1,y1,z1=box
            values=[State((x,y,z)) for z in range(z0,z1+1) for y in range(y0,y1+1) for x in range(x0,x1+1)]
            return SimpleNamespace(toList=lambda:"["+", ".join(map(str,values))+"]")
        level=SimpleNamespace(hasChunkAt=lambda pos:True,getBlockStates=stream,getBlockState=State)
        spec=importlib.util.spec_from_file_location("rooms_survey",Path(__file__).resolve().parents[1]/"scenarios/lab_rooms_actions.py")
        module=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{"minescript":Mock(),"java":SimpleNamespace(JavaClass=lambda name:lambda *args:tuple(args)),
             "lab_common":SimpleNamespace(MC=SimpleNamespace(level=level),guard_world=Mock()),
             "lab_player_actions":SimpleNamespace(PlayerActions=object),
             "lab_validation_core":SimpleNamespace(wait_live=Mock(),wait_position=Mock(),release_inputs=Mock(),
                 block_kind=lambda text:text.removeprefix("Block{").removesuffix("}"))}):
            spec.loader.exec_module(module)
            actions=module.RoomActions()
            for a,b in (((1.5,101,.5),(1.5,101,17.5)),((1.5,101,17.5),(-13.5,101,17.5))):
                self.assertGreater(actions.survey_leg(SCENES[0],a,b),1)
            changed[(1,101,2)]="minecraft:pale_oak_wall_sign"
            changed[(1,101,3)]="minecraft:stone_button"
            self.assertGreater(actions.survey_leg(SCENES[0],SCENES[0]["points"][0],SCENES[0]["points"][1]),1)
            changed.clear()
            changed[(1,100,1)]="minecraft:air"
            with self.assertRaisesRegex(RuntimeError,"Changed room floor at 1,100,1"):
                actions.survey_leg(SCENES[0],SCENES[0]["points"][0],SCENES[0]["points"][1])
            changed.clear();changed[(1,102,1)]="minecraft:stone"
            with self.assertRaisesRegex(RuntimeError,"Room corridor obstacle at 1,102,1"):
                actions.survey_leg(SCENES[0],SCENES[0]["points"][0],SCENES[0]["points"][1])

    def test_valid_three_rooms_and_two_jumps_inside_sprint(self):
        sections=scene_evidence(route(),1000)
        self.assertEqual([s["scene"] for s in sections],["mobs","paintings","redstone"])
        self.assertLess(sum(s["end_qpc"]-s["start_qpc"] for s in sections),sections[-1]["end_qpc"]-sections[0]["start_qpc"])

    def test_missing_scene_camera_jump_and_wrong_pose_rejected(self):
        for change in ("scene","camera","jump","standing_jump","punch","teleport","path","camera_angle"):
            events=route()
            if change=="scene":events=[e for e in events if not(e["event"]=="room_scene_complete" and e["scene"]=="paintings")]
            elif change=="camera":events.remove(next(e for e in events if e["event"]=="room_camera_end"))
            elif change=="jump":events.remove(next(e for e in events if e.get("action")=="jump"))
            elif change=="standing_jump":next(e for e in events if e.get("action")=="jump")["sprinting_observed"]=False
            elif change=="punch":events.append({"event":"player_action_verified","action":"punch","qpc":999999})
            elif change=="teleport":events.append({"event":"room_transition_start","qpc":1020})
            elif change=="path":next(e for e in events if e["event"]=="room_route_path_sample")["position"][0]+=1
            elif change=="camera_angle":next(e for e in events if e["event"]=="room_camera_begin" and e["scene"]=="paintings")["orientation"][0]+=20
            with self.subTest(change=change),self.assertRaises(ValueError):scene_evidence(events,1000)

    def test_transition_and_crossing_intervals_excluded_but_scene_stall_retained(self):
        rows=[{"QPCTime":str(t),"msBetweenPresents":str(ms)} for t,ms in [(0,0),(100,100),(600,500),(700,100),(2000,1300),(2100,100),(2600,500)]]
        self.assertEqual(segmented_intervals(rows,0,700,1000),[100,500,100])
        self.assertEqual(segmented_intervals(rows,2000,2600,1000),[100,500])

    def test_raw_three_repeat_rooms_fixture_scores_with_equal_scene_weights(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);make_suite(root)
            arm=json.loads((root/"session-arm.json").read_text());arm["movement_workload"]=WORKLOAD
            manifest=arm["experiment"]["manifest"];manifest["workload"]=WORKLOAD;manifest["analysis_policy"]=ROOM_POLICY
            arm["experiment"]["manifest_sha256"]=digest(manifest)
            (root/"session-arm.json").write_text(json.dumps(arm))
            old=[json.loads(line) for line in (root/"game-samples.jsonl").read_text().splitlines()]
            events=[e for e in old if e["event"] in ("phase_context","action_start")]
            for e in events:
                if e["event"]=="phase_context":e["experiment"]=arm["experiment"]
            for phase in (1,3,5):
                base=1_000_000_000+phase*150_000_000
                events+=[{"event":"unscored_route_start","phase":phase,"pass":1,"qpc":base-40_000_000}]
                events+=route(base-39_000_000,1_000_000)
                events+=[{"event":"unscored_route_complete","phase":phase,"pass":1,"qpc":base-1_000_000}]
                events+=route(base+100_000,1_000_000)
            events.sort(key=lambda e:e["qpc"])
            (root/"game-samples.jsonl").write_text("".join(json.dumps({"nonce":arm["nonce"],"benchmark_accepted":False,"qpc_frequency":1_000_000,**e})+"\n" for e in events))
            result=score_suite(root)
            self.assertEqual(result["status"],"measurement_valid");self.assertFalse(result["benchmark_accepted"])
            self.assertEqual(len(result["repeats"]),3)
            self.assertEqual(len(result["repeats"][0]["sections"]),3)
            self.assertAlmostEqual(result["repeats"][0]["fixed_weight_presented_fps"],100)

    def test_focus_loss_during_sprint_releases_jump_forward_and_sprint(self):
        ms=Mock();mc=Mock();live=Mock(side_effect=[None,RuntimeError("focus lost")])
        ms.player_position.return_value=[1.5,101,.5];ms.player_orientation.return_value=[0,6.5]
        parent=type("Parent",(),{"__init__":lambda self,write,stop=None:(setattr(self,"write",write),setattr(self,"stop",stop))[-1],
                                "live":lambda self:live()})
        spec=importlib.util.spec_from_file_location("rooms_safety",Path(__file__).resolve().parents[1]/"scenarios/lab_rooms_actions.py")
        module=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{"minescript":ms,"java":SimpleNamespace(JavaClass=lambda name:Mock()),
             "lab_common":SimpleNamespace(MC=mc,guard_world=Mock()),"lab_player_actions":SimpleNamespace(PlayerActions=parent),
             "lab_validation_core":SimpleNamespace(wait_live=Mock(),wait_position=Mock(),release_inputs=Mock(),block_kind=Mock())}):
            spec.loader.exec_module(module)
            module.MovementProbe=Mock(return_value=SimpleNamespace(sample=Mock(side_effect=RuntimeError("focus lost"))))
            with self.assertRaisesRegex(RuntimeError,"focus lost"):module.RoomActions(Mock()).walk_room_leg(SCENES[0],0,SCENES[0]["points"][1])
        ms.player_press_jump.assert_called_with(False);ms.player_press_forward.assert_called_with(False);ms.player_press_sprint.assert_called_with(False)

    def test_batched_movement_probe_checks_focus_and_releases_boolean_handles(self):
        future=lambda value:SimpleNamespace(wait=lambda:value)
        methods=[SimpleNamespace(target=8,member_id=n) for n in range(4)]
        mc=SimpleNamespace(player=SimpleNamespace(onGround=methods[2],isSprinting=methods[3]),
                           isWindowActive=methods[0],isPaused=methods[1])
        for active,paused,screen,position,expected in (
            (True,False,None,[1.5,101.,4.],None),
            (False,False,None,[1.5,101.,4.],"foreground"),
            (True,True,None,[1.5,101.,4.],"foreground"),
            (True,False,"ChatScreen",[1.5,101.,4.],"foreground"),
            (True,False,None,[1.5,float('nan'),4.],"Invalid movement")):
            ms=Mock();values=['true' if active else 'false','true' if paused else 'false','true','true']
            ms.java_call_method.as_async.side_effect=lambda target,member:future(member+10)
            ms.java_to_string.as_async.side_effect=lambda handle:future(values[handle-10])
            ms.player_position.as_async.return_value=future(position);ms.screen_name.as_async.return_value=future(screen)
            spec=importlib.util.spec_from_file_location("rooms_probe",Path(__file__).resolve().parents[1]/"scenarios/lab_rooms_actions.py")
            module=importlib.util.module_from_spec(spec)
            with patch.dict(sys.modules,{"minescript":ms,"java":SimpleNamespace(JavaClass=lambda name:Mock()),
                 "lab_common":SimpleNamespace(MC=mc,guard_world=Mock()),"lab_player_actions":SimpleNamespace(PlayerActions=object),
                 "lab_validation_core":SimpleNamespace(wait_live=Mock(),wait_position=Mock(),release_inputs=Mock(),block_kind=Mock())}):
                spec.loader.exec_module(module)
                probe=module.MovementProbe(None)
                if expected:
                    with self.assertRaisesRegex(RuntimeError,expected):probe.sample()
                else:self.assertEqual(probe.sample(),(position,True,True))
            ms.java_release.assert_called_once_with(10,11,12,13)


if __name__=="__main__":unittest.main()
