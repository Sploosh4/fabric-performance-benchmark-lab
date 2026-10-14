"""Short mob walk plus the user's painting and redstone rooms; no block changes."""
import math
import re
import time
from pathlib import Path
import minescript as ms
import session_runtime
from java import JavaClass
from lab_common import MC,guard_world
from lab_player_actions import PlayerActions
from lab_validation_core import wait_live,wait_position,release_inputs,block_kind
from room_route_protocol import WORKLOAD,SCENES,SPRINT_JUMP_DISTANCES,walk_yaw

BlockPos=JavaClass("net.minecraft.core.BlockPos")
AABB=JavaClass("net.minecraft.world.phys.AABB")


class MovementProbe:
    """Read focus and player state together without repeated reflection/unboxing."""
    def __init__(self,stop):
        self.stop=stop
        # Retain both the player proxy and bound methods for this physical leg.
        self.player=MC.player
        self.methods=(MC.isWindowActive,MC.isPaused,self.player.onGround,self.player.isSprinting)

    def sample(self):
        if self.stop is not None and Path(self.stop).exists():raise RuntimeError("Validation cancelled")
        handles=[]
        try:
            # Public Minescript async calls share the next render execution pass.
            # These methods return Boolean; generic Java type discovery is unnecessary.
            pending=[ms.java_call_method.as_async(method.target,method.member_id) for method in self.methods]
            position=ms.player_position.as_async();screen=ms.screen_name.as_async()
            for future in pending:handles.append(future.wait())
            strings=[ms.java_to_string.as_async(handle) for handle in handles]
            values=[future.wait() for future in strings]
            actual=position.wait();current_screen=screen.wait()
            if any(value not in ("true","false") for value in values):raise RuntimeError("Movement state could not be read")
            active,paused,ground,sprint=[value=="true" for value in values]
            if session_runtime.live_issues(active,paused,current_screen):
                raise RuntimeError("Validation requires an unpaused foreground world with chat closed")
            if len(actual)!=3 or any(not math.isfinite(v) for v in actual):raise RuntimeError("Invalid movement position")
            return actual,ground,sprint
        finally:
            if handles:ms.java_release(*handles)


class RoomActions(PlayerActions):
    def settle_waypoint(self,target):
        if not session_runtime.diagnostic_only:
            return super().settle_waypoint(target)
        from background_corner import settle
        return settle(target,MovementProbe(self.stop),self.write,self.segment_index)

    def enter_scene(self,scene):
        self.live();guard_world();release_inputs()
        target=scene["points"][0]
        self.write({"event":"room_transition_start","scene":scene["id"],"exclude_from_score":True})
        ms.execute("tp @s " + " ".join(map(str,(*target,walk_yaw(*scene["points"][:2]),6.5))))
        ms.flush();wait_position(target)
        deadline=time.monotonic()+10
        while not MC.level.hasChunkAt(BlockPos(math.floor(target[0]),100,math.floor(target[2]))):
            self.live()
            if time.monotonic()>deadline:raise RuntimeError("Room chunk readiness timed out")
            time.sleep(.05)
        self.live()
        self.write({"event":"room_transition_complete","scene":scene["id"],"position":ms.player_position(),"exclude_from_score":True})

    def survey_leg(self,scene,a,b):
        lowx,highx=sorted((math.floor(a[0]),math.floor(b[0])))
        lowz,highz=sorted((math.floor(a[2]),math.floor(b[2])))
        for x,z in ((lowx,lowz),(highx,highz)):
            if not MC.level.hasChunkAt(BlockPos(x,100,z)):raise RuntimeError("Room corridor is not loaded")
        spanx=highx-lowx+1;width=spanx*(highz-lowz+1)
        # Query one horizontal layer at a time, as the validated legacy survey
        # does. A multi-height BlockPos stream advances Y before Z, so treating
        # it as stacked horizontal layers incorrectly labels air as floor.
        for y in range(100,105):
            states=re.findall(r"Block\{(minecraft:[a-z0-9_]+)\}",str(MC.level.getBlockStates(AABB(lowx,y,lowz,highx,y,highz)).toList()))
            if len(states)!=width:raise RuntimeError("Incomplete room corridor survey")
            for index,kind in enumerate(states):
                x=lowx+index%spanx;z=lowz+index//spanx
                if y==100:
                    if kind not in scene["floors"]:raise RuntimeError(f"Changed room floor at {x},{y},{z}: {kind}")
                elif kind not in ("minecraft:air","minecraft:cave_air","minecraft:void_air"):
                    pos=BlockPos(x,y,z);state=MC.level.getBlockState(pos)
                    if kind not in ("minecraft:stone_button","minecraft:pale_oak_wall_sign") or not state.getCollisionShape(MC.level,pos).isEmpty():
                        raise RuntimeError(f"Room corridor obstacle at {x},{y},{z}: {kind}")
            for index,(x,z) in ((0,(lowx,lowz)),(width-1,(highx,highz))):
                if block_kind(str(MC.level.getBlockState(BlockPos(x,y,z))))!=states[index]:
                    raise RuntimeError("Room survey stream ordering differs")
        return width

    def content(self,scene):
        if scene["id"] in ("mobs","paintings"):
            entities=ms.entities(max_distance=35)
            if scene["id"]=="paintings":
                count=sum(e.type=="entity.minecraft.painting" and -65<=e.position[0]<=-30 and 10<=e.position[2]<=45 for e in entities)
                if count<3:raise RuntimeError("Painting display population did not verify")
                return {"paintings":count}
            count=sum(e.type not in ("entity.minecraft.player","entity.minecraft.armor_stand","entity.minecraft.text_display",
                      "entity.minecraft.item_display","entity.minecraft.block_display","entity.minecraft.item_frame","entity.minecraft.painting")
                      and -16<=e.position[0]<=16 and 16<=e.position[2]<=36 for e in entities)
            if count<10:raise RuntimeError("Mob display population did not verify")
            return {"display_mobs":count}
        kinds=re.findall(r"Block\{(minecraft:[a-z0-9_]+)\}",str(MC.level.getBlockStates(AABB(35,101,-30,57,104,-14)).toList()))
        if len(kinds)!=23*4*17:raise RuntimeError("Redstone content survey incomplete")
        count=sum(k in ("minecraft:hopper","minecraft:piston","minecraft:sticky_piston","minecraft:repeater",
                        "minecraft:comparator","minecraft:observer","minecraft:dispenser","minecraft:dropper","minecraft:redstone_lamp") for k in kinds)
        if count<5:raise RuntimeError("Redstone display content did not verify")
        return {"redstone_display_blocks":count,"active_simulation_tested":False}

    def prepare(self):
        guard_world();self.live()
        if str(MC.player.getAbilities().flying).lower()!="false":raise RuntimeError("Room walking requires flight disabled")
        occupied={item.slot for item in ms.player_inventory()}
        empty=next((slot for slot in range(9) if slot not in occupied),None)
        if empty is None:raise RuntimeError("Room route needs an existing empty hotbar slot")
        self.original_slot=ms.player_inventory_select_slot(empty)
        # Surveys are outside scene timing, before the complete unscored/scored passes.
        for scene in SCENES:
            self.enter_scene(scene);cells=0;seen=set()
            for a,b in zip(scene["points"],scene["points"][1:]):
                key=tuple(sorted((a,b)))
                if key not in seen:cells+=self.survey_leg(scene,a,b);seen.add(key)
            self.write({"event":"room_survey_verified","scene":scene["id"],"cells":cells,**self.content(scene)})
        self.enter_scene(SCENES[0])
        self.write({"event":"rooms_actions_ready","workload":WORKLOAD,"mob_distance_blocks":40,"room_distance_blocks":32})

    def restart_after_unscored(self):
        """Reuse this repeat's survey after its verified, non-mutating full pass."""
        guard_world();self.live();release_inputs()
        if str(MC.player.getAbilities().flying).lower()!="false":
            raise RuntimeError("Room walking requires flight disabled")
        # Keep the original slot for final cleanup. Never resurvey inside scoring.
        self.segment_index=0
        self.enter_scene(SCENES[0])
        self.write({"event":"rooms_survey_reused","workload":WORKLOAD,
                    "scope":"same repeat, after complete unscored route; content checked again in every scored room"})

    def walk_room_leg(self,scene,leg,target):
        self.live();began=ms.player_position();axis=0 if began[0]!=target[0] else 2;other=2 if axis==0 else 0
        # Settled endpoints are within .2 blocks; select axis from the registered plan.
        expected_start=scene["points"][leg];axis=0 if expected_start[0]!=target[0] else 2;other=2 if axis==0 else 0
        yaw=walk_yaw(expected_start,target);sprint=scene["id"]=="mobs" and leg==0
        ms.player_set_orientation(yaw,6.5)
        self.write({"event":"room_route_leg_start","scene":scene["id"],"leg":leg,"position":began,
                    "target":target,"sprint":sprint,"orientation":ms.player_orientation()})
        observed=False;positive=target[axis]>began[axis];next_sample=0;jump=None;completed_jumps=0
        probe=MovementProbe(self.stop)
        deadline=time.monotonic()+max(8,abs(target[axis]-began[axis])/2.5+2)
        try:
            ms.player_press_sprint(sprint);ms.player_press_forward(True)
            while time.monotonic()<deadline:
                read_started=time.monotonic()
                position,on_ground,is_sprinting=probe.sample()
                observed|=is_sprinting
                if time.monotonic()>=next_sample:
                    self.write({"event":"room_route_path_sample","scene":scene["id"],"leg":leg,"position":position,
                                "probe_cost_seconds":time.monotonic()-read_started})
                    next_sample=time.monotonic()+.25
                if abs(position[other]-expected_start[other])>.3 or not (100.95<=position[1]<=102.4 if sprint else abs(position[1]-101)<=.2) or not min(expected_start[axis],target[axis])-.35<=position[axis]<=max(expected_start[axis],target[axis])+.35:
                    raise RuntimeError("Player left the registered room corridor")
                if sprint:
                    if jump is not None:
                        jump["height"]=max(jump["height"],position[1])
                        if position[1]>=101.4:
                            if not is_sprinting:raise RuntimeError("Sprinting stopped during the jump")
                            jump["sprint_in_air"]=True
                        if time.monotonic()-jump["started"]>=.15:ms.player_press_jump(False)
                        if on_ground and jump["height"]>=101.4:
                            if not observed or not jump.get("sprint_in_air") or abs(position[1]-101)>.05:raise RuntimeError("Sprint-jump landing did not verify")
                            self.write({"event":"player_action_verified","action":"jump","scene":scene["id"],"leg":leg,
                                        "jump_index":completed_jumps,"sprinting_observed":True,"observed_height":jump["height"],"ground_y":101.})
                            completed_jumps+=1;jump=None
                    if jump is None and completed_jumps<len(SPRINT_JUMP_DISTANCES) and abs(position[axis]-began[axis])>=SPRINT_JUMP_DISTANCES[completed_jumps] and on_ground:
                        if not is_sprinting:raise RuntimeError("Jump started without actual sprinting")
                        ms.player_press_jump(True);jump={"started":time.monotonic(),"height":position[1]}
                    if jump is not None and time.monotonic()-jump["started"]>3:raise RuntimeError("Sprint-jump timed out")
                brake=1.8 if sprint else 1.
                if (positive and position[axis]>=target[axis]-brake) or (not positive and position[axis]<=target[axis]+brake):break
                time.sleep(.025)
            else:raise RuntimeError("Room walking deadline exceeded")
        finally:
            ms.player_press_forward(False);ms.player_press_sprint(False);ms.player_press_jump(False)
        if sprint and (jump is not None or completed_jumps!=len(SPRINT_JUMP_DISTANCES)):
            raise RuntimeError("Sprint leg did not complete both grounded jumps")
        wait_live(.2,self.stop);self.settle_waypoint(target)
        if sprint and not observed:raise RuntimeError("Actual sprint did not verify")
        self.write({"event":"room_route_leg_end","scene":scene["id"],"leg":leg,"position":ms.player_position(),"sprinting_observed":observed})
        self.write({"event":"player_action_verified","action":"sprint" if sprint else "walk","scene":scene["id"],"leg":leg})
        self.segment_index+=1

    def camera_views(self,scene,leg):
        views=scene["camera_yaws"] or (None,)
        for index,yaw in enumerate(views):
            if yaw is None:ms.player_look_at(*scene["camera_target"])
            else:ms.player_set_orientation(yaw,scene["camera_pitch"])
            self.write({"event":"room_camera_begin","scene":scene["id"],"leg":leg,"view":index,
                        "position":ms.player_position(),"orientation":ms.player_orientation(),
                        "target":scene.get("camera_target"),"planned_yaw":yaw})
            wait_live(scene["camera_hold_seconds"],self.stop)
            self.write({"event":"room_camera_end","scene":scene["id"],"leg":leg,"view":index,"orientation":ms.player_orientation()})

    def run(self):
        for i,scene in enumerate(SCENES):
            if i:self.enter_scene(scene)
            evidence=self.content(scene)
            self.write({"event":"room_scene_start","scene":scene["id"],"position":ms.player_position(),"content":evidence})
            for leg,target in enumerate(scene["points"][1:]):
                self.walk_room_leg(scene,leg,target);self.camera_views(scene,leg)
            self.write({"event":"room_scene_complete","scene":scene["id"],"position":ms.player_position()})
        self.write({"event":"player_actions_complete","workload":WORKLOAD})
