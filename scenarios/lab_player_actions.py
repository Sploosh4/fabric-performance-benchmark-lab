"""Repeated real-map player actions with observed outcomes and owned-screen cleanup."""
import time

import minescript as ms
from java import JavaClass
from lab_common import MC, guard_world
from lab_validation_core import assert_live, release_inputs, wait_live, wait_position, read_block, block_kind
from lab_mob_route import WAYPOINTS, verify_route

BlockPos = JavaClass("net.minecraft.core.BlockPos")
START = [1.5, 101.0, 0.5]


class PlayerActions:
    def __init__(self, write, stop=None):
        self.write, self.stop = write, stop
        self.inventory_screen = None
        self.original_slot = None
        self.segment_index = 0

    def live(self):
        assert_live(self.stop)

    def prepare(self):
        guard_world()
        self.live()
        surveyed_cells = verify_route()
        # Include braking room and jumping headroom; do not change the map.
        for z in range(-1, 10):
            if not MC.level.hasChunkAt(BlockPos(1, 100, z)):
                raise RuntimeError("Player-action corridor is not loaded")
            floor = read_block([1, 100, z])
            if block_kind(floor) in ("minecraft:air", "minecraft:water", "minecraft:lava"):
                raise RuntimeError("Player-action corridor lacks safe support")
            for y in (101, 102, 103, 104):
                state = MC.level.getBlockState(BlockPos(1, y, z))
                if not state.getCollisionShape(MC.level, BlockPos(1, y, z)).isEmpty() or block_kind(str(state)) in ("minecraft:water", "minecraft:lava"):
                    raise RuntimeError("Player-action corridor has an obstacle")
        if str(MC.player.getAbilities().flying).lower() != "false":
            raise RuntimeError("Walking/jumping requires flight already disabled")
        # Use an empty hotbar slot for visible empty-hand punches.
        inventory = ms.player_inventory()
        # Minescript represents only occupied slots; missing hotbar entries are empty.
        occupied = {i.slot for i in inventory}
        empty = next((slot for slot in range(9) if slot not in occupied), None)
        if empty is None:
            raise RuntimeError("Player-action test needs an existing empty hotbar slot")
        self.original_slot = ms.player_inventory_select_slot(empty)
        ms.execute("tp @s 1.5 101 0.5 0 6.5")
        ms.flush()
        wait_position(START)
        self.write({"event": "player_actions_ready", "planned_distance_blocks": 124, "mob_route_surveyed_cells": surveyed_cells, "waypoints": WAYPOINTS})

    def settle_waypoint(self, target):
        # Slow, physical corner correction keeps the next cross-aisle walk
        # away from adjacent displays; this never teleports the player.
        self.write({"event": "corner_correction_start", "segment": self.segment_index, "position": ms.player_position()})
        for axis in (0, 2):
            deadline = time.monotonic() + 3
            try:
                ms.player_press_sneak(True)
                while time.monotonic() < deadline:
                    self.live()
                    position = ms.player_position()
                    delta = target[axis] - position[axis]
                    if abs(delta) <= 0.12:
                        break
                    yaw = (-90 if delta > 0 else 90) if axis == 0 else (0 if delta > 0 else 180)
                    ms.player_set_orientation(yaw, 6.5)
                    ms.player_press_forward(True)
                    time.sleep(0.015)
                else:
                    raise RuntimeError("Mob-route corner correction timed out")
            finally:
                ms.player_press_forward(False)
                ms.player_press_sneak(False)
            wait_live(0.15, self.stop)
        final = ms.player_position()
        if max(abs(final[0] - target[0]), abs(final[2] - target[2])) > 0.2:
            raise RuntimeError("Mob-route corner did not settle")
        self.write({"event": "corner_correction_end", "segment": self.segment_index, "position": final})

    def mob_leg(self, target_x, target_z, sprint=False):
        guard_world()
        self.live()
        began = ms.player_position()
        axis = 0 if abs(target_x - began[0]) > 1 else 2
        other = 2 if axis == 0 else 0
        target = [target_x, 101.0, target_z]
        positive = target[axis] > began[axis]
        yaw = (-90 if positive else 90) if axis == 0 else (0 if positive else 180)
        ms.player_set_orientation(yaw, 6.5)
        observed_sprint = False
        deadline = time.monotonic() + max(8, abs(target[axis] - began[axis]) / 2.5 + 2)
        self.write({"event": "mob_route_segment_start", "segment": self.segment_index, "start": began,
                    "target": target, "sprint": sprint, "orientation": ms.player_orientation()})
        next_sample = 0
        try:
            ms.player_press_sprint(sprint)
            ms.player_press_forward(True)
            while time.monotonic() < deadline:
                self.live()
                position = ms.player_position()
                if time.monotonic() >= next_sample:
                    self.write({"event": "route_path_sample", "segment": self.segment_index, "position": position})
                    next_sample = time.monotonic() + 0.4
                observed_sprint |= str(MC.player.isSprinting()).lower() == "true"
                if abs(position[other] - began[other]) > 0.3 or abs(position[1] - 101) > 0.2 or not (-15 <= position[0] <= 15 and -0.8 <= position[2] <= 36.5):
                    raise RuntimeError("Player left the mob-route aisle")
                braking = 1.2 if sprint else 0.8
                if (positive and position[axis] >= target[axis] - braking) or (not positive and position[axis] <= target[axis] + braking):
                    break
                time.sleep(0.025)
            else:
                raise RuntimeError("Mob-route segment timed out")
        finally:
            ms.player_press_forward(False)
            ms.player_press_sprint(False)
        wait_live(0.2, self.stop)
        if sprint and not observed_sprint:
            raise RuntimeError("Actual sprint into/out of mob area did not verify")
        self.settle_waypoint(target)
        final = ms.player_position()
        self.write({"event": "player_action_verified", "action": "sprint" if sprint else "walk", "start": began,
                    "end": final, "sprinting_observed": observed_sprint, "route": "mob_display_loop",
                    "segment": self.segment_index})
        if target_z >= 17:
            nearby = [e for e in ms.entities(max_distance=35) if e.type not in (
                "entity.minecraft.player", "entity.minecraft.armor_stand", "entity.minecraft.text_display",
                "entity.minecraft.item_display", "entity.minecraft.block_display", "entity.minecraft.item_frame", "entity.minecraft.painting")
                and -16 <= e.position[0] <= 16 and 16 <= e.position[2] <= 36]
            self.write({"event": "mob_area_waypoint", "position": final, "nearby_display_entities": len(nearby),
                        "entity_types": sorted({e.type for e in nearby})})
            if len(nearby) < 10:
                raise RuntimeError("Mob area did not contain the expected display population")
            # Briefly look into the displays before the next movement segment.
            ms.player_look_at(0.5, 102, 26.5)
            self.write({"event": "mob_camera_checkpoint", "segment": self.segment_index,
                        "position": ms.player_position(), "orientation": ms.player_orientation(), "target": [0.5, 102, 26.5]})
            wait_live(0.25, self.stop)
        self.write({"event": "mob_route_segment_end", "segment": self.segment_index, "position": ms.player_position()})
        self.segment_index += 1

    def leg(self, target_z, sprint=False):
        guard_world()
        self.live()
        ms.player_set_orientation(0 if target_z > 4 else 180, 6.5)
        began = ms.player_position()
        positive = target_z > began[2]
        observed_sprint = False
        deadline = time.monotonic() + 8
        try:
            ms.player_press_sprint(sprint)
            ms.player_press_forward(True)
            while time.monotonic() < deadline:
                self.live()
                position = ms.player_position()
                observed_sprint |= str(MC.player.isSprinting()).lower() == "true"
                if abs(position[0] - START[0]) > 0.3 or abs(position[1] - START[1]) > 0.2 or not -0.8 <= position[2] <= 10.2:
                    raise RuntimeError("Player left the supported action corridor")
                braking = 1.2 if sprint else 0.8
                if (positive and position[2] >= target_z - braking) or (not positive and position[2] <= target_z + braking):
                    break
                time.sleep(0.025)
            else:
                raise RuntimeError("Player-action walking deadline exceeded")
        finally:
            ms.player_press_forward(False)
            ms.player_press_sprint(False)
        wait_live(0.2, self.stop)
        final = ms.player_position()
        self.write({"event": "player_action_endpoint", "target_z": target_z, "position": final, "sprint": sprint, "sprinting_observed": observed_sprint})
        if abs(final[2] - target_z) > 0.85 or (sprint and not observed_sprint):
            raise RuntimeError("Walking endpoint or actual sprint state did not verify")
        self.write({"event": "player_action_verified", "action": "sprint" if sprint else "walk", "start": began, "end": final, "sprinting_observed": observed_sprint})

    def jump(self):
        guard_world()
        self.live()
        baseline = ms.player_position()[1]
        if not MC.player.onGround():
            raise RuntimeError("Jump must start grounded")
        try:
            ms.player_press_jump(True)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                self.live()
                height = ms.player_position()[1]
                if height >= baseline + 0.4:
                    break
                time.sleep(0.025)
            else:
                raise RuntimeError("Actual jump displacement was not observed")
        finally:
            ms.player_press_jump(False)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            self.live()
            if MC.player.onGround() and abs(ms.player_position()[1] - baseline) < 0.05:
                self.write({"event": "player_action_verified", "action": "jump", "observed_height": height, "ground_y": baseline})
                return
            time.sleep(0.05)
        raise RuntimeError("Jump landing did not verify")

    def punch(self):
        guard_world()
        self.live()
        ms.player_set_orientation(0, -90)
        wait_live(0.15, self.stop)
        if str(MC.hitResult.getType()) != "MISS":
            raise RuntimeError("Punch target is not clear air; refusing to damage the map or mobs")
        try:
            ms.player_press_attack(True)
            deadline = time.monotonic() + 0.4
            while time.monotonic() < deadline:
                self.live()
                if str(MC.player.swinging).lower() == "true":
                    self.write({"event": "player_action_verified", "action": "punch", "target": "MISS", "swing_observed": True})
                    break
                time.sleep(0.01)
            else:
                raise RuntimeError("Punch animation was not observed")
        finally:
            ms.player_press_attack(False)
        wait_live(0.35, self.stop)

    def inventory(self):
        guard_world()
        self.live()
        release_inputs()
        try:
            ms.press_key_bind("key.inventory", True)
        finally:
            ms.press_key_bind("key.inventory", False)
        deadline = time.monotonic() + 3
        while ms.screen_name() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        screen = MC.screen
        if screen is None:
            raise RuntimeError("Inventory did not open")
        name = str(screen.getClass().getName())
        if name not in ("net.minecraft.client.gui.screens.inventory.InventoryScreen", "net.minecraft.client.gui.screens.inventory.CreativeModeInventoryScreen"):
            raise RuntimeError("Unexpected screen opened: " + name)
        self.inventory_screen = screen
        self.write({"event": "inventory_interval_start", "screen": name, "exclude_from_world_fps": True})
        try:
            until = time.monotonic() + 2
            while time.monotonic() < until:
                guard_world()
                if self.stop is not None and self.stop.exists():
                    raise RuntimeError("Validation cancelled in inventory")
                if not MC.isWindowActive() or MC.isPaused() or not screen.equals(MC.screen):
                    raise RuntimeError("Inventory state changed unexpectedly")
                time.sleep(0.1)
        finally:
            self.close_inventory()
        self.live()
        self.write({"event": "inventory_interval_end", "exclude_from_world_fps": True})
        self.write({"event": "player_action_verified", "action": "inventory", "screen": name})

    def close_inventory(self):
        if self.inventory_screen is not None:
            if self.inventory_screen.equals(MC.screen):
                MC.player.closeContainer()
                deadline = time.monotonic() + 3
                while self.inventory_screen.equals(MC.screen) and time.monotonic() < deadline:
                    time.sleep(0.05)
                if self.inventory_screen.equals(MC.screen):
                    raise RuntimeError("Owned inventory screen did not close")
            self.inventory_screen = None

    def run(self):
        for index, (x, z) in enumerate(WAYPOINTS[1:]):
            self.mob_leg(x, z, sprint=index in (0, 6))
        for _ in range(3):
            self.jump()
        for _ in range(5):
            self.punch()
        self.write({"event": "player_actions_complete", "workload": "mob_display_loop_v2"})

    def cleanup(self):
        errors = []
        for action in (self.close_inventory, lambda: ms.press_key_bind("key.inventory", False), release_inputs):
            try:
                action()
            except Exception as error:
                errors.append(str(error))
        if self.original_slot is not None:
            guard_world()
            ms.player_inventory_select_slot(self.original_slot)
        if errors:
            raise RuntimeError("Player-action cleanup failed: " + "; ".join(errors))
