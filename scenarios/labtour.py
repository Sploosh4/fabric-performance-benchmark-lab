"""Real-map walking/camera and bounded dimension-readiness validation; no FPS claims."""
import faulthandler
import json
import math
import re
import time
import uuid

import minescript as ms
from java import JavaClass
from lab_common import PROFILE, CONDITIONS, MC, guard_world, apply_graphics_conditions, sample_state, condition_issues
from lab_validation_core import release_inputs, assert_live, wait_live, wait_position, block_kind, read_block
from pair_protocol import QpcClock

BlockPos = JavaClass("net.minecraft.core.BlockPos")
AABB = JavaClass("net.minecraft.world.phys.AABB")
DIMENSIONS = ("minecraft:overworld", "minecraft:the_nether", "minecraft:the_end")
AIR = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}
GROUND = {"minecraft:netherrack", "minecraft:basalt", "minecraft:blackstone", "minecraft:nether_bricks", "minecraft:end_stone"}
nonce = uuid.uuid4().hex
directory = PROFILE / "minescript/lab-results"
directory.mkdir(exist_ok=True)
result = {"status": "failed", "nonce": nonce, "map_walk_repeats": 0, "dimensions_verified": [], "benchmark_accepted": False}
clock = QpcClock()
original_flying = None
original_position = original_orientation = None
owns_inputs = False


def current_guard():
    dimension = ms.world_info().dimension
    if dimension not in DIMENSIONS:
        raise RuntimeError("Tour entered an unexpected dimension")
    return guard_world(dimension)


def set_flying(value):
    current_guard()
    abilities = MC.player.getAbilities()
    if not abilities.mayfly:
        raise RuntimeError("Dimension camera validation requires the existing creative flight permission")
    abilities.getClass().getField("flying").setBoolean(abilities, value)
    MC.player.onUpdateAbilities()
    actual = str(abilities.flying).lower()
    write({"event": "flight_state", "expected": value, "actual": actual})
    if actual not in (("true",) if value else ("false",)):
        raise RuntimeError("Flight state did not verify: " + actual)


def states_between(first, last):
    if not MC.level.hasChunkAt(BlockPos(*first)) or not MC.level.hasChunkAt(BlockPos(*last)):
        raise RuntimeError("Tour survey chunks are not loaded")
    text = str(MC.level.getBlockStates(AABB(*first, *last)).toList())
    states = re.findall(r"Block\{minecraft:[a-z0-9_]+\}(?:\[[^\]]*\])?", text)
    count = math.prod(b - a + 1 for a, b in zip(first, last))
    if len(states) != count:
        raise RuntimeError("Tour survey returned incomplete block states")
    return states


def await_dimension(dimension, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if ms.world_info().dimension == dimension and ms.screen_name() is None:
                guard_world(dimension)
                assert_live()
                return
        except Exception as error:
            if ms.screen_name() is None:
                raise RuntimeError("Dimension readiness guard failed: " + str(error)) from error
        time.sleep(0.1)
    raise RuntimeError("Dimension did not become ready: " + dimension)


def camera_sweep(dimension, pitch=6.5):
    guard_world(dimension)
    for yaw in (0, 30, 60, 90, 60, 30, 0, -30, -60, -90, -60, -30, 0):
        assert_live()
        ms.player_set_orientation(yaw, pitch)
        wait_live(0.1)
        actual = ms.player_orientation()
        if abs(actual[0] - yaw) > 0.1 or abs(actual[1] - pitch) > 0.1:
            raise RuntimeError("Camera waypoint did not verify")
        write({"event": "camera_waypoint", "dimension": dimension, "orientation": actual})


def walk_leg(start, target_z, yaw):
    guard_world("minecraft:overworld")
    assert_live()
    ms.player_set_orientation(yaw, 6.5)
    beginning = ms.player_position()
    deadline = time.monotonic() + 6
    points = []
    forward = target_z > beginning[2]
    try:
        ms.player_press_forward(True)
        write({"event": "map_input_pressed", "target_z": target_z})
        while time.monotonic() < deadline:
            assert_live()
            pos = ms.player_position()
            points.append(pos)
            if abs(pos[0] - start[0]) > 0.3 or abs(pos[1] - start[1]) > 0.2 or not -0.1 <= pos[2] <= 9.1:
                raise RuntimeError("Player left the surveyed map corridor")
            if (forward and pos[2] >= target_z - 0.4) or (not forward and pos[2] <= target_z + 0.4):
                break
            time.sleep(0.025)
        else:
            raise RuntimeError("Real-map walking checkpoint timed out")
    finally:
        ms.player_press_forward(False)
        write({"event": "map_input_released"})
    wait_live(0.15)
    final = ms.player_position()
    write({"event": "map_walk_endpoint", "target_z": target_z, "position": final})
    if abs(final[2] - target_z) > 0.6:
        raise RuntimeError("Real-map walking endpoint differs")
    write({"event": "map_walk_leg_verified", "start": beginning, "end": final, "checkpoints": points})


def walk_map():
    guard_world("minecraft:overworld")
    # Survey bounded alternatives around the central lectern/buttons.
    route_x = None
    for x in (1, -1, 2, -2):
        supported = True
        for z in range(9):
            if not MC.level.hasChunkAt(BlockPos(x, 100, z)):
                raise RuntimeError("Map corridor chunk is not loaded")
            floor, feet, head = [read_block([x, y, z]) for y in (100, 101, 102)]
            floor_solid = not MC.level.getBlockState(BlockPos(x, 100, z)).getCollisionShape(MC.level, BlockPos(x, 100, z)).isEmpty()
            clear_above = all(MC.level.getBlockState(BlockPos(x, y, z)).getCollisionShape(MC.level, BlockPos(x, y, z)).isEmpty() for y in (101, 102))
            if block_kind(floor) in AIR | {"minecraft:water", "minecraft:lava"} or not floor_solid or not clear_above or any(block_kind(b) in {"minecraft:water", "minecraft:lava"} for b in (feet, head)):
                write({"event": "map_corridor_rejected", "x": x, "z": z, "states": [floor, feet, head]})
                supported = False
                break
        if supported:
            route_x = x + 0.5
            break
    if route_x is None:
        raise RuntimeError("No clear supported map corridor found; no blocks will be changed")
    write({"event": "map_corridor_verified", "x": route_x, "y": 101, "z_bounds": [0.5, 8.5]})
    for repeat in range(2):
        release_inputs()
        guard_world("minecraft:overworld")
        ms.execute(f"tp @s {route_x} 101 0.5 0 6.5")
        ms.flush()
        wait_position([route_x, 101, 0.5])
        walk_leg([route_x, 101, 0.5], 8.5, 0)
        camera_sweep("minecraft:overworld")
        walk_leg([route_x, 101, 0.5], 0.5, 180)
        camera_sweep("minecraft:overworld")
        result["map_walk_repeats"] += 1
        write({"event": "map_repeat_verified", "repeat": repeat})


def visit(dimension):
    current_guard()
    assert_live()
    release_inputs()
    began = time.monotonic()
    # Begin above the Nether roof / End island. Ground contact disables
    # creative flight automatically; enable it after the dimension transition.
    ms.execute("execute in " + dimension + " run tp @s 0.5 140 0.5 0 12")
    ms.flush()
    await_dimension(dimension)
    set_flying(True)
    deadline = time.monotonic() + 30
    while not MC.level.hasChunkAt(BlockPos(0, 80, 0)):
        if time.monotonic() > deadline:
            raise RuntimeError("Dimension's central chunk did not load")
        time.sleep(0.1)
    landing = None
    for x, z in ((0, 0), (4, 0), (-4, 0), (0, 4), (0, -4), (32, 0), (-32, 0), (0, 32), (0, -32)):
        assert_live()
        column = states_between([x, 10, z], [x, 124, z])
        write({"event": "dimension_column_survey", "dimension": dimension, "x": x, "z": z,
               "kinds": sorted(set(map(block_kind, column))), "non_air_count": sum(block_kind(b) not in AIR for b in column)})
        for index in range(111, -1, -1):
            if block_kind(column[index]) in GROUND and all(block_kind(column[index + offset]) in AIR for offset in (1, 2, 3)):
                landing = [x + 0.5, 11 + index, z + 0.5]
                break
        if landing is not None:
            break
    if landing is None:
        raise RuntimeError("No safe dimension camera location was found within the bounded survey")
    guard_world(dimension)
    ms.execute("tp @s " + " ".join(map(str, landing)) + " 0 12")
    ms.flush()
    wait_position(landing)
    wait_live(3)
    camera_sweep(dimension, 12)
    result["dimensions_verified"].append(dimension)
    write({"event": "dimension_visit_verified", "dimension": dimension, "position": landing,
           "readiness_seconds": time.monotonic() - began, "functional_render_distance": 4,
           "capture_performed": False, "note": "Initial loading/generation is separate from future timed steady-state scenes"})


with (directory / ("tour-" + nonce + ".jsonl")).open("x", encoding="utf-8") as output, \
     (directory / ("tour-" + nonce + ".stack.txt")).open("x", encoding="utf-8") as stack:
    def write(record):
        output.write(json.dumps({"nonce": nonce, "qpc": clock(), "qpc_frequency": clock.frequency,
                                 "unix_ns": time.time_ns(), "benchmark_accepted": False, **record}) + "\n")
        output.flush()
    faulthandler.dump_traceback_later(360, file=stack)
    try:
        guard_world()
        duplicates = [j.job_id for j in ms.job_info() if not j.self and j.command and j.command[0].lstrip("\\").removesuffix(".py") in ("labprepare", "labvalidate", "labtour", "laboverhead", "labpair", "labstate")]
        if duplicates:
            raise RuntimeError("Another lab job is active: " + str(duplicates))
        owns_inputs = True
        deadline = time.monotonic() + 20
        while ms.screen_name() is not None and time.monotonic() < deadline:
            time.sleep(0.1)
        initial = sample_state()
        issues = condition_issues(initial, require_pose=True)
        write({"event": "initial_state", "state": initial, "issues": issues})
        if issues:
            raise RuntimeError("Tour starts outside the verified conditions: " + ", ".join(issues))
        original_position, original_orientation = ms.player_position(), ms.player_orientation()
        original_flying = MC.player.getAbilities().flying
        walk_map()
        # This is a readiness/functionality visit, not a benchmark. Bound the
        # first dimension loads at RD/SD 4; restore the 12/8 contract afterward.
        MC.options.renderDistance().set(4)
        MC.options.simulationDistance().set(4)
        for dimension in ("minecraft:the_nether", "minecraft:the_end"):
            visit(dimension)
        result["status"] = "map_and_dimension_validation_passed"
    except Exception as error:
        result["error"] = str(error)
    finally:
        try:
            if owns_inputs:
                release_inputs()
            if original_position is not None:
                current_guard()
                x, y, z = original_position
                yaw, pitch = original_orientation
                ms.execute(f"execute in minecraft:overworld run tp @s {x} {y} {z} {yaw} {pitch}")
                ms.flush()
                await_dimension("minecraft:overworld")
                wait_position(original_position)
                set_flying(original_flying)
                apply_graphics_conditions()
                final = sample_state()
                final_issues = condition_issues(final, require_pose=True)
                write({"event": "restored_state", "state": final, "issues": final_issues})
                if final_issues:
                    raise RuntimeError("Restored conditions differ: " + ", ".join(final_issues))
        except Exception as error:
            result["cleanup_error"] = str(error)
            result["status"] = "failed"
        faulthandler.cancel_dump_traceback_later()
        write({"event": "result", **result})
        (directory / ("tour-" + nonce + ".json")).write_text(json.dumps(result, indent=2), encoding="utf-8")
ms.echo("Lab map/dimension validation: " + result["status"] + ". No benchmark accepted.")
