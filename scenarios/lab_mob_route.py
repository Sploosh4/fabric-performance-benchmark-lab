"""Fixed cardinal route through the real RestWorld mob display."""
import re
from java import JavaClass
from lab_common import MC, guard_world

BlockPos = JavaClass("net.minecraft.core.BlockPos")
AABB = JavaClass("net.minecraft.world.phys.AABB")
WAYPOINTS = ((1.5, 0.5), (1.5, 17.5), (-13.5, 17.5), (-13.5, 35.5),
             (13.5, 35.5), (13.5, 17.5), (1.5, 17.5), (1.5, 0.5))
SUPPORTED_FLOORS = {"minecraft:grass_block", "minecraft:stripped_birch_log", "minecraft:smooth_quartz",
                    "minecraft:redstone_lamp", "minecraft:blue_concrete"}
PASSABLE = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air", "minecraft:pale_oak_wall_sign"}


def route_cells():
    cells = set()
    for a, b in zip(WAYPOINTS, WAYPOINTS[1:]):
        if a[0] != b[0] and a[1] != b[1]:
            raise RuntimeError("Mob route must have cardinal segments")
        for x in range(int(min(a[0], b[0]) // 1), int(max(a[0], b[0]) // 1) + 1):
            for z in range(int(min(a[1], b[1]) // 1), int(max(a[1], b[1]) // 1) + 1):
                cells.add((x, z))
    return cells


def verify_route():
    guard_world()
    for x in (-14, 1, 13):
        for z in (0, 17, 35):
            if not MC.level.hasChunkAt(BlockPos(x, 100, z)):
                raise RuntimeError("Mob route has unloaded chunks")
    cells = route_cells()
    for y in (100, 101, 102):
        states = re.findall(r"Block\{(minecraft:[a-z0-9_]+)\}", str(MC.level.getBlockStates(AABB(-14, y, 0, 13, y, 35)).toList()))
        if len(states) != 28 * 36:
            raise RuntimeError("Mob route survey is incomplete")
        for x, z in cells:
            kind = states[z * 28 + x + 14]
            if kind not in (SUPPORTED_FLOORS if y == 100 else PASSABLE):
                raise RuntimeError(f"Mob route changed at {x},{y},{z}: {kind}")
        # Verify stream ordering against live individual reads, each time.
        for x, z in ((1, 0), (-14, 17), (13, 35)):
            if states[z * 28 + x + 14] not in str(MC.level.getBlockState(BlockPos(x, y, z))):
                raise RuntimeError("Mob route block ordering differs")
    return len(cells)
