"""Verify the mixed-room route and retain complete in-scene intervals only."""
import math
from room_route_protocol import WORKLOAD,SCENES,ROOM_POLICY,SPRINT_JUMP_DISTANCES,walk_yaw


def scored_action_events(events):
    """Stop at this scored route's completion, before a later repeat's warmup."""
    for index,event in enumerate(events):
        if event["event"]=="player_actions_complete":
            return events[:index+1]
    raise ValueError("Scored room route never completed")


def distance(a,b):
    if len(a)!=len(b) or any(not math.isfinite(float(v)) for v in (*a,*b)):raise ValueError("Invalid room coordinates")
    return max(abs(x-y) for x,y in zip(a,b))


def camera_distance(a,b):
    if len(a)!=2 or len(b)!=2:raise ValueError("Invalid room camera")
    return max(abs((a[0]-b[0]+180)%360-180),abs(a[1]-b[1]))


def scene_evidence(events,frequency):
    starts=[e for e in events if e["event"]=="room_scene_start"]
    ends=[e for e in events if e["event"]=="room_scene_complete"]
    complete=[e for e in events if e["event"]=="player_actions_complete"]
    if [e["scene"] for e in starts]!=[s["id"] for s in SCENES] or [e["scene"] for e in ends]!=[s["id"] for s in SCENES]:
        raise ValueError("Missing, duplicated or reordered room scenes")
    if len(complete)!=1 or complete[0].get("workload")!=WORKLOAD or complete[0]["qpc"]<ends[-1]["qpc"]:
        raise ValueError("Mixed-room completion did not verify")
    result=[]
    for index,(scene,start,end) in enumerate(zip(SCENES,starts,ends)):
        if start["qpc"]>=end["qpc"] or (index and start["qpc"]<=ends[index-1]["qpc"]):raise ValueError("Room scene timing overlapped")
        if distance(start["position"],scene["points"][0])>.25 or distance(end["position"],scene["points"][-1])>.25:
            raise ValueError("Room start/end pose differs")
        window=[e for e in events if start["qpc"]<=e["qpc"]<=end["qpc"]]
        if any(e["event"].startswith("room_transition") for e in window):raise ValueError("Teleport occurred inside a scored room")
        content=start.get("content",{})
        if (scene["id"]=="mobs" and content.get("display_mobs",0)<10) or (scene["id"]=="paintings" and content.get("paintings",0)<3) or (scene["id"]=="redstone" and content.get("redstone_display_blocks",0)<5):
            raise ValueError("Room display population/content missing")
        leg_starts=[e for e in window if e["event"]=="room_route_leg_start"]
        leg_ends=[e for e in window if e["event"]=="room_route_leg_end"]
        count=len(scene["points"])-1
        if len(leg_starts)!=count or len(leg_ends)!=count:raise ValueError("Room walking legs missing")
        cameras=[];sample_count=0
        for leg,(a,b,ls,le) in enumerate(zip(scene["points"],scene["points"][1:],leg_starts,leg_ends)):
            sprint=scene["id"]=="mobs" and leg==0
            if ls.get("scene")!=scene["id"] or le.get("scene")!=scene["id"] or ls["leg"]!=leg or le["leg"]!=leg or not ls["qpc"]<le["qpc"]:
                raise ValueError("Room leg identity/order differs")
            if distance(ls["position"],a)>.25 or distance(ls["target"],b)>.001 or distance(le["position"],b)>.25:
                raise ValueError("Room leg endpoint differs")
            if ls["sprint"]!=sprint or (sprint and not le["sprinting_observed"]) or camera_distance(ls["orientation"],[walk_yaw(a,b),6.5])>1:
                raise ValueError("Room walking orientation/sprint differs")
            samples=[e for e in window if e["event"]=="room_route_path_sample" and e["leg"]==leg]
            if len(samples)<3:raise ValueError("Insufficient room trajectory samples")
            axis=0 if a[0]!=b[0] else 2;other=2 if axis==0 else 0;low,high=sorted((a[axis],b[axis]))
            positions=[ls["position"]]+[e["position"] for e in samples]+[le["position"]]
            for p in positions:
                if len(p)!=3 or any(not math.isfinite(float(v)) for v in p):raise ValueError("Invalid room trajectory")
                if abs(p[other]-a[other])>.35 or not low-.35<=p[axis]<=high+.35 or not (100.95<=p[1]<=102.4 if sprint else abs(p[1]-101)<=.35):
                    raise ValueError("Room trajectory left its corridor/jump envelope")
            if any(distance(a,b)>4 for a,b in zip(positions,positions[1:])) or any(not ls["qpc"]<=e["qpc"]<=le["qpc"] or e.get("scene")!=scene["id"] for e in samples):
                raise ValueError("Room trajectory coverage differs")
            sample_count+=len(samples)
            begin=[e for e in window if e["event"]=="room_camera_begin" and e["leg"]==leg]
            finish=[e for e in window if e["event"]=="room_camera_end" and e["leg"]==leg]
            views=scene["camera_yaws"] or (None,)
            if len(begin)!=len(views) or len(finish)!=len(views):raise ValueError("Room camera views missing")
            for view,(yaw,cb,ce) in enumerate(zip(views,begin,finish)):
                next_leg=leg_starts[leg+1]["qpc"] if leg+1<count else end["qpc"]
                if cb.get("scene")!=scene["id"] or ce.get("scene")!=scene["id"] or cb["view"]!=view or ce["view"]!=view or not le["qpc"]<=cb["qpc"]<ce["qpc"]<=next_leg:
                    raise ValueError("Room camera timing/identity differs")
                if (ce["qpc"]-cb["qpc"])/frequency<scene["camera_hold_seconds"]*.8 or distance(cb["position"],b)>.25 or camera_distance(cb["orientation"],ce["orientation"])>1:
                    raise ValueError("Room camera hold/pose differs")
                if yaw is not None and camera_distance(cb["orientation"],[yaw,scene["camera_pitch"]])>1:raise ValueError("Room camera target differs")
                if yaw is None and cb.get("target")!=list(scene["camera_target"]):raise ValueError("Mob camera target differs")
                cameras.append(cb["orientation"])
        result.append({"section":index,"scene":scene["id"],"start_qpc":start["qpc"],"end_qpc":end["qpc"],
                       "path_samples":sample_count,"camera":None,"camera_checkpoints":cameras})
    actions=[e for e in events if e["event"]=="player_action_verified"]
    if any(e["action"] in ("punch","inventory") for e in actions):raise ValueError("Removed action appeared in room route")
    expected={"sprint":1,"walk":6,"jump":len(SPRINT_JUMP_DISTANCES)}
    if {name:sum(e["action"]==name for e in actions) for name in expected}!=expected or len(actions)!=sum(expected.values()):
        raise ValueError("Mixed-room player action counts differ")
    jumps=[e for e in actions if e["action"]=="jump"]
    if [e.get("jump_index") for e in jumps]!=list(range(len(SPRINT_JUMP_DISTANCES))) or any(e.get("scene")!="mobs" or e.get("leg")!=0 or not e.get("sprinting_observed") or e.get("observed_height",0)<101.4 or e.get("ground_y")!=101. for e in jumps):
        raise ValueError("Sprint-jump evidence did not verify")
    first_leg=[e for e in events if e["event"]=="room_route_leg_start" and e.get("scene")=="mobs" and e["leg"]==0][0]
    first_end=[e for e in events if e["event"]=="room_route_leg_end" and e.get("scene")=="mobs" and e["leg"]==0][0]
    if any(not first_leg["qpc"]<e["qpc"]<first_end["qpc"] for e in jumps):raise ValueError("Jump happened outside the sprint leg")
    return result
