"""Bounded functional fixture in an exact disposable world; no Windows input."""
import json
import math
from pathlib import Path
import re
import time

import minescript as ms
import session_runtime
from java import JavaClass
from lab_common import PROFILE, CONDITIONS, MC, guard_world

MINIMUM = [-4, 199, -4]
MAXIMUM = [4, 202, 4]
START = [0.5, 200.0, -2.5]
END_Z = 1.5
LAMP = [3, 200, 2]
LEVER = [3, 201, 2]
AIR = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}
BlockPos = JavaClass("net.minecraft.core.BlockPos")
AABB = JavaClass("net.minecraft.world.phys.AABB")


def block_kind(state):
    value = str(state)
    match = re.match(r"Block\{(minecraft:[a-z0-9_]+)\}", value)
    return match.group(1) if match else value.split("[", 1)[0]


def read_block(position):
    return str(MC.level.getBlockState(BlockPos(*position)))


def read_blocks(positions):
    return [read_block(position) for position in positions]


def read_region_kinds():
    # The live Minescript region API returned None for every cell. Do not
    # interpret unknown data as air; read Minecraft's actual client states.
    if not all(MC.level.hasChunkAt(BlockPos(x, 199, z)) for x in (-4, 4) for z in (-4, 4)):
        raise RuntimeError("The fixture's four chunks are not loaded")
    # BlockGetter floors both AABB corners inclusively; MAXIMUM is already inclusive.
    box = AABB(*MINIMUM, *MAXIMUM)
    states = str(MC.level.getBlockStates(box).toList())
    kinds = re.findall(r"Block\{(minecraft:[a-z0-9_]+)\}", states)
    if len(kinds) != 324:
        raise RuntimeError("Minecraft region query did not return all 324 block states: " + states[:300])
    return kinds


def release_inputs():
    errors = []
    for name in ("forward", "backward", "left", "right", "jump", "sprint", "sneak", "use", "attack"):
        try:
            getattr(ms, "player_press_" + name)(False)
        except Exception as error:
            errors.append(name + ": " + str(error))
    if errors:
        raise RuntimeError("Input release failed: " + "; ".join(errors))


def assert_live(stop=None):
    if stop is not None and Path(stop).exists():
        raise RuntimeError("Validation cancelled")
    if session_runtime.live_issues(MC.isWindowActive(),MC.isPaused(),ms.screen_name()):
        raise RuntimeError("Validation requires an unpaused foreground world with chat closed")


def wait_live(seconds, stop=None):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        assert_live(stop)
        time.sleep(min(0.1, max(0, deadline - time.monotonic())))


def wait_position(expected, timeout=5, tolerance=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        actual = ms.player_position()
        if len(actual) == 3 and all(math.isfinite(a) and abs(a - b) <= tolerance for a, b in zip(actual, expected)):
            return actual
        time.sleep(0.05)
    raise RuntimeError("Player did not reach reset position")


class Fixture:
    def __init__(self, journal, write, stop=None):
        self.journal, self.write, self.stop = Path(journal), write, stop
        self.original_position = self.original_orientation = None
        self.original_slot = None
        self.empty_slot = None
        self.owned = []

    def persist(self):
        self.journal.write_text(json.dumps({"profile": str(PROFILE), "world_folder": CONDITIONS["world_folder"],
            "original_position": self.original_position, "original_orientation": self.original_orientation,
            "original_slot": self.original_slot, "owned": self.owned, "benchmark_accepted": False}, indent=2), encoding="utf-8")

    def build(self):
        guard_world()
        assert_live(self.stop)
        blocks = read_region_kinds()
        if any(block_kind(b) not in AIR for b in blocks):
            self.write({"event": "fixture_space_rejected", "returned_block_count": len(blocks),
                        "block_examples": list(dict.fromkeys(map(str, blocks)))[:20]})
            raise RuntimeError("Functional fixture space is occupied; nothing will be overwritten")
        self.write({"event": "fixture_space_verified", "loaded_chunks": 4, "verified_air_blocks": len(blocks)})
        self.original_position = ms.player_position()
        self.original_orientation = ms.player_orientation()
        inventory = ms.player_inventory()
        self.original_slot = next((item.slot for item in inventory if item.selected), None)
        self.persist()
        empty = [slot for slot in range(9) if not any(item.slot == slot for item in inventory)]
        if not empty:
            raise RuntimeError("A vacant hotbar slot is needed for the interaction check")
        self.empty_slot = empty[0]
        ms.player_inventory_select_slot(self.empty_slot)
        for x in range(-4, 5):
            for z in range(-4, 5):
                self.owned.append({"position": [x, 199, z], "kind": "minecraft:smooth_stone"})
        self.owned.extend(({"position": LAMP, "kind": "minecraft:redstone_lamp"},
                           {"position": LEVER, "kind": "minecraft:lever"}))
        self.persist()  # Recovery ownership exists before any block placement.
        guard_world()
        ms.execute("fill -4 199 -4 4 199 4 minecraft:smooth_stone")
        ms.execute("setblock 3 200 2 minecraft:redstone_lamp[lit=false]")
        ms.execute("setblock 3 201 2 minecraft:lever[face=floor,facing=north,powered=false]")
        ms.flush()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            states = read_blocks([record["position"] for record in self.owned])
            if len(states) == len(self.owned) and all(block_kind(a) == b["kind"] for a, b in zip(states, self.owned)):
                self.write({"event": "fixture_built", "owned_blocks": len(self.owned)})
                return
            time.sleep(0.1)
        raise RuntimeError("Fixture placement did not verify")

    def reset(self):
        guard_world()
        assert_live(self.stop)
        release_inputs()
        if self.empty_slot is not None:
            ms.player_inventory_select_slot(self.empty_slot)
        # Never change an unexpected block, even within the fixture.
        if block_kind(read_block(LEVER)) != "minecraft:lever" or block_kind(read_block(LAMP)) != "minecraft:redstone_lamp":
            raise RuntimeError("Fixture block identity changed")
        ms.execute("setblock 3 201 2 minecraft:lever[face=floor,facing=north,powered=false]")
        ms.execute("setblock 3 200 2 minecraft:redstone_lamp[lit=false]")
        ms.execute("tp @s 0.5 200 -2.5 0 0")
        ms.flush()
        position = wait_position(START)
        ms.player_set_orientation(0, 0)
        self.write({"event": "reset_verified", "position": position,
                    "lever": read_block(LEVER), "lamp": read_block(LAMP)})

    def walk(self):
        guard_world()
        assert_live(self.stop)
        start = wait_position(START)
        began, ticks = time.monotonic(), ms.world_info().game_ticks
        checkpoints = []
        try:
            ms.player_press_forward(True)
            self.write({"event": "movement_input_pressed"})
            while time.monotonic() - began < 4:
                assert_live(self.stop)
                pos = ms.player_position()
                checkpoints.append({"seconds": time.monotonic() - began, "position": pos})
                if abs(pos[0] - START[0]) > 0.1 or abs(pos[1] - START[1]) > 0.1 or not START[2] - 0.1 <= pos[2] <= END_Z + 0.6:
                    raise RuntimeError("Walking left the bounded route")
                if pos[2] >= END_Z:
                    break
                time.sleep(0.025)
            else:
                raise RuntimeError("Walking checkpoint timed out")
        finally:
            ms.player_press_forward(False)
            self.write({"event": "movement_input_released"})
        wait_live(0.15, self.stop)
        final = ms.player_position()
        if abs(final[0] - START[0]) > 0.1 or abs(final[1] - START[1]) > 0.1 or not END_Z <= final[2] <= END_Z + 0.6:
            raise RuntimeError("Walking endpoint failed")
        self.write({"event": "movement_verified", "start": start, "end": final,
                    "elapsed_seconds": time.monotonic() - began,
                    "elapsed_server_ticks": ms.world_info().game_ticks - ticks,
                    "timing": "held game input until a spatial checkpoint; never based on FPS",
                    "checkpoints": checkpoints})

    def interact(self):
        guard_world()
        assert_live(self.stop)
        ms.execute("tp @s 3.5 200 -0.5 0 0")
        ms.flush()
        wait_position([3.5, 200, -0.5])
        ms.player_look_at(3.5, 201.2, 2.5)
        wait_live(0.15, self.stop)
        target = ms.player_get_targeted_block(4.5)
        if target is None or list(target.position) != LEVER:
            raise RuntimeError("Crosshair did not target the fixture lever")
        before = read_block(LEVER)
        if "powered=false" not in before:
            raise RuntimeError("Lever was not reset before interaction")
        try:
            ms.player_press_use(True)
            wait_live(0.1, self.stop)
        finally:
            ms.player_press_use(False)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            assert_live(self.stop)
            lever, lamp = read_blocks([LEVER, LAMP])
            if "powered=true" in lever and "lit=true" in lamp:
                self.write({"event": "interaction_verified", "target": LEVER, "before": before,
                            "after": lever, "lamp": lamp, "method": "actual player use input"})
                return
            time.sleep(0.05)
        raise RuntimeError("Player interaction did not power the lever and lamp")

    def cleanup(self):
        errors = []
        try:
            release_inputs()
        except Exception as error:
            errors.append(str(error))
        try:
            guard_world()
            if self.original_position is not None:
                x, y, z = self.original_position
                yaw, pitch = self.original_orientation
                ms.execute(f"tp @s {x} {y} {z} {yaw} {pitch}")
                ms.flush()
                wait_position(self.original_position)
                if self.original_slot is not None:
                    ms.player_inventory_select_slot(self.original_slot)
            for owned in reversed(self.owned):
                pos = owned["position"]
                state = read_block(pos)
                if block_kind(state) == owned["kind"]:
                    ms.execute("setblock " + " ".join(map(str, pos)) + " minecraft:air")
                elif block_kind(state) not in AIR:
                    errors.append("Unexpected block preserved at " + str(pos))
            ms.flush()
            if self.owned:
                states = read_blocks([r["position"] for r in self.owned])
                if any(block_kind(b) not in AIR for b in states):
                    errors.append("Fixture cleanup did not verify")
        except Exception as error:
            errors.append(str(error))
        self.write({"event": "cleanup", "issues": errors, "player_restored": not errors})
        if errors:
            raise RuntimeError("Cleanup needs attention: " + "; ".join(errors))
        self.journal.with_suffix(".cleaned.json").write_text(self.journal.read_text(), encoding="utf-8")
